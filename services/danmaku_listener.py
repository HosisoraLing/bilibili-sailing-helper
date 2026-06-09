import asyncio
import re
import threading
import time
from typing import Set, Optional

import aiohttp
import blivedm
import blivedm.models.web as web_models

from config import ROOM_ID, SESSDATA, BUVID3, BILI_JCT
from db.models import get_beijing_now
from services.auth_service import (
    get_active_auth_session,
    get_cached_code,
    mark_auth_success,
)
from utils.log_utils import get_logger
import logging

logger = get_logger(__name__)

# 抑制blivedm的unknown cmd噪音日志
logging.getLogger("blivedm").setLevel(logging.ERROR)

# =========================
# 全局状态
# =========================

DANMAKU_REGEX = re.compile(r"鉴权码[:：]\s*([a-zA-Z0-9]{8})")

_flask_app = None
_socketio = None
_listener_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()

_current_client: Optional[blivedm.BLiveClient] = None
_listener_loop: Optional[asyncio.AbstractEventLoop] = None
_http_session: Optional[aiohttp.ClientSession] = None

_authed_uids: Set[int] = set()
_authed_lock = threading.Lock()

# 存储每个UID的鉴权模式 {uid: {'login_mode': bool, 'reset_mode': bool}}
_auth_modes: dict[str, dict] = {}
_auth_mode_lock = threading.Lock()

# =========================
# 弹幕处理器（关键修复点）
# =========================

class AuthDMHandler(blivedm.BaseHandler):
    def _on_danmaku(
        self,
        client: blivedm.BLiveClient,
        message: web_models.DanmakuMessage
    ):
        uid = message.uid
        uname = message.uname
        text = message.msg.strip()

        # 控制台打印弹幕
        print(f"{uid} | {uname} : {text}", flush=True)

        # 已鉴权 UID 直接忽略
        with _authed_lock:
            if uid in _authed_uids:
                return

        if "鉴权码" not in text:
            return

        m = DANMAKU_REGEX.search(text)
        if not m:
            return

        input_code = m.group(1)
        uid_str = str(uid)

        # 立即将uid标记为正在鉴权，防止重复处理
        with _authed_lock:
            if uid in _authed_uids:
                return
            # 预先添加到已鉴权集合，防止竞态条件
            _authed_uids.add(uid)

        try:
            # 检查验证码
            correct_code = get_cached_code(uid_str)
            if not correct_code or input_code.lower() != correct_code.lower():
                # 验证码不匹配，移除预添加的标记
                with _authed_lock:
                    _authed_uids.discard(uid)
                return

            if not _flask_app:
                with _authed_lock:
                    _authed_uids.discard(uid)
                return

            # Flask 上下文内完成鉴权
            redirect_url = None
            with _flask_app.app_context():
                session = get_active_auth_session(uid_str)
                if not session or session.is_expired():
                    with _authed_lock:
                        _authed_uids.discard(uid)
                    return

                # 标记鉴权成功（带并发保护）
                if not mark_auth_success(session):
                    # session已被处理或过期
                    with _authed_lock:
                        _authed_uids.discard(uid)
                    return

                # 获取鉴权模式
                auth_mode = get_auth_mode(uid_str)
                reset_mode = auth_mode.get('reset_mode', False)
                login_mode = auth_mode.get('login_mode', False)

                # 检查用户是否有密码来决定跳转地址
                from db.models import User
                user = User.query.filter_by(uid=uid_str).first()

                if reset_mode:
                    redirect_url = f'/reset-password?uid={uid_str}'
                elif login_mode:
                    redirect_url = f'/login?uid={uid_str}&auto_login=true'
                elif user and user.password_hash:
                    redirect_url = f'/login?uid={uid_str}&auto_login=true'
                else:
                    redirect_url = f'/register?uid={uid_str}'

                # 清除鉴权模式
                clear_auth_mode(uid_str)

            # 确保redirect_url已设置
            if not redirect_url:
                redirect_url = f'/login?uid={uid_str}&auto_login=true'

            logger.warning(f"✅ 鉴权成功：{uname}({uid})")
            logger.warning(f"跳转地址：{redirect_url}")

            # Emit WebSocket event for instant notification
            if _socketio:
                try:
                    _socketio.emit('auth_success', {
                        'uid': uid_str,
                        'nickname': uname,
                        'redirect': redirect_url
                    }, room=f'auth_{uid_str}')
                    logger.warning(f"WebSocket事件已发送到房间：auth_{uid_str}")
                except Exception as e:
                    logger.warning(f"Failed to emit WebSocket event: {e}")

        except Exception as e:
            logger.error(f"鉴权处理异常: {e}", exc_info=True)
            # 发生异常时移除预添加的标记
            with _authed_lock:
                _authed_uids.discard(uid)

# =========================
# blivedm 客户端生命周期
# =========================

async def _run_client():
    global _current_client, _http_session

    # 每次启动时重新读取最新的Cookie
    import config as config_module
    from services.cookie_service import CookieService
    settings = CookieService.load_settings()
    bili = settings.get('bilibili', {})
    sessdata = bili.get('SESSDATA', '') or config_module.SESSDATA
    buvid3 = bili.get('buvid3', '') or config_module.BUVID3
    bili_jct = bili.get('bili_jct', '') or config_module.BILI_JCT
    
    room_id = int(ROOM_ID)

    cookie_jar = aiohttp.CookieJar()
    cookie_jar.update_cookies({
        "SESSDATA": sessdata,
        "buvid3": buvid3,
        "bili_jct": bili_jct,
    })

    _http_session = aiohttp.ClientSession(cookie_jar=cookie_jar)

    client = blivedm.BLiveClient(room_id, session=_http_session)
    client.set_handler(AuthDMHandler())
    _current_client = client

    logger.warning("🎧 弹幕监听已启动")

    try:
        client.start()
        await client.join()
    finally:
        if client.is_running:
            await client.stop()

        await _http_session.close()
        _http_session = None
        _current_client = None
        logger.warning("🔌 弹幕监听已退出")

def _run_listener_forever():
    global _listener_loop

    delay = 3
    loop = asyncio.new_event_loop()
    _listener_loop = loop
    asyncio.set_event_loop(loop)

    while not _stop_event.is_set():
        try:
            loop.run_until_complete(_run_client())
            delay = 3
            logger.warning("弹幕客户端正常退出，%d秒后重连", delay)
        except asyncio.CancelledError:
            logger.warning("弹幕客户端被取消，%d秒后重连", delay)
        except Exception:
            logger.exception("❌ 弹幕监听异常，%d秒后重连", delay)

        if _stop_event.is_set():
            break

        time.sleep(delay)
        delay = min(delay * 2, 60)

    loop.close()
    _listener_loop = None


def _watchdog():
    """守护线程：检测弹幕监听线程存活状态，死了就重启"""
    while not _stop_event.is_set():
        time.sleep(30)
        if _stop_event.is_set():
            break
        if _listener_thread is None or not _listener_thread.is_alive():
            logger.warning("⚠️ 弹幕监听线程已停止，正在重启...")
            start_danmaku_auth_listener(_flask_app, _socketio)

# =========================
# 对外接口
# =========================

_watchdog_thread: Optional[threading.Thread] = None


def start_danmaku_auth_listener(app_instance, socketio_instance=None):
    global _listener_thread, _watchdog_thread, _flask_app, _socketio

    _flask_app = app_instance
    _socketio = socketio_instance

    if _listener_thread and _listener_thread.is_alive():
        return

    _stop_event.clear()

    _listener_thread = threading.Thread(
        target=_run_listener_forever,
        daemon=True,
        name="DanmakuAuthListener"
    )
    _listener_thread.start()

    logger.warning("🚀 弹幕鉴权监听线程已启动")

    if _watchdog_thread is None or not _watchdog_thread.is_alive():
        _watchdog_thread = threading.Thread(
            target=_watchdog,
            daemon=True,
            name="DanmakuWatchdog"
        )
        _watchdog_thread.start()
        logger.warning("🐕 弹幕监听看门狗已启动")

def stop_danmaku_auth_listener():
    _stop_event.set()

    if _current_client and _listener_loop:
        asyncio.run_coroutine_threadsafe(
            _current_client.stop(),
            _listener_loop
        )

def watch_uid(uid: str):
    """允许某 UID 重新鉴权"""
    try:
        with _authed_lock:
            _authed_uids.discard(int(uid))
    except Exception:
        pass


def set_auth_mode(uid: str, login_mode: bool, reset_mode: bool):
    """设置UID的鉴权模式"""
    with _auth_mode_lock:
        _auth_modes[uid] = {
            'login_mode': login_mode,
            'reset_mode': reset_mode
        }


def get_auth_mode(uid: str) -> dict:
    """获取UID的鉴权模式"""
    with _auth_mode_lock:
        return _auth_modes.get(uid, {'login_mode': False, 'reset_mode': False})


def clear_auth_mode(uid: str):
    """清除UID的鉴权模式"""
    with _auth_mode_lock:
        _auth_modes.pop(uid, None)


def get_listener_status() -> dict:
    """
    获取弹幕监听状态
    
    Returns:
        dict: 包含以下字段
            - is_running: 是否正在运行
            - thread_alive: 线程是否存活
            - has_session: 是否有HTTP会话
            - last_check: 最后检查时间
    """
    global _listener_thread, _current_client, _http_session
    
    is_running = _listener_thread is not None and _listener_thread.is_alive()
    has_session = _http_session is not None
    
    return {
        'is_running': is_running,
        'thread_alive': is_running,
        'has_session': has_session,
        'last_check': get_beijing_now().isoformat()
    }


def restart_listener():
    """
    重启弹幕监听
    
    Returns:
        bool: 是否成功重启
    """
    global _flask_app, _socketio
    
    try:
        logger.info("正在重启弹幕监听...")
        
        # 停止当前监听
        stop_danmaku_auth_listener()
        time.sleep(2)
        
        # 重新启动
        if _flask_app:
            start_danmaku_auth_listener(_flask_app, _socketio)
            return True
        
        return False
    except Exception as e:
        logger.error(f"重启弹幕监听失败: {e}", exc_info=True)
        return False


import asyncio
import re
import threading
import time
from typing import Set, Optional

import aiohttp
import blivedm
import blivedm.models.web as web_models

from config import ROOM_ID, SESSDATA, BUVID3, BILI_JCT
from services.auth_service import (
    get_active_auth_session,
    get_cached_code,
    mark_auth_success,
)
from utils.log_utils import get_logger

logger = get_logger(__name__)

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

        # ✅ 控制台只打印这一行
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

        # Check for auth
        correct_code = get_cached_code(uid_str)
        if correct_code and input_code.lower() == correct_code.lower():
            if not _flask_app:
                return

            # Flask 上下文内完成鉴权
            with _flask_app.app_context():
                session = get_active_auth_session(uid_str)
                if not session or session.is_expired():
                    return

                mark_auth_success(session)

                # 获取鉴权模式
                auth_mode = get_auth_mode(uid_str)
                reset_mode = auth_mode.get('reset_mode', False)
                login_mode = auth_mode.get('login_mode', False)

                # 检查用户是否有密码来决定跳转地址
                from db.models import User
                user = User.query.filter_by(uid=uid_str).first()

                if reset_mode:
                    # 密码重置模式：跳转到重置密码页面
                    redirect_url = f'/reset-password?uid={uid_str}'
                elif login_mode:
                    # 鉴权登录模式：跳转到登录页（自动登录）
                    redirect_url = f'/login?uid={uid_str}&auto_login=true'
                elif user and user.password_hash:
                    # 有密码：跳转到登录页（自动登录）
                    redirect_url = f'/login?uid={uid_str}&auto_login=true'
                else:
                    # 无密码：跳转到注册页（设置密码）
                    redirect_url = f'/register?uid={uid_str}'

                # 清除鉴权模式
                clear_auth_mode(uid_str)

            with _authed_lock:
                _authed_uids.add(uid)

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
            return

# =========================
# blivedm 客户端生命周期
# =========================

async def _run_client():
    global _current_client, _http_session

    room_id = int(ROOM_ID)

    cookie_jar = aiohttp.CookieJar()
    cookie_jar.update_cookies({
        "SESSDATA": SESSDATA,
        "buvid3": BUVID3,
        "bili_jct": BILI_JCT,
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
        except Exception:
            logger.exception("❌ 弹幕监听异常，重连中")

        if _stop_event.is_set():
            break

        time.sleep(delay)
        delay = min(delay * 2, 60)

    loop.close()
    _listener_loop = None

# =========================
# 对外接口
# =========================

def start_danmaku_auth_listener(app_instance, socketio_instance=None):
    global _listener_thread, _flask_app, _socketio

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



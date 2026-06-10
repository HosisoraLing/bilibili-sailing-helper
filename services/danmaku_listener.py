import threading

from db.models import get_beijing_now
from utils.log_utils import get_logger


logger = get_logger(__name__)

_auth_modes: dict[str, dict] = {}
_auth_mode_lock = threading.Lock()


def start_danmaku_auth_listener(app_instance=None, socketio_instance=None):
    logger.info("旧版 in-process 弹幕监听已停用；请运行 danmaku-worker 角色")
    return False


def stop_danmaku_auth_listener():
    return True


def restart_listener():
    logger.info("旧版监听重启请求已忽略；danmaku-worker 会通过 Cookie version 自动重连")
    return True


def watch_uid(uid: str):
    return None


def set_auth_mode(uid: str, login_mode: bool, reset_mode: bool):
    with _auth_mode_lock:
        _auth_modes[str(uid)] = {
            "login_mode": bool(login_mode),
            "reset_mode": bool(reset_mode),
        }


def get_auth_mode(uid: str) -> dict:
    with _auth_mode_lock:
        return _auth_modes.get(str(uid), {"login_mode": False, "reset_mode": False})


def clear_auth_mode(uid: str):
    with _auth_mode_lock:
        _auth_modes.pop(str(uid), None)


def get_listener_status() -> dict:
    return {
        "is_running": False,
        "thread_alive": False,
        "has_session": False,
        "role": "danmaku-worker",
        "message": "弹幕监听已迁移到独立 danmaku-worker 角色",
        "last_check": get_beijing_now().isoformat(),
    }

import random
import string
import threading
from datetime import timedelta
from typing import Optional, Tuple

from db.models import db, AuthSession, User, get_beijing_now

# =========================
# 内存验证码缓存 { uid: code }
# =========================
_auth_code_cache: dict[str, str] = {}
_auth_cache_lock = threading.Lock()  # 添加线程锁


def generate_auth_code(uid: str, length: int = 8) -> str:
    """
    生成随机验证码，避免与上一次重复（线程安全）
    """
    chars = string.ascii_letters + string.digits

    with _auth_cache_lock:
        old_code = _auth_code_cache.get(uid)

        while True:
            code = ''.join(random.choice(chars) for _ in range(length))
            if code != old_code:
                break

        _auth_code_cache[uid] = code
        return code


def create_auth_session(uid: str) -> Tuple[AuthSession, str]:
    """
    创建新的鉴权会话（线程安全）
    """
    uid = str(uid)

    code = generate_auth_code(uid)

    now = get_beijing_now()
    session = AuthSession(
        uid=uid,
        status='pending',
        expires_at=now + timedelta(minutes=5)
    )

    db.session.add(session)
    db.session.commit()

    return session, code


def get_active_auth_session(uid: str) -> Optional[AuthSession]:
    """
    获取最新的一条鉴权会话
    """
    return AuthSession.query.filter_by(
        uid=str(uid)
    ).order_by(AuthSession.created_at.desc()).first()


def get_cached_code(uid: str) -> Optional[str]:
    """
    获取当前 UID 的内存验证码（线程安全）
    """
    with _auth_cache_lock:
        return _auth_code_cache.get(str(uid))


def mark_auth_success(session: AuthSession):
    """
    标记鉴权成功
    """
    session.mark_success()

    # 成功后清理验证码，防止复用
    with _auth_cache_lock:
        _auth_code_cache.pop(session.uid, None)

    db.session.commit()


def mark_auth_expired(session: AuthSession):
    """
    标记鉴权过期
    """
    session.mark_expired()

    with _auth_cache_lock:
        _auth_code_cache.pop(session.uid, None)

    db.session.commit()


def can_auto_login(uid: str) -> bool:
    """
    检查用户是否可以自动登录（已有密码）
    """
    uid = str(uid)
    user = User.query.filter_by(uid=uid).first()
    return user is not None and user.password_hash is not None


def clear_auth_cache(uid: str = None):
    """
    清理鉴权缓存（线程安全）

    Args:
        uid: 如果指定，只清理该UID的缓存；否则清理所有过期缓存
    """
    with _auth_cache_lock:
        if uid:
            _auth_code_cache.pop(str(uid), None)
        else:
            # 获取所有活跃的鉴权会话
            active_sessions = AuthSession.query.filter(
                AuthSession.status == 'pending'
            ).all()
            active_uids = {s.uid for s in active_sessions}

            # 清理不在活跃会话中的缓存
            expired_uids = [
                uid for uid in _auth_code_cache
                if uid not in active_uids
            ]
            for uid in expired_uids:
                del _auth_code_cache[uid]



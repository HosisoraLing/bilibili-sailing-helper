import random
import string
from datetime import timedelta
from typing import Optional, Tuple

from db.models import db, AuthSession, User, get_beijing_now

# =========================
# 内存验证码缓存 { uid: code }
# =========================
_auth_code_cache: dict[str, str] = {}


def generate_auth_code(uid: str, length: int = 8) -> str:
    """
    生成随机验证码，避免与上一次重复
    """
    chars = string.ascii_letters + string.digits
    old_code = _auth_code_cache.get(uid)

    while True:
        code = ''.join(random.choice(chars) for _ in range(length))
        if code != old_code:
            break

    _auth_code_cache[uid] = code
    return code


def create_auth_session(uid: str) -> Tuple[AuthSession, str]:
    """
    创建新的鉴权会话（不提前废弃旧会话）
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
    获取当前 UID 的内存验证码
    """
    return _auth_code_cache.get(str(uid))


def mark_auth_success(session: AuthSession):
    """
    标记鉴权成功
    """
    session.mark_success()

    # 成功后清理验证码，防止复用
    _auth_code_cache.pop(session.uid, None)

    db.session.commit()


def mark_auth_expired(session: AuthSession):
    """
    标记鉴权过期
    """
    session.mark_expired()

    _auth_code_cache.pop(session.uid, None)

    db.session.commit()


def can_auto_login(uid: str) -> bool:
    """
    检查用户是否可以自动登录（已有密码）
    """
    uid = str(uid)
    user = User.query.filter_by(uid=uid).first()
    return user is not None and user.password_hash is not None



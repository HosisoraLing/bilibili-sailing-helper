import secrets
import string
import threading
from datetime import timedelta
from typing import Optional, Tuple

from db.models import db, AuthSession, User, get_beijing_now
from utils.log_utils import get_logger

logger = get_logger(__name__)

# =========================
# 内存验证码缓存 { uid: code }
# =========================
_auth_code_cache: dict[str, str] = {}
_auth_cache_lock = threading.Lock()

# Session操作锁 { uid: lock }
_session_locks: dict[str, threading.Lock] = {}
_session_locks_lock = threading.Lock()


def _get_session_lock(uid: str) -> threading.Lock:
    """获取指定UID的session操作锁"""
    with _session_locks_lock:
        if uid not in _session_locks:
            _session_locks[uid] = threading.Lock()
        return _session_locks[uid]


def generate_auth_code(uid: str, length: int = 8) -> str:
    """
    生成随机验证码，避免与上一次重复（线程安全）
    """
    chars = string.ascii_letters + string.digits

    with _auth_cache_lock:
        old_code = _auth_code_cache.get(uid)

        while True:
            code = ''.join(secrets.choice(chars) for _ in range(length))
            if code != old_code:
                break

        _auth_code_cache[uid] = code
        return code


def create_auth_session(uid: str) -> Tuple[AuthSession, str]:
    """
    创建新的鉴权会话（线程安全）
    如果存在未过期的pending session，直接复用
    """
    uid = str(uid)
    
    with _get_session_lock(uid):
        # 检查是否存在未过期的pending session
        existing = AuthSession.query.filter_by(
            uid=uid,
            status='pending'
        ).order_by(AuthSession.created_at.desc()).first()
        
        if existing and not existing.is_expired():
            # 复用现有session，返回新的验证码
            code = generate_auth_code(uid)
            return existing, code
        
        # 创建新session
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
    获取最新的一条鉴权会话（返回pending或success状态）
    """
    return AuthSession.query.filter(
        AuthSession.uid == str(uid),
        AuthSession.status.in_(['pending', 'success'])
    ).order_by(AuthSession.created_at.desc()).first()


def get_cached_code(uid: str) -> Optional[str]:
    """
    获取当前 UID 的内存验证码（线程安全）
    """
    with _auth_cache_lock:
        return _auth_code_cache.get(str(uid))


def mark_auth_success(session: AuthSession) -> bool:
    """
    标记鉴权成功（带并发保护）
    
    Returns:
        bool: 是否成功标记（False表示session已被处理）
    """
    uid = session.uid
    
    with _get_session_lock(uid):
        # 重新从数据库获取session，确保状态最新
        db.session.refresh(session)
        
        # 检查session是否仍处于pending状态
        if session.status != 'pending':
            logger.warning(f"Session已被处理: uid={uid}, status={session.status}")
            return False
        
        # 检查session是否过期
        if session.is_expired():
            logger.warning(f"Session已过期: uid={uid}")
            session.mark_expired()
            db.session.commit()
            return False
        
        # 标记成功
        session.mark_success()
        
        # 清理验证码，防止复用
        with _auth_cache_lock:
            _auth_code_cache.pop(uid, None)
        
        db.session.commit()
        
        logger.info(f"Session标记成功: uid={uid}, session_id={session.id}")
        return True


def mark_auth_expired(session: AuthSession):
    """
    标记鉴权过期
    """
    uid = session.uid
    
    with _get_session_lock(uid):
        session.mark_expired()
        
        with _auth_cache_lock:
            _auth_code_cache.pop(uid, None)
        
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


def cleanup_expired_sessions():
    """
    清理过期的session（定期调用）
    """
    now = get_beijing_now()
    
    # 将所有过期的pending session标记为expired
    expired_count = AuthSession.query.filter(
        AuthSession.status == 'pending',
        AuthSession.expires_at < now
    ).update({'status': 'expired'})
    
    if expired_count > 0:
        db.session.commit()
        logger.info(f"清理了 {expired_count} 个过期session")
    
    return expired_count



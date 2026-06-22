"""
用户服务模块
处理用户认证、登录、注册、密码重置等业务逻辑
"""
from typing import Optional, Tuple

from db.models import db, User, Guard
from config import Config
from services.security import (
    SecurityManager,
    PasswordValidator,
    login_limiter,
)
from services.auth_service import get_active_auth_session
from utils.cache_utils import user_cache, guard_cache, cached


class UserService:
    """用户服务类"""

    @staticmethod
    def is_admin_uid(uid: str) -> bool:
        """检查 UID 是否在管理员白名单中"""
        return uid in Config.ADMIN_UIDS

    @staticmethod
    @cached(guard_cache, "guard_nickname", ttl=300)
    def get_guard_nickname(uid: str) -> Optional[str]:
        """获取舰长昵称，如果不是舰长返回 None"""
        guard = Guard.query.filter_by(uid=uid).first()
        return guard.nickname if guard else None

    @staticmethod
    def get_or_create_user(uid: str, is_admin: bool = False) -> Tuple[User, bool]:
        """
        获取或创建用户
        返回: (user, created) - 用户对象和是否为新创建
        """
        uid = str(uid)

        # 尝试从缓存获取
        cache_key = f"user:{uid}"
        cached_user = user_cache.get(cache_key)
        if cached_user:
            return cached_user, False

        user = User.query.filter_by(uid=uid).first()

        if user:
            # 缓存用户对象
            user_cache.set(cache_key, user, ttl=300)
            return user, False

        # 获取舰长信息用于昵称
        guard_nickname = UserService.get_guard_nickname(uid)

        if is_admin:
            user = User(uid=uid, nickname=f"管理员_{uid}")
            user.add_role('admin')
        else:
            user = User(uid=uid, nickname=guard_nickname or f"用户_{uid}")

        db.session.add(user)
        db.session.commit()

        # 缓存新创建的用户
        user_cache.set(cache_key, user, ttl=300)

        return user, True

    @staticmethod
    def invalidate_user_cache(uid: str):
        """清除用户缓存"""
        user_cache.delete(f"user:{uid}")
        guard_cache.delete(f"guard_nickname:{uid}")

    @staticmethod
    def validate_user_access(uid: str) -> Tuple[bool, Optional[str]]:
        """
        验证用户访问权限
        返回: (is_valid, error_message)
        """
        uid = str(uid)

        # 检查是否是管理员（管理员可以不是陪伴榜用户）
        is_admin = UserService.is_admin_uid(uid)

        if is_admin:
            return True, None

        # 检查是否已有用户记录且已设置密码（已注册用户保留访问权限）
        user = User.query.filter_by(uid=uid).first()
        if user and user.password_hash:
            return True, None

        # 检查是否是陪伴榜用户（粉丝团成员）
        is_companion = UserService.is_companion_user(uid)

        if is_companion:
            return True, None

        return False, "您不在当前陪伴榜名单中"

    @staticmethod
    def is_companion_user(uid: str) -> bool:
        """
        检查用户是否在陪伴榜中（有大航海陪伴天数的用户）
        先检查本地数据库（手动添加的舰长），再检查B站API实时数据
        """
        uid = str(uid)

        # 1. 先检查本地Guard表（手动添加的舰长记录）- 使用缓存
        cache_key = f"guard:{uid}"
        cached_guard = guard_cache.get(cache_key)
        if cached_guard:
            return True

        guard = Guard.query.filter_by(uid=uid).first()
        if guard:
            # 缓存舰长信息
            guard_cache.set(cache_key, guard, ttl=300)
            return True

        # 2. 再检查B站API实时数据
        try:
            from services.guard_service import fetch_guards

            # 获取舰长/陪伴榜用户列表 - 使用缓存版本
            guards_data = fetch_guards()

            # 检查UID是否在舰长列表中
            if uid in guards_data:
                return True

            return False
        except Exception as e:
            # 如果API调用失败，记录错误并返回False
            print(f"⚠ 检查陪伴榜用户失败: {e}")
            return False

    @staticmethod
    def check_password_setup(uid: str) -> Tuple[bool, Optional[str]]:
        """
        检查密码设置状态
        返回: (has_password, message) - 是否已设置密码，需要跳转的提示信息
        """
        uid = str(uid)

        # 尝试从缓存获取
        cache_key = f"user:{uid}"
        user = user_cache.get(cache_key)

        if not user:
            user = User.query.filter_by(uid=uid).first()
            if user:
                user_cache.set(cache_key, user, ttl=300)

        if not user or not user.password_hash:
            return False, "您还没有设置密码，请先注册账号"

        return True, None

    @staticmethod
    def check_auth_session(uid: str) -> Tuple[bool, Optional[str]]:
        """
        检查鉴权会话状态
        返回: (is_valid, error_message)
        """
        uid = str(uid)
        session = get_active_auth_session(uid)

        if not session or session.is_expired():
            return False, "鉴权已过期，请重新验证"

        if session.status != 'success':
            return False, "鉴权未完成，请先完成验证"

        return True, None

    @staticmethod
    def validate_login_rate_limit(uid: str) -> Tuple[bool, Optional[int]]:
        """
        验证登录速率限制
        返回: (is_allowed, wait_time)
        """
        return login_limiter.is_allowed(f"login_{uid}")

    @staticmethod
    def reset_login_rate_limit(uid: str):
        """重置登录速率限制"""
        login_limiter.reset(f"login_{uid}")

    @staticmethod
    def validate_password_strength(password: str) -> Tuple[bool, str]:
        """验证密码强度"""
        return PasswordValidator.validate_password_strength(password)

    @staticmethod
    def validate_phone(phone: str) -> Tuple[bool, str]:
        """验证手机号格式"""
        return PasswordValidator.validate_phone(phone)

    @staticmethod
    def validate_uid_format(uid: str) -> Tuple[bool, str]:
        """验证 UID 格式"""
        return PasswordValidator.validate_uid(uid)

    @staticmethod
    def verify_csrf_token(token: str) -> bool:
        """验证 CSRF Token"""
        return SecurityManager.verify_csrf_token(token)

    @staticmethod
    def verify_sensitive_request() -> Tuple[bool, Optional[str]]:
        """验证敏感操作请求"""
        from services.security import RequestValidator
        return RequestValidator.validate_sensitive_request()

    @staticmethod
    def validate_passwords_match(password: str, confirm: str) -> Tuple[bool, str]:
        """验证两次密码是否一致"""
        if password != confirm:
            return False, "两次输入的密码不一致"
        return True, "密码匹配"

    @staticmethod
    def set_user_password(user: User, password: str):
        """设置用户密码"""
        user.set_password(password)
        db.session.commit()
        # 清除用户缓存
        UserService.invalidate_user_cache(user.uid)

    @staticmethod
    def clear_session():
        """清除当前会话（防止会话固定攻击）"""
        from flask import session
        session.clear()
        session.modified = True

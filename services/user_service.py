"""
用户服务模块
处理用户认证、登录、注册、密码重置等业务逻辑
"""
from typing import Optional, Tuple

from db.models import db, User, Guard, AuthAttempt
from config import Config
from services.security import (
    SecurityManager,
    PasswordValidator,
    login_limiter,
)
from services.auth_service import get_active_auth_session


class UserService:
    """用户服务类"""

    @staticmethod
    def is_admin_uid(uid: str) -> bool:
        """检查 UID 是否在管理员白名单中"""
        return uid in Config.ADMIN_UIDS

    @staticmethod
    def get_guard_nickname(uid: str) -> Optional[str]:
        """获取舰长昵称，如果不是舰长返回 None"""
        guard = Guard.query.filter_by(uid=uid).first()
        return guard.nickname if guard else None

    @staticmethod
    def _get_best_nickname(uid: str) -> str:
        """
        获取用户最佳昵称（按优先级，不含B站API调用以避免阻塞）：
        1. Guard 表中的舰长昵称（来自B站API同步）
        2. AuthAttempt 中的弹幕昵称（来自用户发送验证码时的B站昵称）
        3. 默认占位符（B站API查询由调用方异步补充）
        """
        guard_nickname = UserService.get_guard_nickname(uid)
        if guard_nickname:
            return guard_nickname

        attempt = AuthAttempt.query.filter_by(uid=uid).filter(
            AuthAttempt.nickname.isnot(None),
            AuthAttempt.nickname != ''
        ).order_by(AuthAttempt.created_at.desc()).first()
        if attempt and attempt.nickname:
            return attempt.nickname

        return f"用户_{uid}"

    @staticmethod
    def get_or_create_user(uid: str, is_admin: bool = False) -> Tuple[User, bool]:
        """
        获取或创建用户
        返回: (user, created) - 用户对象和是否为新创建
        """
        uid = str(uid)

        user = User.query.filter_by(uid=uid).first()

        if user:
            return user, False

        nickname = UserService._get_best_nickname(uid)

        if is_admin:
            user = User(uid=uid, nickname=f"管理员_{uid}")
            user.add_role('admin')
        else:
            user = User(uid=uid, nickname=nickname)

        db.session.add(user)
        db.session.commit()

        # B站API查询放到DB提交后，避免网络延迟阻塞用户创建
        if nickname == f"用户_{uid}":
            try:
                from services.guard_service import fetch_user_nickname
                api_nickname = fetch_user_nickname(uid)
                if api_nickname:
                    user.nickname = api_nickname
                    db.session.commit()
            except Exception:
                pass  # API失败不影响用户创建

        return user, True

    @staticmethod
    def invalidate_user_cache(uid: str):
        """清除用户缓存（已移除内存缓存，保留接口兼容性）"""
        pass

    @staticmethod
    def validate_user_access(uid: str) -> Tuple[bool, Optional[str]]:
        """
        验证用户访问权限
        返回: (is_valid, error_message)
        """
        uid = str(uid)

        # 检查是否是管理员（管理员可以不是陪伴榜用户）
        is_admin = UserService.is_admin_uid(uid)

        # 检查是否是陪伴榜用户（粉丝团成员）
        is_companion = UserService.is_companion_user(uid)

        # 如果既不是管理员也不是陪伴榜用户
        if not is_admin and not is_companion:
            return False, "您不在当前陪伴榜名单中"

        return True, None

    @staticmethod
    def is_companion_user(uid: str) -> bool:
        """
        检查用户是否在陪伴榜中（有大航海陪伴天数的用户）
        只检查本地数据库，不调用 B站 API（避免阻塞请求）
        """
        uid = str(uid)
        guard = Guard.query.filter_by(uid=uid).first()
        return guard is not None

    @staticmethod
    def check_password_setup(uid: str) -> Tuple[bool, Optional[str]]:
        """
        检查密码设置状态
        返回: (has_password, message) - 是否已设置密码，需要跳转的提示信息
        """
        uid = str(uid)

        user = User.query.filter_by(uid=uid).first()

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
        UserService.invalidate_user_cache(user.uid)

    @staticmethod
    def update_nickname(user: User, nickname: str) -> Tuple[bool, str]:
        """
        更新用户昵称
        返回: (success, message)
        """
        nickname = nickname.strip()
        if not nickname:
            return False, "昵称不能为空"
        if len(nickname) > 64:
            return False, "昵称不能超过64个字符"

        user.nickname = nickname
        user.nickname_customized = True
        db.session.commit()
        UserService.invalidate_user_cache(user.uid)
        return True, "昵称更新成功"

    @staticmethod
    def clear_session():
        """清除当前会话（防止会话固定攻击）"""
        from flask import session
        session.clear()
        session.modified = True

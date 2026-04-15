"""
常量定义模块
统一管理应用中的常量、角色类型、配置等
"""

from enum import Enum


class GuardLevel(str, Enum):
    """舰长身份等级"""
    GUARD = 'guard'        # 舰长
    CAPTAIN = 'captain'    # 提督
    ADMIRAL = 'admiral'    # 总督

    @classmethod
    def from_api_level(cls, level: int) -> str:
        """从API返回的数字等级转换为内部标识"""
        mapping = {
            3: cls.GUARD,
            2: cls.CAPTAIN,
            1: cls.ADMIRAL
        }
        return mapping.get(level, cls.GUARD)

    @classmethod
    def get_name(cls, level: str) -> str:
        """获取角色中文名称"""
        names = {
            cls.GUARD: '舰长',
            cls.CAPTAIN: '提督',
            cls.ADMIRAL: '总督'
        }
        return names.get(level, '舰长')

    @classmethod
    def get_all(cls) -> list:
        """获取所有角色类型"""
        return [cls.GUARD, cls.CAPTAIN, cls.ADMIRAL]


class UserRole(str, Enum):
    """用户角色"""
    ADMIN = 'admin'
    GUARD = 'guard'
    CAPTAIN = 'captain'
    ADMIRAL = 'admiral'


class AuthStatus(str, Enum):
    """鉴权状态"""
    PENDING = 'pending'
    SUCCESS = 'success'
    EXPIRED = 'expired'


# API 相关常量
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# 分页默认值
DEFAULT_PAGE_SIZE = 30
MAX_PAGE_SIZE = 100

# 时间相关常量
AUTH_CODE_LENGTH = 8
AUTH_SESSION_EXPIRE_MINUTES = 5
CSRF_TOKEN_EXPIRE_SECONDS = 1800  # 30分钟

# 速率限制默认值
RATE_LIMIT_LOGIN_MAX = 5
RATE_LIMIT_LOGIN_WINDOW = 60
RATE_LIMIT_API_MAX = 30
RATE_LIMIT_API_WINDOW = 60

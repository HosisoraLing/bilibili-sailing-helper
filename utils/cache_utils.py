"""
缓存工具模块
提供简单的内存缓存机制，用于优化频繁的数据库查询
"""
import time
import threading
import logging
from functools import wraps
from typing import Optional, Any, Callable

logger = logging.getLogger(__name__)


class SimpleCache:
    """
    简单的线程安全内存缓存
    支持 TTL (Time To Live) 自动过期
    """

    def __init__(self, default_ttl: int = 300):
        """
        初始化缓存

        Args:
            default_ttl: 默认过期时间（秒），默认5分钟
        """
        self._cache = {}
        self._lock = threading.RLock()
        self._default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存值

        Args:
            key: 缓存键

        Returns:
            缓存值，如果不存在或已过期则返回 None
        """
        with self._lock:
            if key not in self._cache:
                return None

            expire_time, value = self._cache[key]
            if time.time() > expire_time:
                # 已过期，删除并返回 None
                del self._cache[key]
                return None

            return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """
        设置缓存值

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒），默认使用初始化时的 default_ttl
        """
        with self._lock:
            expire_time = time.time() + (ttl if ttl is not None else self._default_ttl)
            self._cache[key] = (expire_time, value)

    def delete(self, key: str):
        """
        删除缓存项

        Args:
            key: 缓存键
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]

    def clear(self):
        """清空所有缓存"""
        with self._lock:
            self._cache.clear()

    def clear_pattern(self, pattern: str):
        """
        删除匹配模式的缓存项

        Args:
            pattern: 键的匹配模式（简单子串匹配）
        """
        with self._lock:
            keys_to_delete = [k for k in self._cache if pattern in k]
            for key in keys_to_delete:
                del self._cache[key]

    def get_or_set(self, key: str, getter: Callable[[], Any], ttl: Optional[int] = None) -> Any:
        """
        获取缓存值，如果不存在则调用 getter 获取并缓存

        Args:
            key: 缓存键
            getter: 获取值的回调函数
            ttl: 过期时间（秒）

        Returns:
            缓存值
        """
        value = self.get(key)
        if value is not None:
            return value

        try:
            value = getter()
            if value is not None:
                self.set(key, value, ttl)
            return value
        except Exception as e:
            logger.error(f"缓存 getter 执行失败 [{key}]: {e}")
            raise


def cached(cache_instance: SimpleCache, key_prefix: str, ttl: Optional[int] = None):
    """
    装饰器：缓存函数返回值

    Args:
        cache_instance: 缓存实例
        key_prefix: 缓存键前缀
        ttl: 过期时间（秒）
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 构建缓存键（基于函数名和参数）
            key_parts = [key_prefix]
            key_parts.extend(str(arg) for arg in args[1:] if arg is not None)  # 跳过 self
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()) if v is not None)
            cache_key = ":".join(key_parts)

            # 尝试从缓存获取
            result = cache_instance.get(cache_key)
            if result is not None:
                return result

            # 执行函数并缓存结果
            result = func(*args, **kwargs)
            if result is not None:
                cache_instance.set(cache_key, result, ttl)

            return result

        # 添加清除缓存的方法
        wrapper.cache_clear = lambda *args, **kwargs: cache_instance.delete(
            ":".join([key_prefix] + [str(arg) for arg in args if arg is not None])
        )

        return wrapper
    return decorator


def invalidate_cache(cache_instance: SimpleCache, key_pattern: str):
    """
    清除匹配模式的缓存

    Args:
        cache_instance: 缓存实例
        key_pattern: 缓存键模式
    """
    cache_instance.clear_pattern(key_pattern)


# =========================
# 全局缓存实例
# =========================

# 用户查询缓存 (5分钟 TTL)
user_cache = SimpleCache(default_ttl=300)

# 舰长查询缓存 (5分钟 TTL)
guard_cache = SimpleCache(default_ttl=300)

# 地址查询缓存 (2分钟 TTL)
address_cache = SimpleCache(default_ttl=120)

# API 响应缓存 (1分钟 TTL，用于B站API响应)
api_response_cache = SimpleCache(default_ttl=60)


def clear_all_caches():
    """清空所有缓存"""
    user_cache.clear()
    guard_cache.clear()
    address_cache.clear()
    api_response_cache.clear()
    logger.info("所有缓存已清空")

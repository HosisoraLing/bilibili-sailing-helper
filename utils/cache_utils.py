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


# =========================
# 全局缓存实例
# =========================

# API 响应缓存 (1分钟 TTL，用于B站API响应)
api_response_cache = SimpleCache(default_ttl=60)


def clear_all_caches():
    """清空所有缓存"""
    api_response_cache.clear()
    logger.info("所有缓存已清空")

"""
日志工具模块
ERROR及以上级别的日志会自动写入本地文件
"""
import os
import logging
from logging.handlers import RotatingFileHandler
from config import BASE_DIR

LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

ERROR_LOG_FILE = os.path.join(LOG_DIR, 'error.log')

LOG_FORMAT = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

_initialized = False


def setup_logging():
    """初始化全局日志配置"""
    global _initialized
    if _initialized:
        return

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 检查是否已有控制台处理器
    has_console = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        for h in root_logger.handlers
    )

    if not has_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        root_logger.addHandler(console_handler)

    # 检查是否已有文件处理器
    has_file = any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers)

    if not has_file:
        file_handler = RotatingFileHandler(
            ERROR_LOG_FILE,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.ERROR)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        root_logger.addHandler(file_handler)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """获取指定名称的logger"""
    setup_logging()
    return logging.getLogger(name)

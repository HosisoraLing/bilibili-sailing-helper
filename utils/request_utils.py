"""
请求工具函数
处理请求相关的通用功能
"""
from flask import request


def get_uid_from_request() -> str | None:
    """
    从请求中获取 UID
    支持从 query parameter 或 form data 中获取
    """
    uid = request.args.get('uid') or request.form.get('uid')
    return str(uid) if uid else None


def is_json_request() -> bool:
    """检查是否为 JSON 请求"""
    return request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest'

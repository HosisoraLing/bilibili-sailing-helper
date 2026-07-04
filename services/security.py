"""
安全模块 - 提供加密、签名、CSRF防护等功能
"""
import hashlib
import hmac
import secrets
import time
import json
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
from flask import session, request, current_app


class SecurityManager:
    """安全管理器"""

    @staticmethod
    def generate_nonce() -> str:
        """生成随机数（Nonce）"""
        return secrets.token_hex(16)

    @staticmethod
    def generate_timestamp() -> int:
        """生成时间戳"""
        return int(time.time())

    @staticmethod
    def hash_data(data: str, salt: str = None) -> str:
        """哈希数据（带盐）"""
        if salt is None:
            salt = secrets.token_hex(8)
        hashed = hashlib.sha256(f"{salt}{data}".encode()).hexdigest()
        return f"{salt}:{hashed}"

    @staticmethod
    def verify_hash(data: str, hashed: str) -> bool:
        """验证哈希"""
        try:
            salt, hash_value = hashed.split(":", 1)
            new_hash = hashlib.sha256(f"{salt}{data}".encode()).hexdigest()
            return hmac.compare_digest(new_hash, hash_value)
        except:
            return False

    @staticmethod
    def encrypt_token(data: str, secret_key: str) -> str:
        """使用HMAC加密数据"""
        timestamp = int(time.time())
        nonce = secrets.token_hex(8)

        payload = {
            'data': data,
            'timestamp': timestamp,
            'nonce': nonce
        }

        # 生成签名
        message = f"{data}:{timestamp}:{nonce}"
        signature = hmac.new(
            secret_key.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

        payload['signature'] = signature

        # 返回Base64编码的JSON
        import base64
        json_str = json.dumps(payload, separators=(',', ':'))
        return base64.urlsafe_b64encode(json_str.encode()).decode()

    @staticmethod
    def decrypt_token(token: str, secret_key: str, max_age: int = 300) -> Optional[str]:
        """验证并解密Token"""
        try:
            import base64
            json_str = base64.urlsafe_b64decode(token.encode()).decode()
            payload = json.loads(json_str)

            data = payload['data']
            timestamp = payload['timestamp']
            nonce = payload['nonce']
            signature = payload['signature']

            # 验证时间戳（防止重放攻击）
            current_time = int(time.time())
            if current_time - timestamp > max_age:
                return None  # Token已过期

            # 验证签名
            message = f"{data}:{timestamp}:{nonce}"
            expected_signature = hmac.new(
                secret_key.encode(),
                message.encode(),
                hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(signature, expected_signature):
                return None  # 签名验证失败

            return data

        except Exception:
            return None

    @staticmethod
    def generate_csrf_token() -> str:
        """生成CSRF Token"""
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_hex(32)
            session['csrf_token_created'] = int(time.time())
        return session['csrf_token']

    @staticmethod
    def verify_csrf_token(token: str) -> bool:
        """验证CSRF Token"""
        if 'csrf_token' not in session:
            return False

        # 检查Token是否过期（24小时）
        created = session.get('csrf_token_created', 0)
        if int(time.time()) - created > 86400:
            session.pop('csrf_token', None)
            session.pop('csrf_token_created', None)
            return False

        return hmac.compare_digest(token, session['csrf_token'])


class RequestValidator:
    """请求验证器"""

    @staticmethod
    def validate_request(
        required_params: list,
        max_age: int = 300
    ) -> Tuple[bool, Optional[str]]:
        """
        验证请求参数和签名

        Args:
            required_params: 必需的参数列表
            max_age: 请求最大有效期（秒）

        Returns:
            (是否有效, 错误信息)
        """
        # 检查必需参数
        for param in required_params:
            if not request.values.get(param):
                return False, f"缺少参数: {param}"

        # 验证时间戳
        timestamp_str = request.values.get('timestamp')
        if not timestamp_str:
            return False, "缺少时间戳"

        try:
            timestamp = int(timestamp_str)
            current_time = int(time.time())
            if current_time - timestamp > max_age:
                return False, "请求已过期"
            if timestamp > current_time + 60:
                return False, "时间戳异常"
        except ValueError:
            return False, "时间戳格式错误"

        # 验证签名
        signature = request.values.get('signature')
        if not signature:
            return False, "缺少签名"

        # 构建签名字符串
        params = {k: v for k, v in request.values.items() if k not in ['signature']}
        sorted_params = sorted(params.items())
        param_str = '&'.join([f"{k}={v}" for k, v in sorted_params])

        expected_signature = hmac.new(
            current_app.config['SECRET_KEY'].encode(),
            param_str.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected_signature):
            return False, "签名验证失败"

        return True, None

    @staticmethod
    def validate_sensitive_request() -> Tuple[bool, Optional[str]]:
        """
        验证敏感操作请求（需要额外的Token验证）
        """
        # 检查用户是否登录
        from flask_login import current_user
        if not current_user.is_authenticated:
            return False, "未登录"

        # 验证敏感操作Token
        token = request.values.get('secure_token') or request.headers.get('X-Secure-Token')
        if not token:
            return False, "缺少安全Token"

        secret_key = current_app.config.get('SECURE_TOKEN_SECRET', current_app.config['SECRET_KEY'])
        data = SecurityManager.decrypt_token(token, secret_key, max_age=60)

        if not data:
            return False, "安全Token无效或已过期"

        # 验证Token中的用户ID是否匹配
        try:
            token_data = json.loads(data)
            if str(token_data.get('uid')) != str(current_user.uid):
                return False, "Token用户不匹配"
        except:
            return False, "Token格式错误"

        return True, None


class PasswordValidator:
    """密码验证器"""

    @staticmethod
    def validate_password_strength(password: str) -> Tuple[bool, str]:
        """验证密码强度"""
        if len(password) < 8:
            return False, "密码长度至少8位"

        if len(password) > 128:
            return False, "密码长度不能超过128位"

        import re

        if not re.search(r'[A-Z]', password):
            return False, "密码必须包含大写字母"

        if not re.search(r'[a-z]', password):
            return False, "密码必须包含小写字母"

        if not re.search(r'\d', password):
            return False, "密码必须包含数字"

        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            return False, "密码必须包含特殊字符"

        # 检查常见弱密码
        weak_patterns = [
            '123456', 'password', 'qwerty', 'abc123', 'admin',
            current_app.config.get('ANCHOR_NICKNAME', ''), 'bilibili'
        ]

        password_lower = password.lower()
        for pattern in weak_patterns:
            if pattern and pattern.lower() in password_lower:
                return False, f"密码不能包含常见词汇: {pattern}"

        return True, "密码强度符合要求"

    @staticmethod
    def validate_phone(phone: str) -> Tuple[bool, str]:
        """验证手机号"""
        import re
        pattern = r'^1[3-9]\d{9}$'
        if not re.match(pattern, phone):
            return False, "请输入有效的11位手机号码"
        return True, "手机号格式正确"

    @staticmethod
    def validate_uid(uid: str) -> Tuple[bool, str]:
        """验证UID"""
        import re
        pattern = r'^\d+$'
        if not re.match(pattern, uid):
            return False, "UID必须是纯数字"
        if len(uid) < 1 or len(uid) > 20:
            return False, "UID长度不正确"
        return True, "UID格式正确"


class RateLimiter:
    """简易速率限制器（基于Session）"""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    def is_allowed(self, key: str) -> Tuple[bool, int]:
        """
        检查请求是否被允许

        Returns:
            (是否允许, 剩余等待秒数)
        """
        now = int(time.time())
        session_key = f"rate_limit_{key}"

        if session_key not in session:
            session[session_key] = {
                'count': 1,
                'first_request': now,
                'last_request': now
            }
            return True, 0

        data = session[session_key]

        # 检查是否在时间窗口内
        if now - data['first_request'] > self.window_seconds:
            # 重置计数器
            session[session_key] = {
                'count': 1,
                'first_request': now,
                'last_request': now
            }
            return True, 0

        # 检查是否超过限制
        if data['count'] >= self.max_requests:
            # 计算剩余等待时间
            wait_time = self.window_seconds - (now - data['first_request'])
            return False, wait_time

        # 增加计数
        data['count'] += 1
        data['last_request'] = now
        session[session_key] = data

        return True, 0

    def reset(self, key: str):
        """重置指定key的限制"""
        session_key = f"rate_limit_{key}"
        session.pop(session_key, None)


# 全局速率限制器实例
login_limiter = RateLimiter(max_requests=5, window_seconds=60)  # 登录：5次/分钟
auth_limiter = RateLimiter(max_requests=60, window_seconds=60)   # 鉴权轮询：60次/分钟
api_limiter = RateLimiter(max_requests=30, window_seconds=60)    # API：30次/分钟
nickname_limiter = RateLimiter(max_requests=5, window_seconds=60)  # 昵称修改：5次/分钟

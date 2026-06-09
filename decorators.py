"""
装饰器模块
包含所有可复用的 Flask 装饰器
"""
from functools import wraps
from flask import request, redirect, url_for, render_template, flash, jsonify
from flask_login import current_user

from services.user_service import UserService
from services.security import SecurityManager, RequestValidator
from utils.request_utils import get_uid_from_request, is_json_request


def require_login(f):
    """
    装饰器：要求用户必须登录
    未登录用户重定向到登录页或首页
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            if is_json_request():
                return jsonify({'error': '登录已过期，请重新登录'}), 401
            flash('登录已过期，请重新登录', 'error')
            uid = get_uid_from_request()
            if uid:
                return redirect(url_for('main.login', uid=uid))
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function


def require_guard_or_admin(f):
    """
    装饰器：要求用户必须是陪伴榜用户或管理员
    非陪伴榜用户显示403错误页面
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('main.index'))

        uid = str(current_user.uid)
        is_valid, error_msg = UserService.validate_user_access(uid)
        if not is_valid:
            return render_template('not_guard.html', uid=uid), 403

        return f(*args, **kwargs)
    return decorated_function


def require_admin(f):
    """
    装饰器：要求用户必须是管理员
    非管理员显示403错误（HTML页面或JSON响应）
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            if is_json_request():
                return jsonify({'error': '登录已过期，请重新登录'}), 401
            flash('登录已过期，请重新登录', 'error')
            return redirect(url_for('main.index'))

        if not current_user.is_admin():
            uid = str(current_user.uid)
            if is_json_request():
                return jsonify({'error': 'Unauthorized'}), 403
            return render_template('not_admin.html', uid=uid), 403

        return f(*args, **kwargs)
    return decorated_function


def validate_csrf(f):
    """
    装饰器：验证 CSRF Token
    仅对 POST 请求生效
    若 session 已过期导致 CSRF 失败，提示用户重新登录
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == 'POST':
            csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
            if not csrf_token or not SecurityManager.verify_csrf_token(csrf_token):
                # 检查是否因为 session 过期导致 CSRF 失败
                if not current_user.is_authenticated:
                    if is_json_request():
                        return jsonify({'error': '登录已过期，请重新登录', 'redirect': '/'}), 401
                    flash('登录已过期，请重新登录', 'error')
                    uid = request.form.get('uid') or request.args.get('uid')
                    if uid:
                        return redirect(url_for('main.login', uid=uid))
                    return redirect(url_for('main.index'))
                if is_json_request():
                    return jsonify({'error': 'CSRF token invalid or missing'}), 403
                flash('安全验证失败，请刷新页面重试', 'error')
                return redirect(request.referrer or url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function


def validate_sensitive_request(f):
    """
    装饰器：验证敏感操作请求
    验证 CSRF Token 和敏感操作 Token
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 验证CSRF Token（POST请求）
        if request.method == 'POST':
            csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
            if not csrf_token or not SecurityManager.verify_csrf_token(csrf_token):
                if not current_user.is_authenticated:
                    if is_json_request():
                        return jsonify({'error': '登录已过期，请重新登录', 'redirect': '/'}), 401
                    flash('登录已过期，请重新登录', 'error')
                    uid = request.form.get('uid') or request.args.get('uid')
                    if uid:
                        return redirect(url_for('main.login', uid=uid))
                    return redirect(url_for('main.index'))
                if is_json_request():
                    return jsonify({'error': 'CSRF token invalid or missing'}), 403
                flash('安全验证失败，请刷新页面重试', 'error')
                return redirect(request.referrer or url_for('main.index'))

        # 验证敏感操作Token（针对高敏感操作）
        secure_token = request.form.get('secure_token') or request.headers.get('X-Secure-Token')
        if secure_token:
            is_valid, error_msg = RequestValidator.validate_sensitive_request()
            if not is_valid:
                if is_json_request():
                    return jsonify({'error': error_msg}), 403
                flash(error_msg, 'error')
                return redirect(request.referrer or url_for('main.index'))

        return f(*args, **kwargs)
    return decorated_function


def rate_limited(action: str, limiter=None):
    """
    装饰器工厂：速率限制

    Args:
        action: 操作标识，用于区分不同操作的速率限制
        limiter: 可选的自定义限流器，默认使用 auth_limiter
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            from services.security import auth_limiter

            uid = get_uid_from_request() or str(current_user.uid) if current_user.is_authenticated else None
            if uid:
                _limiter = limiter or auth_limiter
                is_allowed, wait_time = _limiter.is_allowed(f"{action}_{uid}")
                if not is_allowed:
                    if is_json_request():
                        return jsonify({'error': f'请求过于频繁，请 {wait_time} 秒后重试'}), 429
                    flash(f'请求过于频繁，请 {wait_time} 秒后重试', 'error')
                    return redirect(request.referrer or url_for('main.index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def handle_errors(fallback_url='main.index'):
    """
    装饰器工厂：统一错误处理
    捕获异常并返回友好的错误页面或JSON响应
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"请求处理出错: {e}", exc_info=True)

                if is_json_request():
                    return jsonify({'error': '服务器内部错误'}), 500
                flash('服务器内部错误，请稍后重试', 'error')
                return redirect(url_for(fallback_url))
        return decorated_function
    return decorator

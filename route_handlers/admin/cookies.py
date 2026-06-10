from route_handlers.common import *

@admin_bp.route('/cookie/status')
@require_admin
def admin_cookie_status():
    """获取Cookie和弹幕监听状态"""
    from services.cookie_service import CookieService
    from services.danmaku_listener import get_listener_status
    
    settings = CookieService.load_settings()
    bilibili = settings.get('bilibili', {})
    
    has_sessdata = bool(bilibili.get('SESSDATA'))
    has_buvid3 = bool(bilibili.get('buvid3'))
    
    # 验证SESSDATA是否有效（只在有SESSDATA时验证）
    is_valid = False
    username = None
    if has_sessdata:
        try:
            is_valid, result = CookieService.validate_cookie(bilibili['SESSDATA'])
            if is_valid:
                username = result
        except Exception as e:
            logger.warning(f"验证Cookie失败: {e}")
    
    # 获取弹幕监听状态
    listener_status = get_listener_status()
    
    return jsonify({
        'has_sessdata': has_sessdata,
        'has_buvid3': has_buvid3,
        'is_valid': is_valid,
        'username': username,
        'tv_auth': tv_auth_status_payload(),
        'listener': listener_status,
        'runtime': runtime_health_summary(),
    })


@admin_bp.route('/cookie/refresh-buvid3', methods=['POST'])
@require_admin
def admin_refresh_buvid3():
    """刷新buvid3"""
    from services.cookie_service import CookieService
    
    csrf_token = request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid'}), 403
    
    success = CookieService.auto_update_buvid3()
    
    if success:
        return jsonify({'success': True, 'message': 'buvid3 已存在'})
    else:
        return jsonify({'error': '当前 Cookie 缺少 buvid3，请重新扫码登录获取完整 Cookie'}), 500


@admin_bp.route('/cookie/qrcode/<task_id>')
@require_admin
def admin_cookie_qrcode(task_id):
    """生成登录二维码图片"""
    from flask import send_file
    from io import BytesIO

    task = get_qr_login_task(task_id)
    if not task or not task.qr_url:
        return jsonify({'error': '二维码任务不存在'}), 404
    if task.status in {'expired', 'failed'}:
        return jsonify({'error': '二维码已失效，请重新启动扫码登录'}), 410

    return send_file(
        BytesIO(render_qr_png(task.qr_url)),
        mimetype='image/png',
        max_age=0,
    )


@admin_bp.route('/cookie/start-qr-login', methods=['POST'])
@require_admin
def admin_start_qr_login():
    """启动扫码登录"""
    csrf_token = request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid'}), 403

    try:
        result = start_qr_login()
    except Exception as e:
        logger.error(f"启动扫码登录失败: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 502

    return jsonify({'success': True, **result})


@admin_bp.route('/cookie/qr-login/<task_id>', methods=['GET'])
@require_admin
def admin_poll_qr_login(task_id):
    """轮询扫码登录状态"""
    try:
        result = poll_qr_login(task_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error(f"轮询扫码登录失败: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 502

    if result.get('status') == 'succeeded':
        try:
            from services.danmaku_listener import restart_listener
            restart_listener()
        except Exception as e:
            logger.warning(f"Cookie 已更新，但弹幕监听重启失败: {e}")
            result['restart_warning'] = 'Cookie 已更新，但弹幕监听重启失败，请手动重启监听'

    success_states = {'pending', 'scanned', 'succeeded'}
    return jsonify({'success': result.get('status') in success_states, **result})


@admin_bp.route('/cookie/start-tv-qr-login', methods=['POST'])
@require_admin
def admin_start_tv_qr_login():
    """启动 TV 授权扫码登录"""
    csrf_token = request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid'}), 403

    try:
        result = start_tv_qr_login()
    except Exception as e:
        logger.error(f"启动 TV 授权扫码失败: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 502

    return jsonify({'success': True, **result})


@admin_bp.route('/cookie/tv-qr-login/<task_id>', methods=['GET'])
@require_admin
def admin_poll_tv_qr_login(task_id):
    """轮询 TV 授权扫码登录状态"""
    try:
        result = poll_tv_qr_login(task_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error(f"轮询 TV 授权扫码失败: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 502

    if result.get('status') == 'succeeded':
        try:
            from services.danmaku_listener import restart_listener
            restart_listener()
        except Exception as e:
            logger.warning(f"Cookie 已更新，但弹幕监听重启失败: {e}")
            result['restart_warning'] = 'Cookie 已更新，但弹幕监听重启失败，请手动重启监听'

    success_states = {'pending', 'scanned', 'succeeded'}
    return jsonify({'success': result.get('status') in success_states, **result})


@admin_bp.route('/cookie/restart-listener', methods=['POST'])
@require_admin
def admin_restart_listener():
    """重启弹幕监听"""
    from services.danmaku_listener import restart_listener
    
    csrf_token = request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid'}), 403
    
    success = restart_listener()
    
    if success:
        return jsonify({'success': True, 'message': '弹幕监听已重启'})
    else:
        return jsonify({'error': '重启失败'}), 500


# =========================
# 内部 API 路由
# =========================

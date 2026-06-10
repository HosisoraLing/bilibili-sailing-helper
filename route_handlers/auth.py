from route_handlers.common import *

@main_bp.route('/auth/status')
def auth_status():
    uid = get_uid_from_request()
    if not uid:
        return jsonify(status='error'), 400

    # 速率限制检查
    is_allowed, wait_time = auth_limiter.is_allowed(f"status_{uid}")
    if not is_allowed:
        return jsonify(status='rate_limited', wait=wait_time), 429

    session = get_active_auth_session(uid)
    if not session or session.is_expired():
        return jsonify(status='expired'), 410

    if session.status != 'success':
        runtime_state = pending_auth_runtime_state()
        http_status = runtime_state.pop('http_status', 200)
        return jsonify(**runtime_state), http_status

    # 检查各种模式参数
    login_mode = request.args.get('login_mode') == 'true'
    reset_mode = request.args.get('reset_mode') == 'true'

    # 根据模式返回不同的跳转地址
    if reset_mode:
        # 密码重置模式：跳转到重置密码页面
        redirect_url = url_for('main.reset_password', uid=uid)
    elif login_mode:
        # 鉴权登录模式：跳转到首页
        redirect_url = url_for('main.index', uid=uid)
    else:
        # 注册模式：跳转到注册页面
        redirect_url = url_for('main.register', uid=uid)

    return jsonify(
        status='success',
        redirect=redirect_url
    )


# =========================
# 登录
# =========================

@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    uid = get_uid_from_request()
    if not uid:
        return redirect('/')

    # 如果用户已经登录，直接跳转到首页
    if current_user.is_authenticated:
        if str(current_user.uid) == uid:
            return redirect(url_for('main.index', uid=uid))
        else:
            # UID不匹配，提示用户
            flash('请先退出当前账号再登录', 'error')
            return redirect(url_for('main.logout'))

    # 速率限制检查（针对UID）
    is_allowed, wait_time = UserService.validate_login_rate_limit(uid)
    if not is_allowed:
        flash(f'登录尝试过多，请 {wait_time} 秒后重试', 'error')
        return render_template('login.html', uid=uid, nickname='用户')

    # 验证用户访问权限（是否是陪伴榜用户或管理员）
    is_valid, error_msg = UserService.validate_user_access(uid)
    if not is_valid:
        return render_template('not_guard.html', uid=uid), 403

    user = User.query.filter_by(uid=uid).first()

    # 所有用户（包括管理员）未设置密码 → 必须先鉴权获得有效session，然后才能注册密码
    if not user or not user.password_hash:
        return redirect(url_for('main.auth', uid=uid))

    # 检查是否是自动登录模式（鉴权登录流程）
    auto_login = request.args.get('auto_login') == 'true'

    if auto_login:
        # 自动登录模式：检查是否有有效的鉴权会话
        # 验证鉴权会话状态（WebSocket 鉴权已完成）
        is_valid, error_msg = UserService.check_auth_session(uid)
        if is_valid:
            # 鉴权成功，自动登录
            UserService.reset_login_rate_limit(uid)
            UserService.clear_session()
            login_user(user)
            flash('鉴权登录成功', 'success')
            return redirect(url_for('main.index', uid=uid))
        else:
            # 鉴权失败或过期，跳转到鉴权页面
            flash('鉴权已过期，请重新验证', 'error')
            return redirect(url_for('main.auth', uid=uid))

    if request.method == 'POST':
        # 验证CSRF Token
        csrf_token = request.form.get('csrf_token')
        if not csrf_token or not UserService.verify_csrf_token(csrf_token):
            flash('安全验证失败，请刷新页面重试', 'error')
            return render_template('login.html', uid=uid, nickname=user.nickname if user else '')

        password = request.form.get('password', '')

        if user.check_password(password):
            # 登录成功，重置速率限制
            UserService.reset_login_rate_limit(uid)

            # 重新生成session（防止会话固定攻击）
            UserService.clear_session()

            login_user(user)
            flash('登录成功', 'success')
            # 登录成功后重定向到首页，带上自己的UID参数
            return redirect(url_for('main.index', uid=uid))
        else:
            flash('密码错误', 'error')

    return render_template(
        'login.html',
        uid=uid,
        nickname=user.nickname if user else ''
    )


# =========================
# 鉴权登录
# =========================

@main_bp.route('/auth-login')
def auth_login():
    """鉴权登录入口 - 引导用户进行弹幕鉴权"""
    uid = get_uid_from_request()
    if not uid:
        return redirect('/')

    # 验证用户访问权限（是否是陪伴榜用户或管理员）
    is_valid, error_msg = UserService.validate_user_access(uid)
    if not is_valid:
        return render_template('not_guard.html', uid=uid), 403

    # 检查用户是否已有密码（复用 auth_service 的函数）
    from services.auth_service import can_auto_login
    if can_auto_login(uid):
        # 已有密码，允许鉴权登录
        return redirect(url_for('main.auth', uid=uid, login_mode='true'))
    else:
        # 没有密码，需要先注册
        flash('您还没有设置密码，请先完成注册', 'info')
        return redirect(url_for('main.auth', uid=uid))


# =========================
# 弹幕鉴权页（支持登录和注册两种模式）
# =========================

@main_bp.route('/auth')
def auth():
    from services.danmaku_listener import watch_uid

    uid = get_uid_from_request()
    if not uid:
        return redirect('/')

    # 检查是否是登录模式
    login_mode = request.args.get('login_mode') == 'true'

    session = get_active_auth_session(uid)
    code = get_cached_code(uid)

    if not session or not code or session.is_expired():
        session, code = create_auth_session(uid)
        watch_uid(uid)

    return render_template(
        'auth.html',
        uid=uid,
        code=code,
        expires_at=session.expires_at,
        login_mode=login_mode
    )


# =========================
# 登出
# =========================

@main_bp.route('/logout')
def logout():
    """
    退出登录
    清除所有 session 和 cookie，确保用户必须重新登录
    """
    # 清除 Flask-Login 的用户 session
    logout_user()

    # 清除 Flask session（包括 CSRF token 等）
    from flask import session
    session.clear()
    session.modified = True

    # 重定向到首页
    return redirect(url_for('main.index'))


# =========================
# 重置密码
# =========================

@main_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    uid = get_uid_from_request()
    if not uid:
        return redirect('/')

    # 验证用户访问权限（是否是陪伴榜用户或管理员）
    is_valid, error_msg = UserService.validate_user_access(uid)
    if not is_valid:
        return render_template('not_guard.html', uid=uid), 403

    user = User.query.filter_by(uid=uid).first()

    # 用户必须存在且已有密码才能重置
    if not user or not user.password_hash:
        flash('您还没有设置密码，请先注册账号', 'error')
        return redirect(url_for('main.register', uid=uid))

    if request.method == 'POST':
        # 验证CSRF Token
        csrf_token = request.form.get('csrf_token')
        if not csrf_token or not UserService.verify_csrf_token(csrf_token):
            flash('安全验证失败，请刷新页面重试', 'error')
            return render_template(
                'reset_password.html',
                uid=uid,
                nickname=user.nickname
            )

        # 检查是否有有效的鉴权session
        is_valid, error_msg = UserService.check_auth_session(uid)
        if not is_valid:
            flash(error_msg or '安全验证失败', 'error')
            return redirect(url_for('main.reset_password', uid=uid))

        # 设置新密码
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        # 验证密码强度
        is_valid, msg = UserService.validate_password_strength(new_password)
        if not is_valid:
            flash(msg, 'error')
            return render_template(
                'reset_password.html',
                uid=uid,
                nickname=user.nickname
            )

        if new_password != confirm_password:
            flash('两次输入的密码不一致', 'error')
        else:
            # 重置密码
            UserService.set_user_password(user, new_password)

            # 清除当前的鉴权session（避免重复使用）
            auth_session = get_active_auth_session(uid)
            if auth_session:
                auth_session.mark_expired()
                db.session.commit()

            # 清除所有 session 和 cookie，确保必须重新登录
            from flask import session
            session.clear()
            session.modified = True

            flash('密码重置成功！请使用新密码登录', 'success')
            return redirect(url_for('main.login', uid=uid))

    # GET请求：检查是否有有效的鉴权session
    is_valid, _ = UserService.check_auth_session(uid)
    if is_valid:
        # 鉴权成功，显示设置新密码表单
        return render_template(
            'reset_password.html',
            uid=uid,
            nickname=user.nickname
        )

    # 未鉴权或session过期，跳转到鉴权页面
    return redirect(url_for('main.auth', uid=uid, reset_mode='true'))


# =========================
# 注册 / 设置密码
# =========================

@main_bp.route('/register', methods=['GET', 'POST'])
def register():
    uid = get_uid_from_request()
    if not uid:
        return redirect('/')

    # 验证用户访问权限（是否是陪伴榜用户或管理员）
    is_valid, error_msg = UserService.validate_user_access(uid)
    if not is_valid:
        return render_template('not_guard.html', uid=uid), 403

    # 所有用户（包括管理员）都需要弹幕鉴权才能设置密码
    # 检查是否已通过鉴权获得有效session
    is_valid, error_msg = UserService.check_auth_session(uid)
    if not is_valid:
        # 未通过鉴权或session过期，需要重新鉴权
        return redirect(url_for('main.auth', uid=uid))

    is_admin = UserService.is_admin_uid(uid)
    user, _ = UserService.get_or_create_user(uid, is_admin)

    # 已设置密码 → 直接走后续流程
    if user.password_hash:
        login_user(user)
        return redirect(url_for('main.index', uid=uid))

    if request.method == 'POST':
        # 验证CSRF Token
        csrf_token = request.form.get('csrf_token')
        if not csrf_token or not UserService.verify_csrf_token(csrf_token):
            flash('安全验证失败，请刷新页面重试', 'error')
            return render_template(
                'register.html',
                uid=uid,
                nickname=user.nickname
            )

        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        # 验证密码强度
        is_valid, msg = UserService.validate_password_strength(password)
        if not is_valid:
            flash(msg, 'error')
            return render_template(
                'register.html',
                uid=uid,
                nickname=user.nickname
            )

        is_valid, msg = UserService.validate_passwords_match(password, confirm)
        if not is_valid:
            flash(msg, 'error')
        else:
            UserService.set_user_password(user, password)

            # 重新生成session（防止会话固定攻击）
            UserService.clear_session()

            login_user(user)
            flash('密码设置成功！已自动登录', 'success')
            return redirect(url_for('main.index', uid=uid, force_form=1))

    return render_template(
        'register.html',
        uid=uid,
        nickname=user.nickname
    )


# =========================
# 地址提交（必须登录）
# =========================

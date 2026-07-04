from route_handlers.common import *

@main_bp.route('/')
def index():
    uid = get_uid_from_request()

    # If user is logged in, use their UID and verify ownership
    if current_user.is_authenticated:
        # Verify the logged-in user matches any UID in the request
        if uid and str(current_user.uid) != uid:
            # Someone trying to access another user's page - redirect to their own page
            return redirect(url_for('main.index', uid=current_user.uid))

        # Use the logged-in user's UID
        uid = str(current_user.uid)

        # Get user from database
        user = User.query.filter_by(uid=uid).first()
        if not user:
            return redirect(url_for('main.logout'))

        # Get nickname - use guard nickname if available, otherwise use user nickname
        nickname = UserService.get_guard_nickname(uid)
        if not nickname:
            nickname = user.nickname

        # Get existing address for pre-filling the form
        existing_address = get_user_address(uid)
        return render_template('form.html', uid=uid, nickname=nickname, address=existing_address)

    # Not logged in - 检查是否提供了UID参数
    if not uid:
        # 没有提供UID，显示首页输入框
        return render_template('index.html')

    # 有UID参数但未登录 - 检查用户状态并重定向到相应页面
    # 检查是否是管理员（管理员可以不是陪伴榜用户）
    is_admin = UserService.is_admin_uid(uid)

    # 检查是否是陪伴榜用户
    is_companion = UserService.is_companion_user(uid)

    # 如果既不是管理员也不是陪伴榜用户
    if not is_admin and not is_companion:
        return render_template('not_guard.html', uid=uid), 403

    user = User.query.filter_by(uid=uid).first()

    # 所有用户（包括管理员）未设置密码 → 必须先鉴权获得有效session，然后才能注册密码
    if not user or not user.password_hash:
        return redirect(url_for('main.auth', uid=uid))

    # User exists with password but not logged in - require login
    return redirect(url_for('main.login', uid=uid))


# =========================
# 非舰长页面（WebSocket 重定向用）
# =========================

@main_bp.route('/not-guard')
def not_guard():
    """非舰长用户访问页面"""
    uid = get_uid_from_request()
    if not uid:
        return redirect(url_for('main.index'))

    return render_template('not_guard.html', uid=uid), 403


# =========================
# 开源项目说明
# =========================

@main_bp.route('/opensource')
def opensource():
    """开源项目使用说明页面"""
    return render_template('opensource.html')


# =========================
# 鉴权状态轮询
# =========================


@main_bp.route('/submit', methods=['POST'])
@require_guard_or_admin
def submit():
    uid = get_uid_from_request()
    if not uid:
        flash('参数错误', 'error')
        return redirect(url_for('main.index'))

    # Verify the submitted UID matches the logged-in user
    if str(current_user.uid) != uid:
        flash('非法提交：UID与登录账户不匹配', 'error')
        return redirect(url_for('main.index', uid=uid))

    # 验证CSRF Token
    csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        flash('页面已过期，已为您刷新，请重新提交', 'error')
        return redirect(url_for('main.index', uid=uid))

    # 速率限制检查
    is_allowed, wait_time = AdminService.check_admin_rate_limit(uid, "submit")
    if not is_allowed:
        flash(f'请求过于频繁，请 {wait_time} 秒后重试', 'error')
        return redirect(url_for('main.index', uid=uid))

    # 获取用户昵称（陪伴榜用户或管理员）
    nickname = UserService.get_guard_nickname(uid)
    if not nickname:
        # 如果不是舰长，检查是否是管理员（允许管理员填写自己的地址）
        if UserService.is_admin_uid(uid):
            user = User.query.filter_by(uid=uid).first()
            nickname = user.nickname if user else f"管理员_{uid}"
        else:
            flash('非法提交，您不在当前陪伴榜名单中', 'error')
            return redirect(url_for('main.index', uid=uid))

    # 验证表单数据
    phone = request.form.get('phone', '')
    if phone:
        is_valid, msg = UserService.validate_phone(phone)
        if not is_valid:
            flash(msg, 'error')
            return redirect(url_for('main.index', uid=uid))

    existing_address = get_user_address(uid)
    is_update = existing_address is not None

    save_address(uid, nickname, request.form)

    return render_template('success.html', uid=uid, submitted=is_update)


# =========================
# 管理员面板（必须管理员权限）
# =========================

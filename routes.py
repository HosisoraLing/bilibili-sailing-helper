"""
路由模块
包含所有 Flask 路由定义
"""
from datetime import date
from flask import (
    Blueprint, request, render_template, redirect,
    url_for, jsonify, flash, session
)
from flask_login import login_user, current_user, logout_user

from db.models import db, User, Address, Guard, GuardGiftRecord, get_beijing_now
from services.address_service import save_address, get_user_address
from services.auth_service import (
    create_auth_session,
    get_active_auth_session,
    get_cached_code,
)
from services.security import (
    RequestValidator,
    auth_limiter,
)
from services.user_service import UserService
from services.admin_service import AdminService
from services.guard_gift_service import GuardGiftService
from services.guard_service import GUARD_LEVEL_NAME_MAP
from utils.request_utils import get_uid_from_request
from utils.csv_utils import create_csv_response
from utils.cache_utils import (
    invalidate_cache,
    user_cache,
    guard_cache,
    address_cache,
)
from decorators import (
    require_login,
    require_guard_or_admin,
    require_admin,
)


# 创建蓝图
main_bp = Blueprint('main', __name__)
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


# 主路由
# =========================

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
# 鉴权状态轮询
# =========================

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
        return jsonify(status='pending')

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

        # 验证密码强度（防止弱密码）
        is_valid, msg = UserService.validate_password_strength(password)
        if not is_valid:
            flash(msg, 'error')
            return render_template('login.html', uid=uid, nickname=user.nickname if user else '')

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

@main_bp.route('/submit', methods=['POST'])
@require_guard_or_admin
def submit():
    uid = get_uid_from_request()
    if not uid:
        return jsonify({'error': '参数错误'}), 400

    # Verify the submitted UID matches the logged-in user
    if str(current_user.uid) != uid:
        return jsonify({'error': '非法提交：UID与登录账户不匹配'}), 403

    # 验证CSRF Token
    csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid or missing'}), 403

    # 速率限制检查
    is_allowed, wait_time = AdminService.check_admin_rate_limit(uid, "submit")
    if not is_allowed:
        return jsonify({'error': f'请求过于频繁，请 {wait_time} 秒后重试'}), 429

    # 获取用户昵称（陪伴榜用户或管理员）
    nickname = UserService.get_guard_nickname(uid)
    if not nickname:
        # 如果不是舰长，检查是否是管理员（允许管理员填写自己的地址）
        if UserService.is_admin_uid(uid):
            user = User.query.filter_by(uid=uid).first()
            nickname = user.nickname if user else f"管理员_{uid}"
        else:
            return jsonify({'error': '非法提交，您不在当前陪伴榜名单中'}), 403

    # 验证表单数据 - 允许手机号为空（留空）
    phone = request.form.get('phone', '')
    if phone:  # 如果填写了手机号才验证格式
        is_valid, msg = UserService.validate_phone(phone)
        if not is_valid:
            return jsonify({'error': msg}), 400

    save_address(uid, nickname, request.form)

    return render_template('success.html', uid=uid)


# =========================
# 管理员面板（必须管理员权限）
# =========================

@admin_bp.route('/panel')
@require_admin
def admin_panel():
    # 速率限制检查
    is_allowed, wait_time = AdminService.check_admin_rate_limit(current_user.uid, "admin_panel")
    if not is_allowed:
        flash(f'请求过于频繁，请 {wait_time} 秒后重试', 'error')
        return redirect(url_for('main.index'))

    # Load all addresses
    all_addresses = AdminService.get_all_addresses()

    return render_template(
        'admin_panel.html',
        uid=current_user.uid,
        nickname=current_user.nickname,
        addresses=all_addresses,
        total_count=len(all_addresses)
    )


# =========================
# 新增地址（必须管理员权限）
# =========================

@admin_bp.route('/add-address', methods=['GET', 'POST'])
@require_admin
def admin_add_address():

    if request.method == 'POST':
        # 验证CSRF Token
        csrf_token = request.form.get('csrf_token')
        if not csrf_token or not UserService.verify_csrf_token(csrf_token):
            flash('安全验证失败，请刷新页面重试', 'error')
            return render_template('add_address.html', admin_uid=current_user.uid)

        # 验证敏感操作Token（高敏感操作必须验证）
        is_valid, error_msg = RequestValidator.validate_sensitive_request()
        if not is_valid:
            flash(error_msg or '安全验证失败', 'error')
            return render_template('add_address.html', admin_uid=current_user.uid)

        uid = request.form.get('uid', '')
        name = request.form.get('name', '')
        phone = request.form.get('phone', '')

        # 验证数据格式
        is_valid, msg = AdminService.validate_address_data(uid, phone)
        if not is_valid:
            flash(msg, 'error')
            return render_template('add_address.html', admin_uid=current_user.uid)

        # 验证 UID 是否存在（舰长/陪伴榜用户或管理员）
        exists, guard = AdminService.check_guard_exists(uid)
        if not exists:
            flash('该 UID 不在舰长列表中，无法添加地址', 'error')
            return render_template('add_address.html', admin_uid=current_user.uid)

        # 检查该 UID 是否已有地址
        exists, _ = AdminService.check_address_exists(uid)
        if exists:
            flash(f'UID {uid} 已有地址记录，请使用编辑功能', 'error')
            return render_template('add_address.html', admin_uid=current_user.uid)

        # 创建新地址
        form_data = {
            'name': name,
            'phone': phone,
            'province': request.form.get('province', ''),
            'city': request.form.get('city', ''),
            'district': request.form.get('district', ''),
            'detail': request.form.get('detail', ''),
        }
        AdminService.create_address(uid, guard.nickname, form_data)

        flash(f'已成功为 {guard.nickname} ({uid}) 添加地址', 'success')
        return redirect(url_for('admin.admin_panel'))

    # GET request - show form
    return render_template('add_address.html', admin_uid=current_user.uid)


# =========================
# 编辑地址（必须管理员权限）
# =========================

@admin_bp.route('/edit-address/<int:address_id>', methods=['GET', 'POST'])
@require_admin
def admin_edit_address(address_id):

    address = AdminService.get_address_by_id(address_id)
    if not address:
        flash('地址不存在', 'error')
        return redirect(url_for('admin.admin_panel'))

    if request.method == 'POST':
        # 验证CSRF Token
        csrf_token = request.form.get('csrf_token')
        if not csrf_token or not UserService.verify_csrf_token(csrf_token):
            flash('安全验证失败，请刷新页面重试', 'error')
            return render_template(
                'edit_address.html',
                address=address,
                admin_uid=current_user.uid
            )

        # 验证敏感操作Token（高敏感操作必须验证）
        is_valid, error_msg = RequestValidator.validate_sensitive_request()
        if not is_valid:
            flash(error_msg or '安全验证失败', 'error')
            return render_template(
                'edit_address.html',
                address=address,
                admin_uid=current_user.uid
            )

        # 验证手机号格式
        phone = request.form.get('phone', '')
        is_valid, msg = UserService.validate_phone(phone)
        if not is_valid:
            flash(msg, 'error')
            return render_template(
                'edit_address.html',
                address=address,
                admin_uid=current_user.uid
            )

        # Update address
        form_data = {
            'name': request.form.get('name', ''),
            'phone': phone,
            'province': request.form.get('province', ''),
            'city': request.form.get('city', ''),
            'district': request.form.get('district', ''),
            'detail': request.form.get('detail', ''),
        }
        AdminService.update_address(address, form_data)

        flash('地址信息已更新', 'success')
        return redirect(url_for('admin.admin_panel'))

    # GET request - show edit form
    return render_template(
        'edit_address.html',
        address=address,
        admin_uid=current_user.uid
    )


# =========================
# 删除地址（必须管理员权限）
# =========================

@admin_bp.route('/delete-address/<int:address_id>', methods=['POST'])
@require_admin
def admin_delete_address(address_id):

    # 验证CSRF Token
    csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'success': False, 'error': 'CSRF token invalid or missing'}), 403

    # 验证敏感操作Token（高敏感操作必须验证）
    is_valid, error_msg = RequestValidator.validate_sensitive_request()
    if not is_valid:
        return jsonify({'success': False, 'error': error_msg or '安全验证失败'}), 403

    if AdminService.delete_address(address_id):
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': '地址不存在'}), 404


# =========================
# 导出地址 CSV（必须管理员权限）
# =========================

@admin_bp.route('/export/csv')
@require_admin
def admin_export_csv():

    # Get month parameter
    month = request.args.get('month')
    if not month:
        month = GuardGiftService.get_current_month()

    # Get filter type - 默认导出所有地址
    filter_type = request.args.get('filter', 'all')  # eligible, all

    # Load addresses based on filter
    if filter_type == 'eligible':
        # 只导出当月可领礼物的舰长的地址
        eligible_records = AdminService.get_eligible_guard_gift_records(month)
        eligible_uids = [record.uid for record in eligible_records]
        addresses = [addr for addr in AdminService.get_all_addresses() if addr.uid in eligible_uids]
    else:
        # 导出所有地址
        addresses = AdminService.get_all_addresses()

    # Generate CSV
    csv_content = AdminService.generate_addresses_csv(addresses)

    # Return CSV file
    return create_csv_response(csv_content, f'addresses_{month}')


# =========================
# 获取单个舰长详情（必须管理员权限）
# =========================

@admin_bp.route('/guards/<uid>', methods=['GET'])
@require_admin
def admin_guard_get(uid):

    # 验证CSRF Token
    csrf_token = request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid or missing'}), 403

    # Find guard
    guard = Guard.query.filter_by(uid=uid).first()
    if not guard:
        return jsonify({'error': 'Guard not found'}), 404

    return jsonify({
        'success': True,
        'guard': {
            'uid': guard.uid,
            'nickname': guard.nickname,
            'guard_level': guard.guard_level,
            'in_guard': guard.in_guard,
            'accompany_days': guard.accompany_days
        }
    })


# =========================
# 舰长列表（必须管理员权限）
# =========================

@admin_bp.route('/guards')
@require_admin
def admin_guards():

    # Get filter parameter from query string
    status_filter = request.args.get('status', 'all')

    # Load all guards from database
    guards = AdminService.get_all_guards()

    # Apply status filter if specified
    if status_filter == 'in_guard':
        guards = [g for g in guards if g.in_guard]
    elif status_filter == 'not_in_guard':
        guards = [g for g in guards if not g.in_guard]

    # Count by level
    counts = AdminService.count_guards_by_level(guards)

    # Count by status
    status_counts = AdminService.count_guards_by_status(guards)

    return render_template(
        'admin_guards.html',
        uid=current_user.uid,
        nickname=current_user.nickname,
        guards=guards,
        guard_count=counts['guard'],
        captain_count=counts['captain'],
        admiral_count=counts['admiral'],
        total_count=len(guards),
        status_filter=status_filter,
        in_guard_count=status_counts['in_guard'],
        not_in_guard_count=status_counts['not_in_guard']
    )


# =========================
# 编辑舰长（必须管理员权限）
# =========================

@admin_bp.route('/guards/edit', methods=['POST'])
@require_admin
def admin_guard_edit():

    # 验证CSRF Token
    csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid or missing'}), 403

    uid = request.form.get('uid')
    nickname = request.form.get('nickname')
    guard_level = request.form.get('guard_level')
    in_guard = request.form.get('in_guard')
    accompany_days = request.form.get('accompany_days')

    if not uid:
        return jsonify({'error': 'UID is required'}), 400

    # Find guard
    guard = Guard.query.filter_by(uid=uid).first()
    if not guard:
        return jsonify({'error': 'Guard not found'}), 404

    # Update fields if provided
    if nickname:
        guard.nickname = nickname
    if guard_level:
        guard.guard_level = guard_level
    if in_guard is not None:
        guard.in_guard = in_guard.lower() == 'true'
    if accompany_days is not None:
        try:
            guard.accompany_days = int(accompany_days)
        except (ValueError, TypeError):
            guard.accompany_days = 0

    guard.updated_at = get_beijing_now()
    db.session.commit()

    # 清除相关缓存
    guard_cache.clear_pattern(f"guard:{uid}")
    guard_cache.clear_pattern(f"guard_info:{uid}")
    if nickname:
        guard_cache.clear_pattern(f"guard_nickname:{uid}")

    return jsonify({'success': True, 'message': 'Guard updated'})


# =========================
# 删除舰长（必须管理员权限）
# =========================

@admin_bp.route('/guards/delete', methods=['POST'])
@require_admin
def admin_guard_delete():

    # 验证CSRF Token
    csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid or missing'}), 403

    uid = request.form.get('uid')

    if not uid:
        return jsonify({'error': 'UID is required'}), 400

    # Find guard
    guard = Guard.query.filter_by(uid=uid).first()
    if not guard:
        return jsonify({'error': 'Guard not found'}), 404

    # Delete guard
    db.session.delete(guard)
    db.session.commit()

    # 清除相关缓存
    guard_cache.clear_pattern(f"guard:{uid}")
    guard_cache.clear_pattern(f"guard_info:{uid}")
    guard_cache.clear_pattern(f"guard_nickname:{uid}")

    return jsonify({'success': True, 'message': 'Guard deleted'})


# =========================
# 新增舰长（必须管理员权限）
# =========================

@admin_bp.route('/guards/add', methods=['POST'])
@require_admin
def admin_guard_add():

    # 验证CSRF Token
    csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid or missing'}), 403

    uid = request.form.get('uid')
    nickname = request.form.get('nickname')
    guard_level = request.form.get('guard_level', 'guard')

    if not uid:
        return jsonify({'error': 'UID is required'}), 400

    if not nickname:
        return jsonify({'error': 'Nickname is required'}), 400

    # Check if guard already exists
    existing_guard = Guard.query.filter_by(uid=uid).first()
    if existing_guard:
        return jsonify({'error': 'Guard already exists'}), 400

    # Create new guard
    new_guard = Guard(
        uid=uid,
        nickname=nickname,
        guard_level=guard_level,
        in_guard=True,
        accompany_days=0,
        last_guard_date=date.today(),
        updated_at=get_beijing_now()
    )

    db.session.add(new_guard)
    db.session.commit()

    # 清除 API 缓存（因为舰长列表已变更）
    from utils.cache_utils import api_response_cache
    api_response_cache.clear_pattern(f"guards:")

    return jsonify({'success': True, 'message': 'Guard added'})


# =========================
# 导出舰长 CSV（必须管理员权限）
# =========================

@admin_bp.route('/export/guards')
@require_admin
def admin_export_guards():

    # Get filter parameter from query string
    status_filter = request.args.get('status', 'all')

    # Load all guards
    guards = AdminService.get_all_guards()

    # Apply status filter if specified
    if status_filter == 'in_guard':
        guards = [g for g in guards if g.in_guard]
    elif status_filter == 'not_in_guard':
        guards = [g for g in guards if not g.in_guard]

    # Generate CSV
    csv_content = AdminService.generate_guards_csv(guards)

    # Return CSV file
    return create_csv_response(csv_content, 'guards')


# =========================
# 舰长礼物列表（必须管理员权限）
# =========================

@admin_bp.route('/guard-gifts')
@require_admin
def admin_guard_gifts():

    # Get month parameter
    month = request.args.get('month')
    if not month:
        month = GuardGiftService.get_current_month()

    # Get filter type
    filter_type = request.args.get('filter', 'all')  # all, eligible, received

    # Load records based on filter
    if filter_type == 'eligible':
        records = AdminService.get_eligible_guard_gift_records(month)
    elif filter_type == 'received':
        records = AdminService.get_received_guard_gift_records(month)
    else:
        records = AdminService.get_all_guard_gift_records(month)

    # Get statistics
    stats = AdminService.count_guard_gift_records(month)

    # Get available months
    available_months = AdminService.get_available_months()

    return render_template(
        'admin_guard_gifts.html',
        uid=current_user.uid,
        nickname=current_user.nickname,
        records=records,
        month=month,
        filter_type=filter_type,
        stats=stats,
        available_months=available_months
    )


# =========================
# 导出舰长礼物 CSV（必须管理员权限）
# =========================

@admin_bp.route('/export/guard-gifts')
@require_admin
def admin_export_guard_gifts():

    # Get month parameter (None means export all months)
    month = request.args.get('month')
    
    # Get filter type
    filter_type = request.args.get('filter', 'all')  # all, eligible, received

    # Load records based on filter
    if filter_type == 'eligible':
        if month:
            records = AdminService.get_eligible_guard_gift_records(month)
        else:
            # 获取所有月份的未领取记录
            records = GuardGiftRecord.query.filter_by(received=False).order_by(
                GuardGiftRecord.month.desc(),
                GuardGiftRecord.guard_level.desc()
            ).all()
    elif filter_type == 'received':
        if month:
            records = AdminService.get_received_guard_gift_records(month)
        else:
            # 获取所有月份的已领取记录
            records = GuardGiftRecord.query.filter_by(received=True).order_by(
                GuardGiftRecord.month.desc(),
                GuardGiftRecord.guard_level.desc()
            ).all()
    else:
        records = AdminService.get_all_guard_gift_records(month)

    # Generate CSV
    csv_content = AdminService.generate_guard_gift_csv(records)

    # Return CSV file
    filename = f'guard_gifts_{month}' if month else 'guard_gifts_all'
    return create_csv_response(csv_content, filename)


# =========================
# 获取单个舰长礼物记录详情（必须管理员权限）
# =========================

@admin_bp.route('/guard-gifts/<uid>/<month>', methods=['GET'])
@require_admin
def admin_guard_gift_get(uid, month):

    # 验证CSRF Token
    csrf_token = request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid or missing'}), 403

    # Find guard gift record
    record = GuardGiftRecord.query.filter_by(uid=uid, month=month).first()
    if not record:
        return jsonify({'error': 'Record not found'}), 404

    return jsonify({
        'success': True,
        'record': {
            'uid': record.uid,
            'nickname': record.nickname,
            'guard_level': record.guard_level,
            'month': record.month,
            'accompany_days': record.accompany_days,
            'received': record.received
        }
    })


# =========================
# 编辑舰长礼物记录（必须管理员权限）
# =========================

@admin_bp.route('/guard-gifts/edit', methods=['POST'])
@require_admin
def admin_guard_gift_edit():

    # 验证CSRF Token
    csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid or missing'}), 403

    uid = request.form.get('uid')
    month = request.form.get('month')
    nickname = request.form.get('nickname')
    guard_level = request.form.get('guard_level')
    accompany_days = request.form.get('accompany_days')
    received = request.form.get('received')

    if not uid:
        return jsonify({'error': 'UID is required'}), 400

    # Find guard gift record
    record = GuardGiftRecord.query.filter_by(uid=uid, month=month).first()
    if not record:
        return jsonify({'error': 'Record not found'}), 404

    # Update fields if provided
    if nickname:
        record.nickname = nickname
    if guard_level:
        record.guard_level = guard_level
    if accompany_days is not None:
        try:
            record.accompany_days = int(accompany_days)
        except (ValueError, TypeError):
            record.accompany_days = 0
    if received is not None:
        record.received = received.lower() == 'true'
        if record.received:
            record.received_at = get_beijing_now()
        else:
            record.received_at = None

    record.updated_at = get_beijing_now()
    db.session.commit()

    return jsonify({'success': True, 'message': 'Record updated'})


# =========================
# 删除舰长礼物记录（必须管理员权限）
# =========================

@admin_bp.route('/guard-gifts/delete', methods=['POST'])
@require_admin
def admin_guard_gift_delete():

    # 验证CSRF Token
    csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid or missing'}), 403

    uid = request.form.get('uid')
    month = request.form.get('month')

    if not uid:
        return jsonify({'error': 'UID is required'}), 400

    # Find guard gift record
    record = GuardGiftRecord.query.filter_by(uid=uid, month=month).first()
    if not record:
        return jsonify({'error': 'Record not found'}), 404

    # Delete record
    db.session.delete(record)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Record deleted'})


# =========================
# 新增舰长礼物记录（必须管理员权限）
# =========================

@admin_bp.route('/guard-gifts/add', methods=['POST'])
@require_admin
def admin_guard_gift_add():

    # 验证CSRF Token
    csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid or missing'}), 403

    uid = request.form.get('uid')
    nickname = request.form.get('nickname')
    guard_level = request.form.get('guard_level', 'guard')
    month = request.form.get('month')
    accompany_days = request.form.get('accompany_days', '0')

    if not uid:
        return jsonify({'error': 'UID is required'}), 400

    if not nickname:
        return jsonify({'error': 'Nickname is required'}), 400

    if not month:
        return jsonify({'error': 'Month is required'}), 400

    # Check if record already exists
    existing_record = GuardGiftRecord.query.filter_by(uid=uid, month=month).first()
    if existing_record:
        return jsonify({'error': 'Record already exists for this month'}), 400

    # Create new guard gift record
    new_record = GuardGiftRecord(
        uid=uid,
        nickname=nickname,
        guard_level=guard_level,
        month=month,
        accompany_days=int(accompany_days) if accompany_days else 0,
        received=False,
        created_at=get_beijing_now(),
        updated_at=get_beijing_now()
    )

    db.session.add(new_record)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Record added'})


# =========================
# 标记舰长礼物已领取（必须管理员权限）
# =========================

@admin_bp.route('/guard-gifts/receive', methods=['POST'])
@require_admin
def admin_guard_gift_receive():

    # 验证CSRF Token
    csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid or missing'}), 403

    uid = request.form.get('uid')
    month = request.form.get('month')

    if not uid:
        return jsonify({'error': 'UID is required'}), 400

    # 标记已领取
    success = AdminService.mark_guard_gift_received(uid, month)

    if success:
        return jsonify({'success': True, 'message': '标记成功'})
    else:
        return jsonify({'error': '记录不存在'}), 404


# =========================
# 取消标记舰长礼物已领取（必须管理员权限）
# =========================

@admin_bp.route('/guard-gifts/unreceive', methods=['POST'])
@require_admin
def admin_guard_gift_unreceive():

    # 验证CSRF Token
    csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid or missing'}), 403

    uid = request.form.get('uid')
    month = request.form.get('month')

    if not uid:
        return jsonify({'error': 'UID is required'}), 400

    # Find guard gift record
    record = GuardGiftRecord.query.filter_by(uid=uid, month=month).first()
    if not record:
        return jsonify({'error': 'Record not found'}), 404

    # Unmark as received
    record.received = False
    record.received_at = None
    record.updated_at = get_beijing_now()
    db.session.commit()

    return jsonify({'success': True, 'message': '取消标记成功'})


# =========================
# 手动统计舰长礼物（必须管理员权限）
# =========================

@admin_bp.route('/calculate-gifts', methods=['POST'])
@require_admin
def admin_calculate_gifts():

    # 验证CSRF Token
    csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid or missing'}), 403

    try:
        # 手动执行舰长礼物统计
        eligible_records = GuardGiftService.calculate_monthly_eligible_guards()
        count = len(eligible_records)
        
        # 同时更新历史月份
        historical_records = GuardGiftService.update_historical_months()
        historical_count = len(historical_records)
        
        return jsonify({
            'success': True, 
            'count': count,
            'historical_count': historical_count
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =========================
# 获取单个陪伴榜成员详情（必须管理员权限）
# =========================

@admin_bp.route('/companion/<uid>', methods=['GET'])
@require_admin
def admin_companion_get(uid):

    # 验证CSRF Token
    csrf_token = request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid or missing'}), 403

    # Find guard
    guard = Guard.query.filter_by(uid=uid).first()
    if not guard:
        return jsonify({'error': 'Guard not found'}), 404

    return jsonify({
        'success': True,
        'guard': {
            'uid': guard.uid,
            'nickname': guard.nickname,
            'guard_level': guard.guard_level,
            'in_guard': guard.in_guard,
            'accompany_days': guard.accompany_days
        }
    })


# =========================
# 编辑陪伴榜成员（必须管理员权限）
# =========================

@admin_bp.route('/companion/edit', methods=['POST'])
@require_admin
def admin_companion_edit():

    # 验证CSRF Token
    csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid or missing'}), 403

    uid = request.form.get('uid')
    nickname = request.form.get('nickname')
    guard_level = request.form.get('guard_level')
    in_guard = request.form.get('in_guard')
    accompany_days = request.form.get('accompany_days')

    if not uid:
        return jsonify({'error': 'UID is required'}), 400

    # Find guard
    guard = Guard.query.filter_by(uid=uid).first()
    if not guard:
        return jsonify({'error': 'Guard not found'}), 404

    # Update fields if provided
    if nickname:
        guard.nickname = nickname
    if guard_level:
        guard.guard_level = guard_level
    if in_guard is not None:
        guard.in_guard = in_guard.lower() == 'true'
    if accompany_days is not None:
        try:
            guard.accompany_days = int(accompany_days)
        except (ValueError, TypeError):
            guard.accompany_days = 0

    guard.updated_at = get_beijing_now()
    db.session.commit()

    # 清除相关缓存
    guard_cache.clear_pattern(f"guard:{uid}")
    guard_cache.clear_pattern(f"guard_info:{uid}")
    if nickname:
        guard_cache.clear_pattern(f"guard_nickname:{uid}")

    return jsonify({'success': True, 'message': 'Guard updated'})


# =========================
# 删除陪伴榜成员（必须管理员权限）
# =========================

@admin_bp.route('/companion/delete', methods=['POST'])
@require_admin
def admin_companion_delete():

    # 验证CSRF Token
    csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid or missing'}), 403

    uid = request.form.get('uid')

    if not uid:
        return jsonify({'error': 'UID is required'}), 400

    # Find guard
    guard = Guard.query.filter_by(uid=uid).first()
    if not guard:
        return jsonify({'error': 'Guard not found'}), 404

    # Delete guard
    db.session.delete(guard)
    db.session.commit()

    # 清除相关缓存
    guard_cache.clear_pattern(f"guard:{uid}")
    guard_cache.clear_pattern(f"guard_info:{uid}")
    guard_cache.clear_pattern(f"guard_nickname:{uid}")

    return jsonify({'success': True, 'message': 'Guard deleted'})


# =========================
# 新增陪伴榜成员（必须管理员权限）
# =========================

@admin_bp.route('/companion/add', methods=['POST'])
@require_admin
def admin_companion_add():

    # 验证CSRF Token
    csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid or missing'}), 403

    uid = request.form.get('uid')
    nickname = request.form.get('nickname')
    guard_level = request.form.get('guard_level', 'guard')
    in_guard = request.form.get('in_guard', 'true')
    accompany_days = request.form.get('accompany_days', '0')

    if not uid:
        return jsonify({'error': 'UID is required'}), 400

    if not nickname:
        return jsonify({'error': 'Nickname is required'}), 400

    # Check if guard already exists
    existing_guard = Guard.query.filter_by(uid=uid).first()
    if existing_guard:
        return jsonify({'error': 'Guard already exists'}), 400

    # Create new guard
    new_guard = Guard(
        uid=uid,
        nickname=nickname,
        guard_level=guard_level,
        in_guard=in_guard.lower() == 'true',
        accompany_days=int(accompany_days) if accompany_days else 0,
        last_guard_date=date.today(),
        updated_at=get_beijing_now()
    )

    db.session.add(new_guard)
    db.session.commit()

    # 清除 API 缓存（因为舰长列表已变更）
    from utils.cache_utils import api_response_cache
    api_response_cache.clear_pattern(f"guards:")

    return jsonify({'success': True, 'message': 'Guard added'})


# =========================
# 陪伴榜（大航海陪伴天数排行榜）（必须管理员权限）
# =========================

@admin_bp.route('/companion-ranking')
@require_admin
def admin_companion_ranking():

    # 速率限制检查
    is_allowed, wait_time = AdminService.check_admin_rate_limit(current_user.uid, "companion_ranking")
    if not is_allowed:
        flash(f'请求过于频繁，请 {wait_time} 秒后重试', 'error')
        return redirect(url_for('main.index'))

    # Get rank_type parameter (kept for compatibility, but not used for guards)
    rank_type = request.args.get('rank_type', 1, type=int)
    if rank_type not in [1, 2]:
        rank_type = 1

    # Get status filter parameter
    status_filter = request.args.get('status', 'all')

    # Fetch all guards from database (synced with guard table)
    guards = Guard.query.all()

    # Apply status filter
    if status_filter == 'in_guard':
        guards = [g for g in guards if g.in_guard]
    elif status_filter == 'not_in_guard':
        guards = [g for g in guards if not g.in_guard]

    # Convert guards to list format for template
    all_items = []
    for guard in guards:
        item = {
            'uid': guard.uid,
            'nickname': guard.nickname,
            'guard_level': guard.guard_level,
            'accompany_days': guard.accompany_days or 0,
            'in_guard': guard.in_guard,
            'user_rank': 0  # Not applicable for guards
        }
        all_items.append(item)

    # Sort by accompany_days descending
    all_items.sort(key=lambda x: x.get('accompany_days', 0), reverse=True)

    # Add rank to each item
    for idx, item in enumerate(all_items, 1):
        item['user_rank'] = idx

    return render_template(
        'admin_companion.html',
        uid=current_user.uid,
        nickname=current_user.nickname,
        items=all_items,
        total=len(all_items),
        medal_status=0,  # Not applicable for guards
        rank_type=rank_type,
        status_filter=status_filter
    )


# =========================
# 导出陪伴榜 CSV（必须管理员权限）
# =========================

@admin_bp.route('/export/companion-ranking')
@require_admin
def admin_export_companion_ranking():

    # Get rank_type parameter (kept for compatibility, but not used for guards)
    rank_type = request.args.get('rank_type', 1, type=int)
    if rank_type not in [1, 2]:
        rank_type = 1

    # Get status filter parameter
    status_filter = request.args.get('status', 'all')

    # Fetch all guards from database (synced with guard table)
    guards = Guard.query.all()

    # Apply status filter
    if status_filter == 'in_guard':
        guards = [g for g in guards if g.in_guard]
    elif status_filter == 'not_in_guard':
        guards = [g for g in guards if not g.in_guard]

    # Convert guards to list format for CSV
    all_items = []
    for guard in guards:
        item = {
            'uid': guard.uid,
            'nickname': guard.nickname,
            'guard_level': guard.guard_level,
            'guard_level_name': GUARD_LEVEL_NAME_MAP.get(guard.guard_level, '舰长'),
            'accompany_days': guard.accompany_days or 0,
            'in_guard': guard.in_guard,
            'user_rank': 0
        }
        all_items.append(item)

    # Sort by accompany_days descending
    all_items.sort(key=lambda x: x.get('accompany_days', 0), reverse=True)

    # Add rank to each item
    for idx, item in enumerate(all_items, 1):
        item['user_rank'] = idx

    # Generate CSV
    csv_content = generate_companion_ranking_csv(all_items, rank_type)

    # Return CSV file
    return create_csv_response(csv_content, 'companion_ranking_guards')


# =========================
# 陪伴榜 CSV 生成函数
# =========================

def generate_companion_ranking_csv(items: list, rank_type: int) -> str:
    """
    生成陪伴榜 CSV 内容

    Args:
        items: 陪伴榜用户列表
        rank_type: 排序方式 (1=粉丝牌亮着, 2=未上舰)

    Returns:
        str: CSV 内容
    """
    import csv
    from io import StringIO

    output = StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow(['排名', 'UID', '昵称', '大航海', '是否在舰', '陪伴天数'])

    # Data
    for item in items:
        guard_level = item.get('guard_level', 'guard')
        guard_level_name = GUARD_LEVEL_NAME_MAP.get(guard_level, '舰长')
        in_guard_status = '是' if item.get('in_guard', False) else '否'

        writer.writerow([
            item.get('user_rank', ''),
            item.get('uid', ''),
            item.get('nickname', ''),
            guard_level_name,
            in_guard_status,
            item.get('accompany_days', 0)
        ])

    csv_content = output.getvalue()
    output.close()
    return csv_content


# =========================
# 导入CSV（必须管理员权限）
# =========================

@admin_bp.route('/import/csv', methods=['POST'])
@require_admin
def admin_import_csv():
    """导入CSV数据到数据库"""
    import csv
    from io import StringIO
    from datetime import date
    from db.models import get_beijing_now

    # 验证CSRF Token
    csrf_token = request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid or missing'}), 403

    # Get import type
    import_type = request.args.get('type')
    if not import_type:
        return jsonify({'error': 'Import type is required'}), 400

    # Get CSV file
    if 'csv_file' not in request.files:
        return jsonify({'error': 'No CSV file provided'}), 400

    csv_file = request.files['csv_file']
    if csv_file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not csv_file.filename.endswith('.csv'):
        return jsonify({'error': 'File must be a CSV file'}), 400

    try:
        # Read CSV content with encoding detection
        csv_bytes = csv_file.read()

        # Try UTF-8 first, then fall back to GBK for Chinese files
        try:
            csv_content = csv_bytes.decode('utf-8')
        except UnicodeDecodeError:
            csv_content = csv_bytes.decode('gbk')

        reader = csv.DictReader(StringIO(csv_content))

        added_count = 0
        updated_count = 0
        skipped_count = 0

        for row in reader:
            uid = row.get('UID') or row.get('uid')
            if not uid:
                skipped_count += 1
                continue

            if import_type == 'address':
                # Import address data
                nickname = row.get('昵称') or row.get('nickname')
                receiver = row.get('收件人') or row.get('receiver')
                phone = row.get('手机号') or row.get('phone')
                province = row.get('省') or row.get('province')
                city = row.get('市') or row.get('city')
                area = row.get('区') or row.get('area')
                address = row.get('详细地址') or row.get('address')

                if not nickname:
                    skipped_count += 1
                    continue

                # Check if address already exists
                existing = Address.query.filter_by(uid=uid).first()
                if existing:
                    # Update existing
                    existing.nickname = nickname
                    existing.receiver = receiver
                    existing.phone = phone
                    existing.province = province
                    existing.city = city
                    existing.area = area
                    existing.address = address
                    updated_count += 1
                else:
                    # Create new
                    new_address = Address(
                        uid=uid,
                        nickname=nickname,
                        receiver=receiver,
                        phone=phone,
                        province=province,
                        city=city,
                        area=area,
                        address=address,
                        submitted_at=get_beijing_now()
                    )
                    db.session.add(new_address)
                    added_count += 1

            elif import_type == 'guard':
                # Import guard data
                nickname = row.get('昵称') or row.get('nickname')
                guard_level = row.get('身份') or row.get('guard_level')
                in_guard_str = row.get('是否在舰') or row.get('in_guard')
                accompany_days = row.get('陪伴天数') or row.get('accompany_days')

                if not nickname:
                    skipped_count += 1
                    continue

                # Map guard level
                if guard_level == '总督' or guard_level == 'admiral':
                    guard_level = 'admiral'
                elif guard_level == '提督' or guard_level == 'captain':
                    guard_level = 'captain'
                else:
                    guard_level = 'guard'

                # Map in_guard
                if in_guard_str == '是' or in_guard_str == 'true':
                    in_guard = True
                else:
                    in_guard = False

                # Map accompany_days
                if accompany_days:
                    try:
                        accompany_days = int(accompany_days)
                    except:
                        accompany_days = 0
                else:
                    accompany_days = 0

                # Check if guard already exists
                existing = Guard.query.filter_by(uid=uid).first()
                if existing:
                    # Update existing
                    existing.nickname = nickname
                    existing.guard_level = guard_level
                    existing.in_guard = in_guard
                    existing.accompany_days = accompany_days
                    existing.last_guard_date = date.today()
                    existing.updated_at = get_beijing_now()
                    updated_count += 1
                else:
                    # Create new
                    new_guard = Guard(
                        uid=uid,
                        nickname=nickname,
                        guard_level=guard_level,
                        in_guard=in_guard,
                        accompany_days=accompany_days,
                        last_guard_date=date.today(),
                        updated_at=get_beijing_now()
                    )
                    db.session.add(new_guard)
                    added_count += 1

            elif import_type == 'guard_gift':
                # Import guard gift data
                nickname = row.get('昵称') or row.get('nickname')
                guard_level = row.get('身份') or row.get('guard_level')
                month = row.get('月份') or row.get('month')
                accompany_days = row.get('陪伴天数') or row.get('accompany_days')
                received_str = row.get('领取状态') or row.get('received')

                if not nickname or not month:
                    skipped_count += 1
                    continue

                # Map guard level
                if guard_level == '总督' or guard_level == 'admiral':
                    guard_level = 'admiral'
                elif guard_level == '提督' or guard_level == 'captain':
                    guard_level = 'captain'
                else:
                    guard_level = 'guard'

                # Map received
                if received_str == '是' or received_str == 'true':
                    received = True
                else:
                    received = False

                # Map accompany_days
                if accompany_days:
                    try:
                        accompany_days = int(accompany_days)
                    except:
                        accompany_days = 0
                else:
                    accompany_days = 0

                # Check if record already exists
                existing = GuardGiftRecord.query.filter_by(uid=uid, month=month).first()
                if existing:
                    # Update existing
                    existing.nickname = nickname
                    existing.guard_level = guard_level
                    existing.accompany_days = accompany_days
                    existing.received = received
                    existing.updated_at = get_beijing_now()
                    updated_count += 1
                else:
                    # Create new
                    new_record = GuardGiftRecord(
                        uid=uid,
                        nickname=nickname,
                        guard_level=guard_level,
                        month=month,
                        accompany_days=accompany_days,
                        received=received,
                        created_at=get_beijing_now(),
                        updated_at=get_beijing_now()
                    )
                    db.session.add(new_record)
                    added_count += 1

            elif import_type == 'companion':
                # Import companion data (same as guard)
                nickname = row.get('昵称') or row.get('nickname')
                guard_level = row.get('大航海') or row.get('guard_level')
                in_guard_str = row.get('是否在舰') or row.get('in_guard')
                accompany_days = row.get('陪伴天数') or row.get('accompany_days')

                if not nickname:
                    skipped_count += 1
                    continue

                # Map guard level
                if guard_level == '总督' or guard_level == 'admiral':
                    guard_level = 'admiral'
                elif guard_level == '提督' or guard_level == 'captain':
                    guard_level = 'captain'
                else:
                    guard_level = 'guard'

                # Map in_guard
                if in_guard_str == '是' or in_guard_str == 'true':
                    in_guard = True
                else:
                    in_guard = False

                # Map accompany_days
                if accompany_days:
                    try:
                        accompany_days = int(accompany_days)
                    except:
                        accompany_days = 0
                else:
                    accompany_days = 0

                # Check if guard already exists
                existing = Guard.query.filter_by(uid=uid).first()
                if existing:
                    # Update existing
                    existing.nickname = nickname
                    existing.guard_level = guard_level
                    existing.in_guard = in_guard
                    existing.accompany_days = accompany_days
                    existing.last_guard_date = date.today()
                    existing.updated_at = get_beijing_now()
                    updated_count += 1
                else:
                    # Create new
                    new_guard = Guard(
                        uid=uid,
                        nickname=nickname,
                        guard_level=guard_level,
                        in_guard=in_guard,
                        accompany_days=accompany_days,
                        last_guard_date=date.today(),
                        updated_at=get_beijing_now()
                    )
                    db.session.add(new_guard)
                    added_count += 1

            else:
                return jsonify({'error': f'Unknown import type: {import_type}'}), 400

        db.session.commit()

        return jsonify({
            'success': True,
            'added': added_count,
            'updated': updated_count,
            'skipped': skipped_count
        })

    except Exception as e:
        db.session.rollback()
        print(f"CSV import error: {e}")
        return jsonify({'error': f'CSV导入失败: {str(e)}'}), 500


# =========================
# Cookie管理接口（管理员）
# =========================

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
        'listener': listener_status
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
        return jsonify({'success': True, 'message': 'buvid3刷新成功'})
    else:
        return jsonify({'error': 'buvid3刷新失败，请检查playwright是否安装'}), 500


@admin_bp.route('/cookie/qrcode')
@require_admin
def admin_cookie_qrcode():
    """获取登录二维码"""
    import os
    import time
    from flask import send_file
    
    QR_IMAGE_PATH = '/tmp/bilibili_qr.png'
    
    # 检查二维码是否存在
    if os.path.exists(QR_IMAGE_PATH):
        # 检查是否是最近5分钟生成的
        if time.time() - os.path.getmtime(QR_IMAGE_PATH) < 300:
            return send_file(QR_IMAGE_PATH, mimetype='image/png')
    
    return jsonify({'error': '二维码不存在或已过期，请先启动扫码登录'}), 404


@admin_bp.route('/cookie/start-qr-login', methods=['POST'])
@require_admin
def admin_start_qr_login():
    """启动扫码登录"""
    import threading
    from services.cookie_service import CookieService
    from services.danmaku_listener import restart_listener
    
    csrf_token = request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'error': 'CSRF token invalid'}), 403
    
    # 清除之前的二维码
    import os
    QR_PATH = '/tmp/bilibili_qr.png'
    if os.path.exists(QR_PATH):
        os.remove(QR_PATH)
    
    def do_login():
        try:
            logger.info("开始扫码登录流程...")
            sessdata, bili_jct = CookieService.get_sessdata_by_qr()
            if sessdata:
                logger.info(f"获取到SESSDATA，长度: {len(sessdata)}")
                settings = CookieService.load_settings()
                settings.setdefault('bilibili', {})['SESSDATA'] = sessdata
                if bili_jct:
                    settings['bilibili']['bili_jct'] = bili_jct
                CookieService.save_settings(settings)
                logger.info("Cookie已保存到settings.json")
                
                # 重启弹幕监听
                restart_listener()
                logger.info("弹幕监听已重启")
            else:
                logger.warning("扫码登录未获取到SESSDATA")
        except Exception as e:
            logger.error(f"扫码登录失败: {e}", exc_info=True)
    
    thread = threading.Thread(target=do_login, daemon=True)
    thread.start()
    
    return jsonify({'success': True, 'message': '扫码登录已启动，请查看二维码'})


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
# 注册蓝图
# =========================

def register_routes(app):
    """注册所有路由蓝图"""
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)

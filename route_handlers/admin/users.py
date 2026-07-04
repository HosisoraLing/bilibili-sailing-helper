import os
from route_handlers.common import *


@admin_bp.route('/users')
@require_admin
def admin_users():
    """用户管理列表页面"""
    is_allowed, wait_time = AdminService.check_admin_rate_limit(current_user.uid, "admin_users")
    if not is_allowed:
        flash(f'请求过于频繁，请 {wait_time} 秒后重试', 'error')
        return redirect(url_for('admin.admin_panel'))

    users = AdminService.get_all_users()
    from config import RUID_INT

    return render_template(
        'admin_users.html',
        uid=current_user.uid,
        nickname=current_user.nickname,
        users=users,
        anchor_uid=str(RUID_INT),
        total_count=len(users),
    )


@admin_bp.route('/repair-nicknames')
@require_admin
def repair_nicknames_preview():
    """预览昵称修复（dry-run）"""
    from db.models import Guard, Address, User

    guards = {g.uid: g for g in Guard.query.all()}
    discrepancies = []

    # 检查 Address 表
    for addr in Address.query.all():
        if addr.uid in guards:
            guard = guards[addr.uid]
            if addr.nickname != guard.nickname:
                discrepancies.append({
                    'table': 'Address',
                    'uid': addr.uid,
                    'current': addr.nickname,
                    'correct': guard.nickname,
                    'record_id': addr.id
                })

    # 检查 User 表
    for user in User.query.all():
        if user.nickname and user.nickname.startswith('管理员_'):
            continue
        if user.uid in guards:
            guard = guards[user.uid]
            if user.nickname != guard.nickname:
                discrepancies.append({
                    'table': 'User',
                    'uid': user.uid,
                    'current': user.nickname,
                    'correct': guard.nickname,
                    'record_id': user.id
                })

    return jsonify({
        'success': True,
        'count': len(discrepancies),
        'discrepancies': discrepancies
    })


@admin_bp.route('/repair-nicknames/apply', methods=['POST'])
@require_admin
def repair_nicknames_apply():
    """应用昵称修复"""
    csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'success': False, 'error': 'CSRF token invalid or missing'}), 403

    from db.models import Guard, Address, User
    import shutil
    from datetime import datetime

    guards = {g.uid: g for g in Guard.query.all()}
    fixed_count = 0
    details = []

    # 修复 Address 表
    for addr in Address.query.all():
        if addr.uid in guards:
            guard = guards[addr.uid]
            if addr.nickname != guard.nickname:
                old_nickname = addr.nickname
                addr.nickname = guard.nickname
                fixed_count += 1
                details.append({
                    'table': 'Address',
                    'uid': addr.uid,
                    'old': old_nickname,
                    'new': guard.nickname
                })

    # 修复 User 表
    for user in User.query.all():
        if user.nickname and user.nickname.startswith('管理员_'):
            continue
        if user.uid in guards:
            guard = guards[user.uid]
            if user.nickname != guard.nickname:
                old_nickname = user.nickname
                user.nickname = guard.nickname
                fixed_count += 1
                details.append({
                    'table': 'User',
                    'uid': user.uid,
                    'old': old_nickname,
                    'new': guard.nickname
                })

    if fixed_count > 0:
        # 备份数据库
        from config import Config
        db_url = Config.SQLALCHEMY_DATABASE_URI
        if db_url.startswith('sqlite:///'):
            db_path = db_url.replace('sqlite:///', '')
            if db_path and os.path.exists(db_path):
                backup_dir = os.path.join(os.path.dirname(os.path.dirname(db_path)), 'backups')
                os.makedirs(backup_dir, exist_ok=True)
                timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
                backup_path = os.path.join(backup_dir, f'data-{timestamp}.db')
                shutil.copy2(db_path, backup_path)

        db.session.commit()

    return jsonify({
        'success': True,
        'fixed_count': fixed_count,
        'details': details
    })


@admin_bp.route('/users/add', methods=['POST'])
@require_admin
def admin_user_add():
    """新增用户"""
    csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'success': False, 'error': 'CSRF token invalid or missing'}), 403

    uid = request.form.get('uid', '').strip()
    nickname = request.form.get('nickname', '').strip()
    is_admin = request.form.get('is_admin') == 'true'

    if not uid:
        return jsonify({'success': False, 'error': 'UID 不能为空'}), 400
    if not nickname:
        return jsonify({'success': False, 'error': '昵称不能为空'}), 400

    success, error_msg = AdminService.create_user(uid, nickname, is_admin)
    if not success:
        return jsonify({'success': False, 'error': error_msg}), 400

    return jsonify({'success': True, 'message': f'用户 {nickname} 创建成功'})


@admin_bp.route('/users/edit', methods=['POST'])
@require_admin
def admin_user_edit():
    """编辑用户"""
    csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'success': False, 'error': 'CSRF token invalid or missing'}), 403

    uid = request.form.get('uid', '').strip()
    nickname = request.form.get('nickname', '').strip()

    if not uid:
        return jsonify({'success': False, 'error': 'UID 不能为空'}), 400

    user = AdminService.get_user_by_uid(uid)
    if not user:
        return jsonify({'success': False, 'error': '用户不存在'}), 404

    if nickname:
        AdminService.update_user(user, nickname)

    return jsonify({'success': True, 'message': '用户信息已更新'})


@admin_bp.route('/users/delete', methods=['POST'])
@require_admin
def admin_user_delete():
    """删除用户及其所有记录"""
    csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'success': False, 'error': 'CSRF token invalid or missing'}), 403

    is_valid, error_msg = RequestValidator.validate_sensitive_request()
    if not is_valid:
        return jsonify({'success': False, 'error': error_msg or '安全验证失败'}), 403

    uid = request.form.get('uid', '').strip()
    if not uid:
        return jsonify({'success': False, 'error': 'UID 不能为空'}), 400

    if AdminService.is_anchor(uid):
        return jsonify({'success': False, 'error': '不可删除主播账号'}), 403

    success, error_msg = AdminService.delete_user_all_records(uid)
    if not success:
        return jsonify({'success': False, 'error': error_msg}), 404

    return jsonify({'success': True, 'message': '用户及其所有记录已删除'})


@admin_bp.route('/users/set-admin', methods=['POST'])
@require_admin
def admin_user_set_admin():
    """设置用户为管理员"""
    csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'success': False, 'error': 'CSRF token invalid or missing'}), 403

    uid = request.form.get('uid', '').strip()
    if not uid:
        return jsonify({'success': False, 'error': 'UID 不能为空'}), 400

    user = AdminService.get_user_by_uid(uid)
    if not user:
        return jsonify({'success': False, 'error': '用户不存在'}), 404

    AdminService.set_user_admin(user)
    return jsonify({'success': True, 'message': f'已将 {user.nickname} 设置为管理员'})


@admin_bp.route('/users/unset-admin', methods=['POST'])
@require_admin
def admin_user_unset_admin():
    """取消用户的管理员身份"""
    csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not csrf_token or not UserService.verify_csrf_token(csrf_token):
        return jsonify({'success': False, 'error': 'CSRF token invalid or missing'}), 403

    uid = request.form.get('uid', '').strip()
    if not uid:
        return jsonify({'success': False, 'error': 'UID 不能为空'}), 400

    user = AdminService.get_user_by_uid(uid)
    if not user:
        return jsonify({'success': False, 'error': '用户不存在'}), 404

    success, error_msg = AdminService.unset_user_admin(user)
    if not success:
        return jsonify({'success': False, 'error': error_msg}), 403

    return jsonify({'success': True, 'message': f'已取消 {user.nickname} 的管理员身份'})

from route_handlers.common import *

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

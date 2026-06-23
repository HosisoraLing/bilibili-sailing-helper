from route_handlers.common import *

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

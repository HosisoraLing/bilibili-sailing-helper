from route_handlers.common import *

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
    if month not in available_months:
        available_months = [month, *available_months]

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

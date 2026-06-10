from route_handlers.common import *

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

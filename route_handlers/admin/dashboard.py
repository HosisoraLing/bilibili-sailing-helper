from route_handlers.common import *

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

from route_handlers.common import *
from route_handlers.common import (
    _internal_authorized,
    _internal_json_payload,
    _internal_unauthorized,
)

@internal_bp.route('/runtime/heartbeat', methods=['POST'])
def internal_runtime_heartbeat():
    if not _internal_authorized():
        return _internal_unauthorized()

    try:
        status = record_runtime_heartbeat(_internal_json_payload())
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify({
        'status': 'ok',
        'role': status.role,
        'instance_id': status.instance_id,
        'state': status.state,
    })


@internal_bp.route('/runtime/cookie', methods=['GET'])
def internal_runtime_cookie():
    if not _internal_authorized():
        return _internal_unauthorized()

    return jsonify(RuntimeCookieService.get_runtime_cookie_payload())


@internal_bp.route('/danmaku/auth-event', methods=['POST'])
def internal_danmaku_auth_event():
    if not _internal_authorized():
        return _internal_unauthorized()

    try:
        result = process_danmaku_auth_event(_internal_json_payload())
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify({'status': 'ok', **result})


def run_pending_scheduler_job(job):
    started_at = get_beijing_now().isoformat()
    job_status = 'success'
    error = ''
    try:
        if job.job_type == 'guard-sync':
            fetch_and_save_guards()
            summary = 'guard-sync completed'
        elif job.job_type == 'guard-gift-refresh':
            eligible_records = GuardGiftService.calculate_monthly_eligible_guards()
            historical_records = GuardGiftService.update_historical_months()
            summary = (
                f"guard-gift-refresh completed: "
                f"{len(eligible_records or [])} current, "
                f"{len(historical_records or [])} historical"
            )
        elif job.job_type == 'cookie-maintenance':
            maintenance_result = CookieMaintenanceService.run_cookie_maintenance()
            job_status = maintenance_result.get('status') or 'unknown'
            summary = maintenance_result.get('summary') or 'cookie-maintenance completed'
            error = maintenance_result.get('error') or ''
        elif job.job_type == 'auth-cleanup':
            cleaned = cleanup_expired_sessions()
            summary = f"auth-cleanup completed: {cleaned} expired sessions"
        else:
            return {'executed': False, 'job_status': job.status}
    except Exception as exc:
        record_scheduler_result({
            'job_id': job.job_id,
            'job_name': job.job_type,
            'status': 'failed',
            'started_at': started_at,
            'finished_at': get_beijing_now().isoformat(),
            'summary': f'{job.job_type} failed',
            'error': str(exc),
        })
        return {'executed': True, 'job_status': 'failed', 'error': str(exc)}
    else:
        record_scheduler_result({
            'job_id': job.job_id,
            'job_name': job.job_type,
            'status': job_status,
            'started_at': started_at,
            'finished_at': get_beijing_now().isoformat(),
            'summary': summary,
            'error': error,
        })
        result = {'executed': True, 'job_status': job_status}
        if error:
            result['error'] = error
        return result


@internal_bp.route('/scheduler/job', methods=['POST'])
def internal_scheduler_job():
    if not _internal_authorized():
        return _internal_unauthorized()

    job = None
    try:
        job = create_scheduler_job(_internal_json_payload())
    except ConflictError as exc:
        return jsonify({'error': str(exc)}), 409
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify({
        'status': 'ok',
        'job_id': job.job_id,
        'job_name': job.job_type,
        'accepted': True,
        'job_status': job.status,
    })


@internal_bp.route('/scheduler/result', methods=['POST'])
def internal_scheduler_result():
    if not _internal_authorized():
        return _internal_unauthorized()

    try:
        job = record_scheduler_result(_internal_json_payload())
    except ConflictError as exc:
        return jsonify({'error': str(exc)}), 409
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify({
        'status': 'ok',
        'job_id': job.job_id,
        'job_name': job.job_type,
        'job_status': job.status,
    })

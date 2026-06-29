import os
from route_handlers.common import *

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'logs')
ERROR_LOG_FILE = os.path.join(LOG_DIR, 'error.log')


def _read_log_tail(filepath, max_lines=500):
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        return lines[-max_lines:]
    except (OSError, PermissionError):
        return []


def _parse_log_entries(lines):
    entries = []
    current = None

    for line in lines:
        line = line.rstrip('\n')
        if not line:
            continue

        if line.startswith('20') and '[' in line and ']' in line:
            if current:
                entries.append(current)
            parts = line.split(' ', 2)
            timestamp = parts[0] + ' ' + parts[1] if len(parts) > 1 else ''
            rest = parts[2] if len(parts) > 2 else ''

            level = 'INFO'
            if '[ERROR]' in rest:
                level = 'ERROR'
            elif '[WARN]' in rest:
                level = 'WARN'
            elif '[DEBUG]' in rest:
                level = 'DEBUG'

            bracket_end = rest.find(']')
            source = rest[1:bracket_end] if bracket_end > 0 else ''
            message = rest[bracket_end + 2:] if bracket_end > 0 else rest

            current = {
                'timestamp': timestamp,
                'level': level,
                'source': source,
                'message': message,
                'raw': line,
            }
        elif current:
            current['message'] += '\n' + line
            current['raw'] += '\n' + line

    if current:
        entries.append(current)

    return entries


@admin_bp.route('/logs')
@require_admin
def admin_logs():
    lines = _read_log_tail(ERROR_LOG_FILE, max_lines=500)
    entries = _parse_log_entries(lines)
    entries.reverse()

    return render_template(
        'admin_logs.html',
        uid=current_user.uid,
        nickname=current_user.nickname,
        entries=entries,
        log_file=ERROR_LOG_FILE,
    )


@admin_bp.route('/logs/raw')
@require_admin
def admin_logs_raw():
    lines = _read_log_tail(ERROR_LOG_FILE, max_lines=500)
    return jsonify({
        'lines': [line.rstrip('\n') for line in lines],
        'count': len(lines),
    })

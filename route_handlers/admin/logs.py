import os
import threading
import time
from route_handlers.common import *

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'logs')
ERROR_LOG_FILE = os.path.join(LOG_DIR, 'error.log')

_tail_thread = None
_tail_lock = threading.Lock()


def _parse_log_line(line):
    line = line.rstrip('\n')
    if not line:
        return None

    if line.startswith('20') and '[' in line and ']' in line:
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

        return {
            'timestamp': timestamp,
            'level': level,
            'source': source,
            'message': message,
            'raw': line,
        }
    return {'raw': line, 'message': line, 'level': 'INFO', 'timestamp': '', 'source': ''}


def _tail_log_file(app, socketio):
    last_size = 0
    if os.path.exists(ERROR_LOG_FILE):
        try:
            last_size = os.path.getsize(ERROR_LOG_FILE)
        except OSError:
            pass

    while True:
        try:
            if not os.path.exists(ERROR_LOG_FILE):
                time.sleep(1)
                continue

            current_size = os.path.getsize(ERROR_LOG_FILE)

            if current_size < last_size:
                last_size = 0

            if current_size > last_size:
                with open(ERROR_LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
                    f.seek(last_size)
                    new_lines = f.readlines()
                    last_size = f.tell()

                with app.app_context():
                    for line in new_lines:
                        entry = _parse_log_line(line)
                        if entry:
                            socketio.emit('log_entry', entry, namespace='/logs')

            time.sleep(0.5)
        except Exception:
            time.sleep(1)


def start_tail_thread(app, socketio):
    global _tail_thread
    with _tail_lock:
        if _tail_thread and _tail_thread.is_alive():
            return
        _tail_thread = threading.Thread(target=_tail_log_file, args=(app, socketio), daemon=True)
        _tail_thread.start()


def _read_log_tail(filepath, max_lines=200):
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        return lines[-max_lines:]
    except (OSError, PermissionError):
        return []


@admin_bp.route('/logs')
@require_admin
def admin_logs():
    lines = _read_log_tail(ERROR_LOG_FILE, max_lines=200)
    entries = []
    for line in lines:
        entry = _parse_log_line(line)
        if entry:
            entries.append(entry)
    entries.reverse()

    return render_template(
        'admin_logs.html',
        uid=current_user.uid,
        nickname=current_user.nickname,
        entries=entries,
    )


@admin_bp.route('/logs/raw')
@require_admin
def admin_logs_raw():
    lines = _read_log_tail(ERROR_LOG_FILE, max_lines=200)
    return jsonify({
        'lines': [line.rstrip('\n') for line in lines],
        'count': len(lines),
    })

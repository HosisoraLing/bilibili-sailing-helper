"""Shared route dependencies and Blueprint instances."""
from datetime import date
from flask import (
    Blueprint, request, render_template, redirect,
    url_for, jsonify, flash, session
)
from flask_login import login_user, current_user, logout_user

from db.models import db, User, Address, Guard, GuardGiftRecord, get_beijing_now
from services.address_service import save_address, get_user_address
from services.auth_service import (
    cleanup_expired_sessions,
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
from services.internal_api_service import (
    ConflictError,
    create_scheduler_job,
    pending_auth_runtime_state,
    process_danmaku_auth_event,
    record_runtime_heartbeat,
    record_scheduler_result,
    runtime_health_summary,
    verify_internal_secret,
)
from services.runtime_cookie_service import RuntimeCookieService
from services.bilibili_qr_service import poll_qr_login, start_qr_login
from services.bilibili_qr_service import get_qr_login_task, render_qr_png
from services.cookie_service import CookieService
from services.cookie_maintenance_service import CookieMaintenanceService
from services.tv_auth_service import (
    poll_tv_qr_login,
    start_tv_qr_login,
    tv_auth_status_payload,
)
from utils.request_utils import get_uid_from_request
from utils.csv_utils import create_csv_response
from utils.cache_utils import (
    invalidate_cache,
    user_cache,
    guard_cache,
    address_cache,
    api_response_cache,
)
from utils.log_utils import get_logger
from decorators import (
    require_login,
    require_guard_or_admin,
    require_admin,
)

logger = get_logger(__name__)

main_bp = Blueprint('main', __name__)
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')
internal_bp = Blueprint('internal', __name__, url_prefix='/internal')


def fetch_and_save_guards():
    from app import fetch_and_save_guards as app_fetch_and_save_guards

    return app_fetch_and_save_guards()


def _internal_json_payload():
    return request.get_json(silent=True) or {}


def _internal_authorized():
    secret = request.headers.get('Authorization')
    return verify_internal_secret(secret)


def _internal_unauthorized():
    return jsonify({'error': 'invalid internal secret'}), 401

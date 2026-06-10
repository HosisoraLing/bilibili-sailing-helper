from db.models import CookieMetadata, db
from services.tv_auth_service import (
    DEFAULT_REFRESH_THRESHOLD_DAYS,
    refresh_tv_auth,
    sessdata_needs_refresh,
    store_tv_auth_success,
)


class CookieMaintenanceService:
    @staticmethod
    def run_cookie_maintenance(http_client=None, refresh_threshold_days: int = DEFAULT_REFRESH_THRESHOLD_DAYS):
        return run_cookie_maintenance(
            http_client=http_client,
            refresh_threshold_days=refresh_threshold_days,
        )


def run_cookie_maintenance(
    http_client=None,
    refresh_threshold_days: int = DEFAULT_REFRESH_THRESHOLD_DAYS,
) -> dict:
    metadata = CookieMetadata.query.filter_by(role="admin").first()
    if metadata is None:
        return {
            "status": "failed",
            "action": "rescan_required",
            "summary": "cookie-maintenance failed: no TV authorization",
            "next_action": "请扫码授权 B 站账号",
            "error": "missing TV authorization",
        }

    if not sessdata_needs_refresh(metadata, threshold_days=refresh_threshold_days):
        return {
            "status": "success",
            "action": "noop",
            "summary": "cookie-maintenance noop: SESSDATA is not near expiry",
            "next_action": "无需操作",
        }

    try:
        payload = refresh_tv_auth(metadata, http_client=http_client)
        store_tv_auth_success(payload, http_client=http_client)
    except Exception as exc:
        metadata.status = "rescan_required"
        metadata.last_error = str(exc)
        db.session.commit()
        return {
            "status": "failed",
            "action": "rescan_required",
            "summary": "cookie-maintenance failed: rescan required",
            "next_action": "请重新扫码授权 B 站账号",
            "error": str(exc),
        }

    return {
        "status": "success",
        "action": "refreshed",
        "summary": "cookie-maintenance refreshed TV authorization",
        "next_action": "无需操作",
    }

from db.models import CookieMetadata, db
from services.bilibili_qr_service import (
    WebCookieRefreshRejected,
    cookie_header_from_map,
    cookie_map_from_metadata,
    refresh_web_qr_cookie,
    validate_cookie_header,
)


DEFAULT_REFRESH_THRESHOLD_DAYS = 10


class CookieMaintenanceService:
    @staticmethod
    def run_cookie_maintenance(
        http_client=None,
        refresh_threshold_days: int = DEFAULT_REFRESH_THRESHOLD_DAYS,
        force: bool = False,
    ):
        return run_cookie_maintenance(
            http_client=http_client,
            refresh_threshold_days=refresh_threshold_days,
            force=force,
        )


def run_cookie_maintenance(
    http_client=None,
    refresh_threshold_days: int = DEFAULT_REFRESH_THRESHOLD_DAYS,
    force: bool = False,
) -> dict:
    metadata = CookieMetadata.query.filter_by(role="admin").first()
    if metadata is None:
        return {
            "status": "failed",
            "action": "rescan_required",
            "summary": "cookie-maintenance failed: no Web QR authorization",
            "next_action": "请扫码授权 B 站账号",
            "error": "missing Web QR authorization",
        }

    if metadata.source != "qr_login" or not metadata.web_refresh_token:
        metadata.status = "rescan_required"
        metadata.last_error = "missing Web refresh token"
        db.session.commit()
        return {
            "status": "failed",
            "action": "rescan_required",
            "summary": "cookie-maintenance failed: Web refresh token is missing",
            "next_action": "请重新扫码授权 B 站账号",
            "error": "missing Web refresh token",
        }

    try:
        return refresh_web_qr_cookie(metadata, http_client=http_client, force=force)
    except WebCookieRefreshRejected as exc:
        is_valid = False
        cookie_map = cookie_map_from_metadata(metadata)
        if cookie_map.get("SESSDATA"):
            validation = validate_cookie_header(
                cookie_header_from_map(cookie_map),
                http_client=http_client,
            )
            is_valid = bool(validation.get("valid"))
        if is_valid:
            metadata.status = "valid"
            metadata.last_error = str(exc)
            db.session.commit()
            return {
                "status": "failed",
                "action": "refresh_rejected",
                "summary": "cookie-maintenance failed: Web refresh was rejected but current Cookie is still valid",
                "next_action": "当前 Cookie 仍有效；请在 Cookie 过期前重新扫码刷新 token",
                "error": str(exc),
            }
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

from typing import Any

from db.models import CookieMetadata, RuntimeStatus
from services.bilibili_qr_service import parse_cookie_header


class RuntimeCookieService:
    @staticmethod
    def load_runtime_cookie(metadata: CookieMetadata | None = None) -> dict[str, str]:
        if metadata and metadata.cookie_header:
            return parse_cookie_header(metadata.cookie_header)
        return {}

    @staticmethod
    def get_runtime_cookie_payload(role: str = "admin") -> dict[str, Any]:
        metadata = CookieMetadata.query.filter_by(role=role).first()
        if metadata is None:
            return {
                "status": "missing",
                "version": 0,
                "reload_requested_version": 0,
                "reload_requested_at": "",
                "cookie": {},
            }

        cookie = RuntimeCookieService.load_runtime_cookie(metadata)
        missing_keys = [
            key
            for key in ("SESSDATA",)
            if not cookie.get(key)
        ]
        status = metadata.status
        last_error = metadata.last_error or ""
        if metadata.status == "valid" and missing_keys:
            status = "invalid"
            last_error = f"Cookie 配置缺少 {', '.join(missing_keys)}"
        return {
            "status": status,
            "version": int(metadata.cookie_version or 0),
            "reload_requested_version": int(metadata.reload_requested_version or 0),
            "reload_requested_at": (
                metadata.reload_requested_at.isoformat()
                if metadata.reload_requested_at
                else ""
            ),
            "masked_uid": metadata.masked_uid or "",
            "updated_at": metadata.updated_at.isoformat() if metadata.updated_at else "",
            "last_validated_at": (
                metadata.last_validated_at.isoformat()
                if metadata.last_validated_at
                else ""
            ),
            "last_error": last_error,
            "cookie": cookie if status == "valid" else {},
        }


def is_worker_cookie_stale(
    worker_status: RuntimeStatus,
    metadata: CookieMetadata | None = None,
) -> bool:
    if metadata is None:
        metadata = CookieMetadata.query.filter_by(role="admin").first()
    if metadata is None or metadata.status != "valid":
        return False
    return int(worker_status.cookie_version or 0) < int(metadata.cookie_version or 0)

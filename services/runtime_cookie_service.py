from typing import Any

from db.models import CookieMetadata, RuntimeStatus
from services.cookie_service import CookieService


class RuntimeCookieService:
    @staticmethod
    def load_cookie_settings() -> dict[str, str]:
        settings = CookieService.load_settings()
        bilibili = settings.get("bilibili", {})
        return {
            "SESSDATA": bilibili.get("SESSDATA") or "",
            "bili_jct": bilibili.get("bili_jct") or "",
            "buvid3": bilibili.get("buvid3") or "",
        }

    @staticmethod
    def get_runtime_cookie_payload(role: str = "admin") -> dict[str, Any]:
        metadata = CookieMetadata.query.filter_by(role=role).first()
        if metadata is None:
            return {
                "status": "missing",
                "version": 0,
                "cookie": {},
            }

        cookie = RuntimeCookieService.load_cookie_settings()
        missing_keys = [
            key
            for key in ("SESSDATA", "bili_jct", "buvid3")
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

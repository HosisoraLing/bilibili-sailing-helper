import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import requests

from db.models import CookieMetadata, db, get_beijing_now
from services.bilibili_qr_service import (
    cookie_header_from_map,
    validate_cookie_header,
)
from services.cookie_service import CookieService


TV_REFRESH_URL = "https://passport.bilibili.com/x/passport-tv-login/token/refresh"
DEFAULT_REFRESH_THRESHOLD_DAYS = 10


@dataclass
class TvAuthPayload:
    mid: str
    access_token: str
    refresh_token: str
    raw_payload: dict[str, Any]
    cookie_map: dict[str, str]
    cookie_header: str
    sessdata_expires_at: datetime | None


def _json_text(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _client(http_client=None):
    return http_client or requests


def _token_value(payload: dict[str, Any], name: str) -> str:
    token_info = payload.get("token_info") or {}
    return str(payload.get(name) or token_info.get(name) or "").strip()


def _cookie_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    cookie_info = payload.get("cookie_info") or {}
    return list(cookie_info.get("cookies") or [])


def parse_tv_auth_payload(payload: dict[str, Any]) -> TvAuthPayload:
    access_token = _token_value(payload, "access_token")
    refresh_token = _token_value(payload, "refresh_token")
    if not access_token:
        raise ValueError("TV auth payload missing access_token")
    if not refresh_token:
        raise ValueError("TV auth payload missing refresh_token")

    cookie_map: dict[str, str] = {}
    sessdata_expires_at = None
    for item in _cookie_items(payload):
        name = str(item.get("name") or "").strip()
        value = str(item.get("value") or "")
        if not name:
            continue
        cookie_map[name] = value
        if name == "SESSDATA" and item.get("expires"):
            sessdata_expires_at = datetime.fromtimestamp(int(item["expires"]))

    if not cookie_map.get("SESSDATA"):
        raise ValueError("TV auth payload missing SESSDATA Cookie")

    mid = str(payload.get("mid") or cookie_map.get("DedeUserID") or "").strip()
    return TvAuthPayload(
        mid=mid,
        access_token=access_token,
        refresh_token=refresh_token,
        raw_payload=payload,
        cookie_map=cookie_map,
        cookie_header=cookie_header_from_map(cookie_map),
        sessdata_expires_at=sessdata_expires_at,
    )


def _metadata() -> CookieMetadata:
    metadata = CookieMetadata.query.filter_by(role="admin").first()
    if metadata is None:
        metadata = CookieMetadata(role="admin")
        db.session.add(metadata)
    return metadata


def _save_cookie_map(cookie_map: dict[str, str]) -> bool:
    settings = CookieService.load_settings()
    bilibili = settings.setdefault("bilibili", {})
    for key in ("SESSDATA", "bili_jct", "buvid3"):
        if key in cookie_map:
            bilibili[key] = cookie_map[key]
    return CookieService.save_settings(settings)


def tv_auth_status_payload(metadata: CookieMetadata | None = None) -> dict[str, Any]:
    if metadata is None:
        metadata = CookieMetadata.query.filter_by(role="admin").first()
    if metadata is None:
        return {
            "status": "missing",
            "has_refresh_token": False,
            "sessdata_expires_at": "",
            "last_refresh_at": "",
            "last_validated_at": "",
            "last_error": "",
            "next_action": "请扫码授权 B 站账号",
        }

    has_refresh_token = bool(metadata.tv_refresh_token)
    status = metadata.status or "unknown"
    next_action = "无需操作"
    if status == "rescan_required" or (status == "valid" and not has_refresh_token):
        status = "rescan_required"
        next_action = "请重新扫码授权 B 站账号"
    elif status != "valid":
        next_action = "检查授权状态并重新扫码"

    return {
        "status": status,
        "has_refresh_token": has_refresh_token,
        "sessdata_expires_at": (
            metadata.sessdata_expires_at.isoformat()
            if metadata.sessdata_expires_at
            else ""
        ),
        "last_refresh_at": (
            metadata.last_refresh_at.isoformat() if metadata.last_refresh_at else ""
        ),
        "last_validated_at": (
            metadata.last_validated_at.isoformat()
            if metadata.last_validated_at
            else ""
        ),
        "last_error": metadata.last_error or "",
        "next_action": next_action,
    }


def store_tv_auth_success(payload: dict[str, Any], http_client=None) -> dict[str, Any]:
    parsed = parse_tv_auth_payload(payload)
    validation = validate_cookie_header(parsed.cookie_header, http_client=http_client)
    metadata = _metadata()
    now = get_beijing_now()

    if not validation.get("valid"):
        metadata.status = "invalid"
        metadata.source = "tv_auth"
        metadata.tv_access_token = ""
        metadata.tv_refresh_token = ""
        metadata.last_validated_at = now
        metadata.last_error = validation.get("message") or "Cookie 未登录或已失效"
        db.session.commit()
        return {"tv_auth": tv_auth_status_payload(metadata)}

    if not _save_cookie_map(parsed.cookie_map):
        metadata.status = "invalid"
        metadata.source = "tv_auth"
        metadata.last_validated_at = now
        metadata.last_error = "Cookie 保存失败"
        db.session.commit()
        return {"tv_auth": tv_auth_status_payload(metadata)}

    metadata.status = "valid"
    metadata.source = "tv_auth"
    metadata.masked_uid = validation.get("mid") or parsed.mid
    metadata.payload_json = _json_text(validation.get("payload") or {})
    metadata.tv_auth_payload_json = _json_text(parsed.raw_payload)
    metadata.tv_access_token = parsed.access_token
    metadata.tv_refresh_token = parsed.refresh_token
    metadata.sessdata_expires_at = parsed.sessdata_expires_at
    metadata.last_refresh_at = now
    metadata.last_validated_at = now
    metadata.last_error = ""
    metadata.cookie_version = int(metadata.cookie_version or 0) + 1
    db.session.commit()
    return {"tv_auth": tv_auth_status_payload(metadata)}


def refresh_tv_auth(metadata: CookieMetadata, http_client=None) -> dict[str, Any]:
    if not metadata.tv_access_token or not metadata.tv_refresh_token:
        raise RuntimeError("请重新扫码授权 B 站账号")
    response = _client(http_client).post(
        TV_REFRESH_URL,
        data={
            "access_token": metadata.tv_access_token,
            "refresh_token": metadata.tv_refresh_token,
        },
        timeout=10,
    )
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(payload.get("message") or "TV 授权刷新失败")
    data = payload.get("data") or payload
    if data.get("token_info"):
        data = {**data, **data.get("token_info", {})}
    return data


def sessdata_needs_refresh(
    metadata: CookieMetadata,
    threshold_days: int = DEFAULT_REFRESH_THRESHOLD_DAYS,
) -> bool:
    if not metadata.sessdata_expires_at:
        return True
    return metadata.sessdata_expires_at - get_beijing_now() <= timedelta(days=threshold_days)

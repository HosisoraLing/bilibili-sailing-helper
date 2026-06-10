import json
import hashlib
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import requests

from db.models import CookieMetadata, QrLoginTask, db, get_beijing_now
from services.bilibili_qr_service import (
    cookie_header_from_map,
    validate_cookie_header,
)
from services.cookie_service import CookieService


TV_APPKEY = "4409e2ce8ffd12b8"
TV_SECRET_KEY = "59b43e04ad6965f34319062b478f83dd"
TV_REFRESH_URL = "https://passport.bilibili.com/api/v2/oauth2/refresh_token"
TV_QR_BEGIN_URL = "http://passport.bilibili.com/x/passport-tv-login/qrcode/auth_code"
TV_QR_POLL_URL = "http://passport.bilibili.com/x/passport-tv-login/qrcode/poll"
DEFAULT_REFRESH_THRESHOLD_DAYS = 10
TV_FORM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/119.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/x-www-form-urlencoded",
    "cookie": "",
    "host": "passport.bilibili.com",
}


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


def _tv_timestamp() -> int:
    return int(time.time())


def _tv_sign(params: dict[str, Any]) -> str:
    sign_base = "&".join(f"{key}={params[key]}" for key in params)
    return hashlib.md5(f"{sign_base}{TV_SECRET_KEY}".encode()).hexdigest()


def _tv_qr_begin_params() -> dict[str, Any]:
    signed = {
        "appkey": TV_APPKEY,
        "local_id": "0",
        "ts": _tv_timestamp(),
    }
    signed["sign"] = _tv_sign(signed)
    return signed


def _tv_qr_poll_params(auth_code: str) -> dict[str, Any]:
    signed = {
        "appkey": TV_APPKEY,
        "auth_code": auth_code,
        "local_id": "0",
        "ts": _tv_timestamp(),
    }
    signed["sign"] = _tv_sign(signed)
    return signed


def _tv_refresh_params(access_key: str, refresh_token: str) -> dict[str, Any]:
    signed = {
        "access_key": access_key,
        "appkey": TV_APPKEY,
        "refresh_token": refresh_token,
        "ts": _tv_timestamp(),
    }
    signed["sign"] = _tv_sign(signed)
    return signed


def _task_payload(task: QrLoginTask, **extra) -> dict[str, Any]:
    payload = {
        "task_id": task.task_id,
        "status": task.status,
        "qrcode_key": task.qrcode_key,
        "qr_url": task.qr_url,
        "message": task.error_message or "",
    }
    payload.update(extra)
    return payload


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
    if (
        metadata is None
        or (
            metadata.source != "tv_auth"
            and not metadata.tv_access_token
            and not metadata.tv_refresh_token
        )
    ):
        return {
            "status": "missing",
            "has_refresh_token": False,
            "masked_uid": "",
            "source": "",
            "cookie_version": 0,
            "reload_requested_version": 0,
            "reload_requested_at": "",
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
        "masked_uid": metadata.masked_uid or "",
        "source": metadata.source or "",
        "cookie_version": int(metadata.cookie_version or 0),
        "reload_requested_version": int(metadata.reload_requested_version or 0),
        "reload_requested_at": (
            metadata.reload_requested_at.isoformat()
            if metadata.reload_requested_at
            else ""
        ),
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
    metadata.reload_requested_version = int(metadata.cookie_version or 0)
    metadata.reload_requested_at = now
    db.session.commit()
    return {"tv_auth": tv_auth_status_payload(metadata)}


def start_tv_qr_login(http_client=None, role: str = "admin") -> dict[str, Any]:
    response = _client(http_client).post(
        TV_QR_BEGIN_URL,
        data=_tv_qr_begin_params(),
        headers=TV_FORM_HEADERS,
        timeout=10,
    )
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(payload.get("message") or "TV 二维码生成失败")

    data = payload.get("data") or {}
    qr_url = data.get("url") or data.get("qrcode_url") or ""
    auth_code = data.get("auth_code") or data.get("qrcode_key") or ""
    if not qr_url or not auth_code:
        raise RuntimeError("TV 二维码响应缺少 url 或 auth_code")

    task = QrLoginTask(
        task_id=str(uuid.uuid4()),
        role=f"{role}_tv",
        status="pending",
        qrcode_key=auth_code,
        qr_url=qr_url,
        payload_json=_json_text(payload),
        expires_at=get_beijing_now() + timedelta(minutes=5),
    )
    db.session.add(task)
    db.session.commit()
    return _task_payload(task, tv_auth=tv_auth_status_payload())


def poll_tv_qr_login(task_id: str, http_client=None) -> dict[str, Any]:
    task = QrLoginTask.query.filter_by(task_id=task_id).first()
    if task is None:
        raise ValueError("TV 二维码任务不存在")

    response = _client(http_client).post(
        TV_QR_POLL_URL,
        data=_tv_qr_poll_params(task.qrcode_key),
        headers=TV_FORM_HEADERS,
        timeout=10,
    )
    payload = response.json()

    status_code = payload.get("code")
    data = payload.get("data") or {}
    if status_code == 0 and "code" in data:
        status_code = data.get("code")

    if status_code == 0 and not data:
        task.status = "failed"
        task.error_message = "TV 二维码轮询响应缺少授权数据"
        task.payload_json = _json_text(payload)
        db.session.commit()
        return _task_payload(task, tv_auth=tv_auth_status_payload())

    if payload.get("code") not in {0, 86038, 86039, 86090, 86101}:
        task.status = "failed"
        task.error_message = payload.get("message") or "TV 二维码轮询失败"
        task.payload_json = _json_text(payload)
        db.session.commit()
        return _task_payload(task, tv_auth=tv_auth_status_payload())

    message = data.get("message") or payload.get("message") or ""
    task.payload_json = _json_text(payload)

    if status_code in {86039, 86101}:
        task.status = "pending"
        task.error_message = message
        db.session.commit()
        return _task_payload(task, tv_auth=tv_auth_status_payload())
    if status_code == 86090:
        task.status = "scanned"
        task.error_message = message
        db.session.commit()
        return _task_payload(task, tv_auth=tv_auth_status_payload())
    if status_code == 86038:
        task.status = "expired"
        task.error_message = message
        db.session.commit()
        return _task_payload(task, tv_auth=tv_auth_status_payload())
    if status_code not in {0, None}:
        task.status = "unknown"
        task.error_message = message or "未知 TV 二维码状态"
        db.session.commit()
        return _task_payload(task, tv_auth=tv_auth_status_payload())

    result = store_tv_auth_success(data, http_client=http_client)
    task.status = "succeeded" if result["tv_auth"]["status"] == "valid" else "failed"
    task.error_message = "" if task.status == "succeeded" else result["tv_auth"].get("last_error", "")
    task.completed_at = get_beijing_now() if task.status == "succeeded" else None
    db.session.commit()
    return _task_payload(task, **result)


def refresh_tv_auth(metadata: CookieMetadata, http_client=None) -> dict[str, Any]:
    if not metadata.tv_access_token or not metadata.tv_refresh_token:
        raise RuntimeError("请重新扫码授权 B 站账号")
    response = _client(http_client).post(
        TV_REFRESH_URL,
        data=_tv_refresh_params(metadata.tv_access_token, metadata.tv_refresh_token),
        headers=TV_FORM_HEADERS,
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

import json
import uuid
from io import BytesIO
from datetime import timedelta
from http.cookies import SimpleCookie
from typing import Any

import requests

from db.models import CookieMetadata, QrLoginTask, db, get_beijing_now
from services.cookie_service import CookieService
from utils.log_utils import get_logger

logger = get_logger(__name__)

QR_BEGIN_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"


def _client(http_client=None):
    return http_client or requests


def _json_text(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def parse_cookie_header(cookie_header: str) -> dict[str, str]:
    cookie = SimpleCookie()
    cookie.load(cookie_header or "")
    return {key: morsel.value for key, morsel in cookie.items()}


def cookie_header_from_map(cookie_map: dict[str, str]) -> str:
    return "; ".join(
        f"{key}={value}"
        for key, value in sorted(cookie_map.items())
        if key and value is not None
    )


def _response_cookie_map(response) -> dict[str, str]:
    cookies = getattr(response, "cookies", None)
    if not cookies:
        return {}
    if hasattr(cookies, "get_dict"):
        return cookies.get_dict()
    return dict(cookies)


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


def get_qr_login_task(task_id: str) -> QrLoginTask | None:
    return QrLoginTask.query.filter_by(task_id=task_id).first()


def render_qr_png(qr_url: str) -> bytes:
    import qrcode

    image = qrcode.make(qr_url)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def start_qr_login(http_client=None, role: str = "admin") -> dict[str, Any]:
    response = _client(http_client).get(QR_BEGIN_URL, timeout=10)
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(payload.get("message") or "二维码生成失败")

    data = payload.get("data") or {}
    qr_url = data.get("url") or ""
    qrcode_key = data.get("qrcode_key") or ""
    if not qr_url or not qrcode_key:
        raise RuntimeError("二维码响应缺少 url 或 qrcode_key")

    task = QrLoginTask(
        task_id=str(uuid.uuid4()),
        role=role,
        status="pending",
        qrcode_key=qrcode_key,
        qr_url=qr_url,
        payload_json=_json_text(payload),
        expires_at=get_beijing_now() + timedelta(minutes=5),
    )
    db.session.add(task)
    db.session.commit()
    return _task_payload(task)


def validate_cookie_header(cookie_header: str, http_client=None) -> dict[str, Any]:
    cookie_map = parse_cookie_header(cookie_header)
    sessdata = cookie_map.get("SESSDATA")
    if not sessdata:
        return {
            "valid": False,
            "status": "invalid",
            "message": "Cookie 缺少 SESSDATA",
            "cookie_map": cookie_map,
        }

    response = _client(http_client).get(
        NAV_URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Cookie": cookie_header,
        },
        timeout=10,
    )
    payload = response.json()
    data = payload.get("data") or {}
    if payload.get("code") == 0 and data.get("isLogin"):
        return {
            "valid": True,
            "status": "valid",
            "message": "ok",
            "username": data.get("uname") or "",
            "mid": str(data.get("mid") or cookie_map.get("DedeUserID") or ""),
            "cookie_map": cookie_map,
            "payload": payload,
        }
    return {
        "valid": False,
        "status": "invalid",
        "message": payload.get("message") or "Cookie 未登录或已失效",
        "cookie_map": cookie_map,
        "payload": payload,
    }


def _upsert_cookie_metadata(validation: dict[str, Any], source: str, error: str = ""):
    metadata = CookieMetadata.query.filter_by(role="admin").first()
    is_new = metadata is None
    if metadata is None:
        metadata = CookieMetadata(role="admin")
        db.session.add(metadata)
    metadata.status = "valid" if validation.get("valid") else "invalid"
    metadata.source = source
    metadata.masked_uid = validation.get("mid") or ""
    metadata.payload_json = _json_text(validation.get("payload") or {})
    now = get_beijing_now()
    metadata.last_validated_at = now
    metadata.last_error = error or ("" if validation.get("valid") else validation.get("message") or "")
    if validation.get("valid"):
        metadata.cookie_version = int(metadata.cookie_version or 0) + 1
        metadata.reload_requested_version = int(metadata.cookie_version or 0)
        metadata.reload_requested_at = now
    elif is_new and metadata.cookie_version is None:
        metadata.cookie_version = 0
    return metadata


def _save_validated_cookie(cookie_map: dict[str, str]) -> bool:
    settings = CookieService.load_settings()
    bilibili = settings.setdefault("bilibili", {})
    if "SESSDATA" in cookie_map:
        bilibili["SESSDATA"] = cookie_map["SESSDATA"]
    if "bili_jct" in cookie_map:
        bilibili["bili_jct"] = cookie_map["bili_jct"]
    if "buvid3" in cookie_map:
        bilibili["buvid3"] = cookie_map["buvid3"]
    return CookieService.save_settings(settings)


def poll_qr_login(task_id: str, http_client=None) -> dict[str, Any]:
    task = QrLoginTask.query.filter_by(task_id=task_id).first()
    if task is None:
        raise ValueError("二维码任务不存在")

    response = _client(http_client).get(
        QR_POLL_URL,
        params={"qrcode_key": task.qrcode_key},
        timeout=10,
    )
    payload = response.json()
    if payload.get("code") != 0:
        task.status = "failed"
        task.error_message = payload.get("message") or "二维码轮询失败"
        task.payload_json = _json_text(payload)
        db.session.commit()
        return _task_payload(task)

    data = payload.get("data") or {}
    status_code = data.get("code")
    message = data.get("message") or ""
    task.payload_json = _json_text(payload)

    if status_code == 86101:
        task.status = "pending"
        task.error_message = message
        db.session.commit()
        return _task_payload(task)
    if status_code == 86090:
        task.status = "scanned"
        task.error_message = message
        db.session.commit()
        return _task_payload(task)
    if status_code == 86038:
        task.status = "expired"
        task.error_message = message
        db.session.commit()
        return _task_payload(task)
    if status_code != 0:
        task.status = "unknown"
        task.error_message = message or "未知二维码状态"
        db.session.commit()
        return _task_payload(task)

    cookie_map = _response_cookie_map(response)
    cookie_header = cookie_header_from_map(cookie_map)
    validation = validate_cookie_header(cookie_header, http_client=http_client)

    if not validation["valid"]:
        _upsert_cookie_metadata(validation, source="qr_login")
        task.status = "failed"
        task.error_message = validation["message"]
        db.session.commit()
        return _task_payload(task, username="")

    if not _save_validated_cookie(validation["cookie_map"]):
        _upsert_cookie_metadata(
            {**validation, "valid": False, "status": "invalid"},
            source="qr_login",
            error="Cookie 保存失败",
        )
        task.status = "failed"
        task.error_message = "Cookie 保存失败"
        db.session.commit()
        return _task_payload(task, username=validation.get("username") or "")

    _upsert_cookie_metadata(validation, source="qr_login")
    task.status = "succeeded"
    task.error_message = ""
    task.completed_at = get_beijing_now()
    db.session.commit()
    return _task_payload(task, username=validation.get("username") or "")

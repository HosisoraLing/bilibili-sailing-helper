import json
import re
import time
import uuid
import binascii
from io import BytesIO
from datetime import timedelta
from http.cookies import SimpleCookie
from typing import Any

import requests

from db.models import CookieMetadata, QrLoginTask, db, get_beijing_now
from services.bilibili_live.api import DEFAULT_USER_AGENT
from services.cookie_service import CookieService
from utils.log_utils import get_logger

logger = get_logger(__name__)


class WebCookieRefreshRejected(RuntimeError):
    pass


QR_BEGIN_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
COOKIE_INFO_URL = "https://passport.bilibili.com/x/passport-login/web/cookie/info"
CORRESPOND_URL = "https://www.bilibili.com/correspond/1/{correspond_path}"
COOKIE_REFRESH_URL = "https://passport.bilibili.com/x/passport-login/web/cookie/refresh"
CONFIRM_REFRESH_URL = "https://passport.bilibili.com/x/passport-login/web/confirm/refresh"
CORRESPOND_PUBLIC_KEY = """\
-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDLgd2OAkcGVtoE3ThUREbio0Eg
Uc/prcajMKXvkCKFCWhJYJcLkcM2DKKcSeFpD/j6Boy538YXnR6VhcuUJOhH2x71
nzPjfdTcqMz7djHum0qSZA0AyCBDABUqCrfNgCiJ00Ra7GmRj+YCK1NJEuewlb40
JNrRuoEUXpabUzGB8QIDAQAB
-----END PUBLIC KEY-----"""
BROWSER_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": "https://www.bilibili.com",
    "Referer": "https://www.bilibili.com/",
}


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


def cookie_map_from_metadata(metadata: CookieMetadata | None) -> dict[str, str]:
    if metadata and metadata.cookie_header:
        return parse_cookie_header(metadata.cookie_header)
    return {}


def _json_payload(response, operation: str) -> dict[str, Any]:
    try:
        return response.json()
    except ValueError as exc:
        status = getattr(response, "status_code", "")
        status_text = f"HTTP {status}" if status else "HTTP 响应"
        text = str(getattr(response, "text", "") or "").strip().replace("\n", " ")
        if len(text) > 120:
            text = text[:120] + "..."
        detail = f": {text}" if text else ""
        raise RuntimeError(f"{operation}返回非 JSON 响应（{status_text}）{detail}") from exc


def _is_success_code(value: Any) -> bool:
    return str(value) == "0"


def generate_correspond_path(timestamp_ms: int | None = None) -> str:
    from Crypto.Cipher import PKCS1_OAEP
    from Crypto.Hash import SHA256
    from Crypto.PublicKey import RSA

    timestamp_ms = timestamp_ms or round(time.time() * 1000)
    key = RSA.importKey(CORRESPOND_PUBLIC_KEY)
    cipher = PKCS1_OAEP.new(key, SHA256)
    encrypted = cipher.encrypt(f"refresh_{timestamp_ms}".encode())
    return binascii.b2a_hex(encrypted).decode()


def check_web_cookie_refresh_needed(cookie_map: dict[str, str], http_client=None) -> dict[str, Any]:
    cookie_header = cookie_header_from_map(cookie_map)
    response = _client(http_client).get(
        COOKIE_INFO_URL,
        params={"csrf": cookie_map.get("bili_jct") or ""},
        headers={
            **BROWSER_HEADERS,
            "Cookie": cookie_header,
        },
        timeout=10,
    )
    payload = _json_payload(response, "B 站 Cookie 刷新检查接口")
    if not _is_success_code(payload.get("code")):
        raise RuntimeError(payload.get("message") or "Cookie 刷新检查失败")
    data = payload.get("data") or {}
    return {
        "refresh": bool(data.get("refresh")),
        "timestamp": int(data.get("timestamp") or 0),
        "payload": payload,
    }


def get_refresh_csrf(cookie_map: dict[str, str], timestamp_ms: int, http_client=None) -> str:
    correspond_path = generate_correspond_path(timestamp_ms)
    response = _client(http_client).get(
        CORRESPOND_URL.format(correspond_path=correspond_path),
        headers={
            **BROWSER_HEADERS,
            "Cookie": cookie_header_from_map(cookie_map),
        },
        timeout=10,
    )
    status = getattr(response, "status_code", 200)
    if status == 404:
        raise RuntimeError("correspondPath 过期或错误")
    text = getattr(response, "text", "") or ""
    match = re.search(r'<div id="1-name">([^<]+)</div>', text)
    if not match:
        raise RuntimeError("获取 refresh_csrf 失败")
    return match.group(1)


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
    response = _client(http_client).get(QR_BEGIN_URL, headers=BROWSER_HEADERS, timeout=10)
    payload = _json_payload(response, "B 站二维码生成接口")
    if not _is_success_code(payload.get("code")):
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
            **BROWSER_HEADERS,
            "Cookie": cookie_header,
        },
        timeout=10,
    )
    payload = _json_payload(response, "B 站 Cookie 验证接口")
    data = payload.get("data") or {}
    if _is_success_code(payload.get("code")) and data.get("isLogin"):
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


def _upsert_cookie_metadata(
    validation: dict[str, Any],
    source: str,
    error: str = "",
    web_refresh_token: str = "",
):
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
        metadata.cookie_header = cookie_header_from_map(validation.get("cookie_map") or {})
        metadata.web_refresh_token = web_refresh_token or metadata.web_refresh_token or ""
        metadata.cookie_version = int(metadata.cookie_version or 0) + 1
        metadata.reload_requested_version = int(metadata.cookie_version or 0)
        metadata.reload_requested_at = now
    elif is_new and metadata.cookie_version is None:
        metadata.cookie_version = 0
    return metadata


def _sync_validated_cookie_settings(cookie_map: dict[str, str]) -> bool:
    try:
        settings = CookieService.load_settings()
        metadata = CookieMetadata.query.filter_by(role="admin").first()
        settings["bilibili_auth_mirror"] = {
            "source": "db.cookie_metadata",
            "role": getattr(metadata, "role", "admin") or "admin",
            "status": getattr(metadata, "status", "") or "",
            "cookie_version": int(getattr(metadata, "cookie_version", 0) or 0),
            "cookie_header": cookie_header_from_map(cookie_map),
            "has_web_refresh_token": bool(getattr(metadata, "web_refresh_token", "") or ""),
            "masked_uid": getattr(metadata, "masked_uid", "") or "",
            "updated_at": get_beijing_now().isoformat(),
        }
        return CookieService.save_settings(settings)
    except Exception as exc:
        logger.warning("Failed to sync Bilibili Cookie to legacy settings: %s", exc)
        return False


def refresh_web_qr_cookie(
    metadata: CookieMetadata,
    http_client=None,
    force: bool = False,
) -> dict[str, Any]:
    if not metadata.web_refresh_token:
        raise RuntimeError("当前账号没有 Web refresh token，请重新扫码授权 B 站账号")

    cookie_map = cookie_map_from_metadata(metadata)
    if not cookie_map.get("SESSDATA"):
        raise RuntimeError("当前 Cookie 缺少 SESSDATA，请重新扫码授权 B 站账号")
    if not cookie_map.get("bili_jct"):
        raise RuntimeError("当前 Cookie 缺少 bili_jct，请重新扫码授权 B 站账号")

    check = check_web_cookie_refresh_needed(cookie_map, http_client=http_client)
    if not metadata.cookie_header:
        metadata.cookie_header = cookie_header_from_map(cookie_map)
    metadata.payload_json = _json_text(check.get("payload") or {})
    metadata.last_validated_at = get_beijing_now()
    if not force and not check["refresh"]:
        metadata.status = "valid"
        metadata.last_error = ""
        db.session.commit()
        return {
            "status": "success",
            "action": "noop",
            "summary": "cookie-maintenance noop: Web Cookie does not need refresh",
            "next_action": "无需操作",
        }

    old_refresh_token = metadata.web_refresh_token
    refresh_csrf = get_refresh_csrf(
        cookie_map,
        check["timestamp"] or round(time.time() * 1000),
        http_client=http_client,
    )
    refresh_response = _client(http_client).post(
        COOKIE_REFRESH_URL,
        data={
            "csrf": cookie_map["bili_jct"],
            "refresh_csrf": refresh_csrf,
            "source": "main_web",
            "refresh_token": old_refresh_token,
        },
        headers={
            **BROWSER_HEADERS,
            "Cookie": cookie_header_from_map(cookie_map),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=10,
    )
    refresh_payload = _json_payload(refresh_response, "B 站 Cookie 刷新接口")
    if not _is_success_code(refresh_payload.get("code")):
        raise WebCookieRefreshRejected(refresh_payload.get("message") or "Web Cookie 刷新失败")
    new_refresh_token = str((refresh_payload.get("data") or {}).get("refresh_token") or "").strip()
    if not new_refresh_token:
        raise RuntimeError("Web Cookie 刷新响应缺少 refresh_token")

    new_cookie_map = {**cookie_map, **_response_cookie_map(refresh_response)}
    validation = validate_cookie_header(cookie_header_from_map(new_cookie_map), http_client=http_client)
    if not validation["valid"]:
        raise RuntimeError(validation.get("message") or "刷新后的 Cookie 未登录或已失效")

    confirm_response = _client(http_client).post(
        CONFIRM_REFRESH_URL,
        data={
            "csrf": validation["cookie_map"].get("bili_jct") or new_cookie_map.get("bili_jct") or "",
            "refresh_token": old_refresh_token,
        },
        headers={
            **BROWSER_HEADERS,
            "Cookie": cookie_header_from_map(validation["cookie_map"]),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=10,
    )
    confirm_payload = _json_payload(confirm_response, "B 站 Cookie 刷新确认接口")
    if not _is_success_code(confirm_payload.get("code")):
        raise RuntimeError(confirm_payload.get("message") or "Web Cookie 刷新确认失败")

    refreshed_metadata = _upsert_cookie_metadata(
        validation,
        source="qr_login",
        web_refresh_token=new_refresh_token,
    )
    refreshed_metadata.last_refresh_at = get_beijing_now()
    settings_synced = _sync_validated_cookie_settings(validation["cookie_map"])
    db.session.commit()
    return {
        "status": "success",
        "action": "refreshed",
        "summary": "cookie-maintenance refreshed Web QR Cookie",
        "next_action": "无需操作",
        "settings_synced": settings_synced,
    }


def poll_qr_login(task_id: str, http_client=None) -> dict[str, Any]:
    task = QrLoginTask.query.filter_by(task_id=task_id).first()
    if task is None:
        raise ValueError("二维码任务不存在")

    response = _client(http_client).get(
        QR_POLL_URL,
        params={"qrcode_key": task.qrcode_key},
        headers=BROWSER_HEADERS,
        timeout=10,
    )
    payload = _json_payload(response, "B 站二维码轮询接口")
    if not _is_success_code(payload.get("code")):
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

    refresh_token = str(data.get("refresh_token") or "").strip()
    cookie_map = _response_cookie_map(response)
    cookie_header = cookie_header_from_map(cookie_map)
    validation = validate_cookie_header(cookie_header, http_client=http_client)

    if not validation["valid"]:
        _upsert_cookie_metadata(validation, source="qr_login")
        task.status = "failed"
        task.error_message = validation["message"]
        db.session.commit()
        return _task_payload(task, username="")

    _upsert_cookie_metadata(validation, source="qr_login", web_refresh_token=refresh_token)
    _sync_validated_cookie_settings(validation["cookie_map"])
    task.status = "succeeded"
    task.error_message = ""
    task.completed_at = get_beijing_now()
    db.session.commit()
    return _task_payload(task, username=validation.get("username") or "")

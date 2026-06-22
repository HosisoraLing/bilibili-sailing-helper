#!/usr/bin/env python3
"""Probe Bilibili Web QR login and cookie refresh with raw audit logs.

This script is intentionally standalone. It does not import the Flask app, read
settings.json, or mutate the application database. All artifacts are written
under scripts/web-refresh-probe/<timestamp>/ by default.
"""
from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import re
import sys
import time
from datetime import datetime
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_ROOT = SCRIPT_DIR / "web-refresh-probe"

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
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": "https://www.bilibili.com",
    "Referer": "https://www.bilibili.com/",
}


class ProbeFailure(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


def sha256_prefix(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def raw_json(value: Any) -> Any:
    return value


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


def response_cookie_map(response: requests.Response) -> dict[str, str]:
    return response.cookies.get_dict() if response.cookies else {}


def raw_cookie_map(cookie_map: dict[str, str]) -> dict[str, Any]:
    return dict(sorted(cookie_map.items()))


def raw_headers(headers: requests.structures.CaseInsensitiveDict[str]) -> dict[str, Any]:
    return dict(headers.items())


def response_snapshot(response: requests.Response) -> dict[str, Any]:
    try:
        payload: Any = response.json()
    except ValueError:
        text = response.text or ""
        payload = {
            "non_json_text": text,
            "non_json_text_length": len(text),
            "non_json_text_sha256_prefix": sha256_prefix(text) if text else "",
        }
    return {
        "url": response.url,
        "status_code": response.status_code,
        "elapsed_ms": round(response.elapsed.total_seconds() * 1000),
        "headers": raw_headers(response.headers),
        "cookies": raw_cookie_map(response_cookie_map(response)),
        "json": raw_json(payload),
    }


def is_success_code(value: Any) -> bool:
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


class ProbeLogger:
    def __init__(self, output_dir: Path, verbose: bool):
        self.output_dir = output_dir
        self.verbose = verbose
        self.events_path = output_dir / "events.jsonl"
        self.summary: dict[str, Any] = {
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "output_dir": str(output_dir),
            "steps": {},
            "final_status": "running",
        }

    def event(self, name: str, data: dict[str, Any] | None = None):
        record = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "event": name,
            "data": raw_json(data or {}),
        }
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        if self.verbose:
            print(f"[{record['time']}] {name}: {json.dumps(record['data'], ensure_ascii=False)}")
        else:
            print(f"[{record['time']}] {name}")

    def write_summary(self):
        with (self.output_dir / "summary.json").open("w", encoding="utf-8") as f:
            json.dump(self.summary, f, ensure_ascii=False, indent=2, sort_keys=True)

    def step(self, name: str, data: dict[str, Any]):
        self.summary["steps"][name] = raw_json(data)
        self.event(name, data)
        self.write_summary()

    def finish(self, final_status: str, exit_code: int):
        self.summary["final_status"] = final_status
        self.summary["exit_code"] = exit_code
        self.summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
        self.write_summary()


def append_failure(output_dir: Path, message: str, exit_code: int):
    output_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "event": "probe.failure",
        "data": raw_json({"message": message, "exit_code": exit_code}),
    }
    with (output_dir / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    summary_path = output_dir / "summary.json"
    if summary_path.exists():
        with summary_path.open("r", encoding="utf-8") as f:
            summary = json.load(f)
    else:
        summary = {
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "output_dir": str(output_dir),
            "steps": {},
        }
    summary["final_status"] = "failed"
    summary["exit_code"] = exit_code
    summary["failure"] = raw_json({"message": message})
    summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, sort_keys=True)


def write_qr_png(qr_url: str, output_dir: Path) -> Path | None:
    try:
        import qrcode
    except ImportError:
        return None
    path = output_dir / "qr.png"
    image = qrcode.make(qr_url)
    image.save(path)
    return path


def print_terminal_qr(qr_url: str):
    try:
        import qrcode
    except ImportError:
        return
    qr = qrcode.QRCode(border=1)
    qr.add_data(qr_url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


def json_payload(response: requests.Response, operation: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProbeFailure(f"{operation} 返回非 JSON：HTTP {response.status_code}") from exc
    if not isinstance(payload, dict):
        raise ProbeFailure(f"{operation} 返回 JSON 不是对象")
    return payload


def request_with_log(
    session: requests.Session,
    logger: ProbeLogger,
    event_name: str,
    method: str,
    url: str,
    **kwargs: Any,
) -> tuple[requests.Response, dict[str, Any]]:
    started = time.time()
    logger.event(
        f"{event_name}.request",
        {
            "method": method.upper(),
            "url": url,
            "params": kwargs.get("params") or {},
            "data": kwargs.get("data") or {},
            "headers": kwargs.get("headers") or {},
        },
    )
    response = session.request(method, url, **kwargs)
    snapshot = response_snapshot(response)
    snapshot["duration_ms"] = round((time.time() - started) * 1000)
    logger.event(f"{event_name}.response", snapshot)
    return response, snapshot


def require_success_payload(payload: dict[str, Any], operation: str):
    if not is_success_code(payload.get("code")):
        raise ProbeFailure(f"{operation} 失败：code={payload.get('code')} message={payload.get('message')}")


def validate_cookie(
    session: requests.Session,
    logger: ProbeLogger,
    cookie_map: dict[str, str],
    name: str,
    timeout: int,
) -> dict[str, Any]:
    response, snapshot = request_with_log(
        session,
        logger,
        f"{name}.nav",
        "GET",
        NAV_URL,
        headers={**BROWSER_HEADERS, "Cookie": cookie_header_from_map(cookie_map)},
        timeout=timeout,
    )
    payload = json_payload(response, "Cookie 验证接口")
    data = payload.get("data") or {}
    result = {
        "http_status": response.status_code,
        "code": payload.get("code"),
        "message": payload.get("message"),
        "is_login": bool(data.get("isLogin")),
        "mid": str(data.get("mid") or cookie_map.get("DedeUserID") or ""),
            "uname": data.get("uname") or "",
            "snapshot": snapshot,
        }
    logger.step(f"{name}.validation", result)
    return result


def get_refresh_csrf(
    session: requests.Session,
    logger: ProbeLogger,
    cookie_map: dict[str, str],
    timestamp_ms: int,
    timeout: int,
) -> str:
    correspond_path = generate_correspond_path(timestamp_ms)
    response, snapshot = request_with_log(
        session,
        logger,
        "correspond",
        "GET",
        CORRESPOND_URL.format(correspond_path=correspond_path),
        headers={**BROWSER_HEADERS, "Cookie": cookie_header_from_map(cookie_map)},
        timeout=timeout,
    )
    text = response.text or ""
    match = re.search(r'<div id="1-name">([^<]+)</div>', text)
    result = {
        "http_status": response.status_code,
        "html_length": len(text),
        "refresh_csrf_found": bool(match),
        "correspond_path": correspond_path,
        "snapshot": snapshot,
    }
    logger.step("correspond.parse", result)
    if response.status_code == 404:
        raise ProbeFailure("correspondPath 过期或错误")
    if not match:
        raise ProbeFailure("获取 refresh_csrf 失败")
    return match.group(1)


def run_probe(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = ProbeLogger(output_dir, verbose=args.verbose)
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)

    logger.event(
        "probe.start",
        {
            "output_dir": str(output_dir),
            "timeout": args.timeout,
            "poll_interval": args.poll_interval,
            "poll_timeout": args.poll_timeout,
            "force_refresh": True,
        },
    )

    response, _ = request_with_log(
        session,
        logger,
        "qr.generate",
        "GET",
        QR_BEGIN_URL,
        timeout=args.timeout,
    )
    payload = json_payload(response, "二维码生成接口")
    require_success_payload(payload, "二维码生成接口")
    data = payload.get("data") or {}
    qr_url = data.get("url") or ""
    qrcode_key = data.get("qrcode_key") or ""
    if not qr_url or not qrcode_key:
        raise ProbeFailure("二维码生成响应缺少 url 或 qrcode_key")

    qr_png_path = write_qr_png(qr_url, output_dir)
    logger.step(
        "qr.ready",
        {
            "qr_url": qr_url,
            "qrcode_key": qrcode_key,
            "qr_png_path": str(qr_png_path) if qr_png_path else "",
        },
    )
    print("\n扫码地址:")
    print(qr_url)
    if qr_png_path:
        print(f"二维码 PNG: {qr_png_path}")
    if args.terminal_qr:
        print_terminal_qr(qr_url)

    deadline = time.time() + args.poll_timeout
    poll_payload: dict[str, Any] | None = None
    poll_response: requests.Response | None = None
    while time.time() < deadline:
        poll_response, _ = request_with_log(
            session,
            logger,
            "qr.poll",
            "GET",
            QR_POLL_URL,
            params={"qrcode_key": qrcode_key},
            timeout=args.timeout,
        )
        poll_payload = json_payload(poll_response, "二维码轮询接口")
        require_success_payload(poll_payload, "二维码轮询接口")
        poll_data = poll_payload.get("data") or {}
        poll_code = poll_data.get("code")
        logger.step(
            "qr.poll_state",
            {
                "code": poll_code,
                "message": poll_data.get("message") or "",
            },
        )
        if poll_code == 0:
            break
        if poll_code == 86038:
            raise ProbeFailure("二维码已过期")
        time.sleep(args.poll_interval)

    if not poll_payload or not poll_response:
        raise ProbeFailure("二维码轮询未完成")
    poll_data = poll_payload.get("data") or {}
    if poll_data.get("code") != 0:
        raise ProbeFailure(f"扫码未成功：code={poll_data.get('code')} message={poll_data.get('message')}")

    old_refresh_token = str(poll_data.get("refresh_token") or "").strip()
    cookie_map = response_cookie_map(poll_response)
    logger.step(
        "login.success",
        {
            "refresh_token_present": bool(old_refresh_token),
            "refresh_token": old_refresh_token,
            "cookie_keys": sorted(cookie_map.keys()),
            "cookies": raw_cookie_map(cookie_map),
        },
    )
    if not old_refresh_token:
        raise ProbeFailure("扫码成功但响应缺少 refresh_token")
    if not cookie_map.get("SESSDATA") or not cookie_map.get("bili_jct"):
        raise ProbeFailure("扫码成功但响应 Cookie 缺少 SESSDATA 或 bili_jct")

    validation = validate_cookie(session, logger, cookie_map, "original_cookie", args.timeout)
    if not validation.get("is_login"):
        raise ProbeFailure("扫码 Cookie nav 验证未登录")

    info_response, _ = request_with_log(
        session,
        logger,
        "cookie.info",
        "GET",
        COOKIE_INFO_URL,
        params={"csrf": cookie_map.get("bili_jct") or ""},
        headers={**BROWSER_HEADERS, "Cookie": cookie_header_from_map(cookie_map)},
        timeout=args.timeout,
    )
    info_payload = json_payload(info_response, "Cookie 刷新检查接口")
    require_success_payload(info_payload, "Cookie 刷新检查接口")
    info_data = info_payload.get("data") or {}
    timestamp_ms = int(info_data.get("timestamp") or round(time.time() * 1000))
    logger.step(
        "cookie.info.parsed",
        {
            "refresh": bool(info_data.get("refresh")),
            "timestamp": timestamp_ms,
            "timestamp_is_current_server_time": True,
        },
    )

    refresh_csrf = get_refresh_csrf(session, logger, cookie_map, timestamp_ms, args.timeout)
    refresh_response, _ = request_with_log(
        session,
        logger,
        "cookie.refresh",
        "POST",
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
        timeout=args.timeout,
    )
    refresh_payload = json_payload(refresh_response, "Cookie 刷新接口")
    refresh_ok = is_success_code(refresh_payload.get("code"))
    logger.step(
        "cookie.refresh.parsed",
        {
            "ok": refresh_ok,
            "code": refresh_payload.get("code"),
            "message": refresh_payload.get("message") or "",
            "new_cookie_keys": sorted(response_cookie_map(refresh_response).keys()),
            "new_refresh_token": str((refresh_payload.get("data") or {}).get("refresh_token") or ""),
        },
    )

    if not refresh_ok:
        fallback_validation = validate_cookie(session, logger, cookie_map, "original_cookie_after_refresh_failure", args.timeout)
        logger.finish(
            "refresh_failed_cookie_still_valid" if fallback_validation.get("is_login") else "refresh_failed_cookie_invalid",
            2,
        )
        return 2

    new_refresh_token = str((refresh_payload.get("data") or {}).get("refresh_token") or "").strip()
    if not new_refresh_token:
        raise ProbeFailure("刷新成功响应缺少新的 refresh_token")

    new_cookie_map = {**cookie_map, **response_cookie_map(refresh_response)}
    new_validation = validate_cookie(session, logger, new_cookie_map, "refreshed_cookie", args.timeout)
    if not new_validation.get("is_login"):
        raise ProbeFailure("刷新后的 Cookie nav 验证未登录")

    confirm_response, _ = request_with_log(
        session,
        logger,
        "cookie.confirm_refresh",
        "POST",
        CONFIRM_REFRESH_URL,
        data={
            "csrf": new_cookie_map.get("bili_jct") or "",
            "refresh_token": old_refresh_token,
        },
        headers={
            **BROWSER_HEADERS,
            "Cookie": cookie_header_from_map(new_cookie_map),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=args.timeout,
    )
    confirm_payload = json_payload(confirm_response, "Cookie 刷新确认接口")
    confirm_ok = is_success_code(confirm_payload.get("code"))
    logger.step(
        "cookie.confirm_refresh.parsed",
        {
            "ok": confirm_ok,
            "code": confirm_payload.get("code"),
            "message": confirm_payload.get("message") or "",
        },
    )
    if not confirm_ok:
        raise ProbeFailure(
            f"刷新确认失败：code={confirm_payload.get('code')} message={confirm_payload.get('message')}"
        )

    logger.finish("refresh_confirmed", 0)
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Standalone probe for Bilibili Web QR login and forced Cookie refresh. "
            "Exit 0 means refresh+confirm succeeded; exit 2 means login/validation "
            "worked but refresh was rejected by Bilibili and the response was logged; "
            "exit 1 means script/infrastructure failure."
        )
    )
    parser.add_argument("--output-dir", help="Artifact directory. Defaults to scripts/web-refresh-probe/<timestamp>.")
    parser.add_argument("--timeout", type=int, default=15, help="HTTP timeout in seconds. Default: 15.")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="QR poll interval in seconds. Default: 2.")
    parser.add_argument("--poll-timeout", type=int, default=180, help="QR scan timeout in seconds. Default: 180.")
    parser.add_argument("--terminal-qr", action="store_true", help="Also print a terminal QR code.")
    parser.add_argument("--verbose", action="store_true", help="Print raw event payloads while running.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if not args.output_dir:
        args.output_dir = str(DEFAULT_OUTPUT_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S"))
    output_dir = Path(args.output_dir).resolve()
    try:
        return run_probe(args)
    except ProbeFailure as exc:
        append_failure(output_dir, str(exc), exc.exit_code)
        print(f"失败: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130
    except Exception as exc:
        append_failure(output_dir, f"{type(exc).__name__}: {exc}", 1)
        print(f"失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

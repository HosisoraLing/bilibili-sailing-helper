import asyncio
import json
import os
import random
import time

import aiohttp

from config import ROOM_ID_INT
from services.bilibili_live.api import BilibiliApiError, BilibiliLiveApi, DANMU_INFO_URL
from services.bilibili_live.client import BilibiliLiveClient
from services.bilibili_live.cookies import RuntimeCookieProvider
from services.bilibili_live.events import normalize_danmaku_event
from services.bilibili_live.protocol import OP_MESSAGE, unpack_packets
from services.bilibili_live.webhook import InternalWebhookClient


class WorkerStop(Exception):
    pass


def json_dumps(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def cookie_header(cookie: dict[str, str]) -> str:
    return "; ".join(
        f"{key}={value}"
        for key, value in cookie.items()
        if value
    )


def generate_buvid3() -> str:
    chars = "0123456789ABCDEF"

    def rand(length: int) -> str:
        return "".join(random.choice(chars) for _ in range(length))

    suffix = f"{int(time.time() * 1000) % 100000:05d}infoc"
    return f"{rand(8)}-{rand(4)}-{rand(4)}-{rand(4)}-{rand(12)}{suffix}"


def runtime_live_cookie(cookie: dict[str, str]) -> dict[str, str]:
    live_cookie = dict(cookie)
    if not live_cookie.get("buvid3"):
        live_cookie["buvid3"] = generate_buvid3()
    return live_cookie


def is_bilibili_live_rejected(exc: Exception) -> bool:
    return (
        getattr(exc, "code", None) == -352
        or "-352" in str(exc)
    )


def safe_cookie_keys(cookie: dict[str, str]) -> list[str]:
    return sorted(key for key, value in cookie.items() if value)


def bilibili_error_payload(exc: Exception, cookie: dict[str, str] | None) -> dict:
    payload = {
        "bilibili_stage": "getDanmuInfo",
        "bilibili_api_url": DANMU_INFO_URL,
        "bilibili_error": str(exc),
        "cookie_keys": safe_cookie_keys(cookie or {}),
    }
    if isinstance(exc, BilibiliApiError):
        payload.update({
            "bilibili_code": exc.code,
            "bilibili_http_status": exc.http_status,
        })
    return payload


def default_cookie_poll_interval(environ=os.environ) -> float:
    raw = environ.get("DANMAKU_COOKIE_POLL_INTERVAL_SECONDS", "10")
    try:
        interval = float(raw)
    except (TypeError, ValueError):
        return 10.0
    return max(interval, 1.0)


async def default_websocket_factory(url: str):
    session = aiohttp.ClientSession()
    try:
        websocket = await session.ws_connect(url, heartbeat=30)
        setattr(websocket, "_bsh_session", session)
        return websocket
    except Exception:
        await session.close()
        raise


async def close_websocket(websocket):
    close = getattr(websocket, "close", None)
    if callable(close):
        result = close()
        if asyncio.iscoroutine(result):
            await result
    session = getattr(websocket, "_bsh_session", None)
    session_close = getattr(session, "close", None)
    if callable(session_close):
        result = session_close()
        if asyncio.iscoroutine(result):
            await result


async def handle_packet(raw: bytes, room_id: int, webhook: InternalWebhookClient):
    for packet in unpack_packets(raw):
        if packet.get("operation") != OP_MESSAGE:
            continue
        try:
            raw_event = json.loads(packet.get("body") or b"{}")
        except json.JSONDecodeError:
            continue
        event = normalize_danmaku_event(raw_event, room_id)
        if event:
            await webhook.enqueue_auth_event(event)
            await webhook.drain_once()


async def monitor_cookie_version(
    *,
    cookie_provider: RuntimeCookieProvider,
    current_version: int,
    websocket,
    webhook: InternalWebhookClient,
    instance_id: str,
    poll_interval: float,
    sleep=asyncio.sleep,
):
    while True:
        await sleep(poll_interval)
        try:
            latest = await cookie_provider.fetch_latest()
        except Exception as exc:
            await webhook.report_heartbeat(
                role="danmaku-worker",
                instance_id=instance_id,
                state="cookie_poll_error",
                last_error=str(exc),
            )
            continue
        if RuntimeCookieProvider.should_reload(current_version, latest):
            await webhook.report_heartbeat(
                role="danmaku-worker",
                instance_id=instance_id,
                state="cookie_reloading",
                cookie_version=latest.version,
            )
            await close_websocket(websocket)
            return


async def wait_for_new_cookie_version(
    *,
    cookie_provider: RuntimeCookieProvider,
    current_version: int,
    webhook: InternalWebhookClient,
    instance_id: str,
    poll_interval: float,
    sleep=asyncio.sleep,
):
    while True:
        await sleep(poll_interval)
        try:
            latest = await cookie_provider.fetch_latest()
        except Exception as exc:
            await webhook.report_heartbeat(
                role="danmaku-worker",
                instance_id=instance_id,
                state="cookie_poll_error",
                last_error=str(exc),
            )
            continue
        if RuntimeCookieProvider.should_reload(current_version, latest):
            await webhook.report_heartbeat(
                role="danmaku-worker",
                instance_id=instance_id,
                state="cookie_reloading",
                cookie_version=latest.version,
            )
            return


async def report_runtime_heartbeat(
    *,
    webhook: InternalWebhookClient,
    instance_id: str,
    cookie_version: int,
    interval: float,
    sleep=asyncio.sleep,
):
    while True:
        await sleep(interval)
        await webhook.report_heartbeat(
            role="danmaku-worker",
            instance_id=instance_id,
            state="running",
            cookie_version=cookie_version,
            retry_count=0,
            last_error="",
        )


async def run_connection(
    *,
    room_id: int,
    cookie,
    cookie_provider: RuntimeCookieProvider,
    webhook: InternalWebhookClient,
    api_factory=BilibiliLiveApi,
    websocket_factory=default_websocket_factory,
    instance_id: str,
    cookie_poll_interval: float = 10.0,
    sleep=asyncio.sleep,
):
    async with aiohttp.ClientSession() as session:
        live_cookie = runtime_live_cookie(cookie.cookie)
        api = api_factory(session, cookie_header=cookie_header(live_cookie))
        client = BilibiliLiveClient(
            room_id=room_id,
            buvid3=live_cookie.get("buvid3", ""),
            cookie_version=cookie.version,
        )
        info = await api.get_danmu_info(room_id)
        websocket = await websocket_factory(client._select_wss_host(info))
        await client.send_auth(websocket, token=info.get("token") or "")
        await webhook.report_heartbeat(
            role="danmaku-worker",
            instance_id=instance_id,
            state="running",
            cookie_version=cookie.version,
            retry_count=0,
            last_error="",
        )
        heartbeat_task = asyncio.create_task(client.heartbeat_loop(websocket))
        cookie_task = None
        if cookie_poll_interval > 0:
            cookie_task = asyncio.create_task(
                monitor_cookie_version(
                    cookie_provider=cookie_provider,
                    current_version=cookie.version,
                    websocket=websocket,
                    webhook=webhook,
                    instance_id=instance_id,
                    poll_interval=cookie_poll_interval,
                    sleep=sleep,
                )
            )
        try:
            if cookie_poll_interval <= 0:
                await monitor_cookie_version(
                    cookie_provider=cookie_provider,
                    current_version=cookie.version,
                    websocket=websocket,
                    webhook=webhook,
                    instance_id=instance_id,
                    poll_interval=cookie_poll_interval,
                    sleep=sleep,
                )
            else:
                async for message in websocket:
                    raw = getattr(message, "data", message)
                    if isinstance(raw, bytes):
                        await handle_packet(raw, room_id, webhook)
        finally:
            client.stop()
            await close_websocket(websocket)
            for task in (heartbeat_task, cookie_task):
                if task is None:
                    continue
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


async def run_worker_loop(
    *,
    room_id: int,
    cookie_provider: RuntimeCookieProvider,
    webhook: InternalWebhookClient,
    api_factory=BilibiliLiveApi,
    websocket_factory=default_websocket_factory,
    instance_id: str,
    reconnect_delay: float = 5.0,
    cookie_poll_interval: float = 10.0,
    idle_sleep=asyncio.sleep,
):
    current_version = 0
    current_cookie = {}
    while True:
        try:
            latest = await cookie_provider.fetch_latest()
            if latest.status != "valid":
                await webhook.report_heartbeat(
                    role="danmaku-worker",
                    instance_id=instance_id,
                    state="cookie_unavailable",
                    cookie_version=latest.version,
                )
                await idle_sleep(reconnect_delay)
                continue

            current_version = latest.version
            current_cookie = latest.cookie
            await run_connection(
                room_id=room_id,
                cookie=latest,
                cookie_provider=cookie_provider,
                webhook=webhook,
                api_factory=api_factory,
                websocket_factory=websocket_factory,
                instance_id=instance_id,
                cookie_poll_interval=cookie_poll_interval,
            )
            await idle_sleep(reconnect_delay)
        except WorkerStop:
            return
        except Exception as exc:
            if is_bilibili_live_rejected(exc):
                await webhook.report_heartbeat(
                    role="danmaku-worker",
                    instance_id=instance_id,
                    state="bilibili_rejected",
                    cookie_version=current_version,
                    last_error="B站直播接口返回 -352，请扫码授权其他账号",
                    **bilibili_error_payload(exc, current_cookie),
                )
                await wait_for_new_cookie_version(
                    cookie_provider=cookie_provider,
                    current_version=current_version,
                    webhook=webhook,
                    instance_id=instance_id,
                    poll_interval=reconnect_delay,
                    sleep=idle_sleep,
                )
                continue
            await webhook.report_heartbeat(
                role="danmaku-worker",
                instance_id=instance_id,
                state="reconnecting",
                cookie_version=current_version,
                last_error=str(exc),
            )
            await idle_sleep(reconnect_delay)


async def run():
    internal_url = os.environ.get("INTERNAL_API_URL", "http://web:7111")
    secret = os.environ.get("INTERNAL_API_SECRET", "")
    instance_id = os.environ.get("RUNTIME_INSTANCE_ID", "danmaku-worker")
    room_id = int(os.environ.get("BILIBILI_ROOM_ID") or ROOM_ID_INT)
    cookie_poll_interval = default_cookie_poll_interval()

    async with aiohttp.ClientSession() as session:
        cookie_provider = RuntimeCookieProvider(
            base_url=internal_url,
            secret=secret,
            session=session,
        )
        webhook = InternalWebhookClient(
            base_url=internal_url,
            secret=secret,
            session=session,
            instance_id=instance_id,
        )
        await run_worker_loop(
            room_id=room_id,
            cookie_provider=cookie_provider,
            webhook=webhook,
            instance_id=instance_id,
            cookie_poll_interval=cookie_poll_interval,
        )


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()

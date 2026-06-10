import asyncio
import json
import os

import aiohttp

from config import ROOM_ID_INT
from services.bilibili_live.api import BilibiliLiveApi
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


async def default_websocket_factory(url: str):
    session = aiohttp.ClientSession()
    try:
        return await session.ws_connect(url, heartbeat=30)
    except Exception:
        await session.close()
        raise


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


async def run_connection(
    *,
    room_id: int,
    cookie,
    webhook: InternalWebhookClient,
    api_factory=BilibiliLiveApi,
    websocket_factory=default_websocket_factory,
    instance_id: str,
):
    async with aiohttp.ClientSession() as session:
        api = api_factory(session, cookie_header=cookie_header(cookie.cookie))
        client = BilibiliLiveClient(
            room_id=room_id,
            buvid3=cookie.cookie.get("buvid3", ""),
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
        try:
            async for message in websocket:
                raw = getattr(message, "data", message)
                if isinstance(raw, bytes):
                    await handle_packet(raw, room_id, webhook)
        finally:
            client.stop()
            heartbeat_task.cancel()
            try:
                await heartbeat_task
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
    idle_sleep=asyncio.sleep,
):
    current_version = 0
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
            await run_connection(
                room_id=room_id,
                cookie=latest,
                webhook=webhook,
                api_factory=api_factory,
                websocket_factory=websocket_factory,
                instance_id=instance_id,
            )
            await idle_sleep(reconnect_delay)
        except WorkerStop:
            return
        except Exception as exc:
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
        )


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()

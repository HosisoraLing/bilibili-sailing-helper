import asyncio
from typing import Any

from services.bilibili_live.protocol import pack_auth, pack_heartbeat


class BilibiliLiveClient:
    def __init__(
        self,
        room_id: int | str,
        uid: int = 0,
        buvid3: str = "",
        cookie_version: int = 0,
        heartbeat_interval: float = 30.0,
    ):
        self.room_id = int(room_id)
        self.uid = int(uid or 0)
        self.buvid3 = buvid3
        self.cookie_version = int(cookie_version or 0)
        self.heartbeat_interval = heartbeat_interval
        self.running = False

    def auth_payload(self, token: str) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "roomid": self.room_id,
            "protover": 3,
            "buvid": self.buvid3,
            "platform": "web",
            "type": 2,
            "key": token,
        }

    async def send_auth(self, websocket, token: str):
        await websocket.send_bytes(pack_auth(self.auth_payload(token)))

    async def send_heartbeat(self, websocket):
        await websocket.send_bytes(pack_heartbeat())

    async def heartbeat_loop(self, websocket):
        self.running = True
        try:
            while self.running:
                await asyncio.sleep(self.heartbeat_interval)
                await self.send_heartbeat(websocket)
        except asyncio.CancelledError:
            self.running = False
            raise

    async def connect_with_retries(
        self,
        api,
        websocket_factory,
        webhook,
        instance_id: str,
        max_retries: int = 3,
        sleep=asyncio.sleep,
    ) -> bool:
        last_error = ""
        for attempt in range(1, max_retries + 1):
            try:
                info = await api.get_danmu_info(self.room_id)
                host = self._select_wss_host(info)
                websocket = await websocket_factory(host)
                await self.send_auth(websocket, token=info.get("token") or "")
                await webhook.report_heartbeat(
                    role="danmaku-worker",
                    instance_id=instance_id,
                    state="running",
                    cookie_version=self.cookie_version,
                    retry_count=attempt - 1,
                    last_error="",
                )
                return True
            except Exception as exc:
                last_error = str(exc)
                await webhook.report_heartbeat(
                    role="danmaku-worker",
                    instance_id=instance_id,
                    state="reconnecting",
                    cookie_version=self.cookie_version,
                    retry_count=attempt,
                    last_error=last_error,
                )
                if attempt < max_retries:
                    await sleep(attempt)

        await webhook.report_heartbeat(
            role="danmaku-worker",
            instance_id=instance_id,
            state="failed",
            cookie_version=self.cookie_version,
            retry_count=max_retries,
            last_error=last_error,
        )
        return False

    @staticmethod
    def _select_wss_host(danmu_info: dict[str, Any]) -> str:
        for host in danmu_info.get("host_list") or []:
            wss_port = host.get("wss_port")
            host_name = host.get("host")
            if host_name and wss_port:
                return f"wss://{host_name}:{wss_port}/sub"
        raise RuntimeError("no usable danmaku WSS host")

    def stop(self):
        self.running = False

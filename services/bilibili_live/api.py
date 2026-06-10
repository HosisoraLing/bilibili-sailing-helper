from typing import Any


DANMU_INFO_URL = "https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo"
ROOM_INFO_URL = "https://api.live.bilibili.com/room/v1/Room/get_info"


class BilibiliLiveApi:
    def __init__(self, session, cookie_header: str = "", timeout: int = 15):
        self.session = session
        self.cookie_header = cookie_header
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://live.bilibili.com/",
            "Origin": "https://live.bilibili.com",
        }
        if self.cookie_header:
            headers["Cookie"] = self.cookie_header
        return headers

    async def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        async with self.session.get(
            url,
            params=params,
            headers=self._headers(),
            timeout=self.timeout,
        ) as response:
            payload = await response.json()
            if response.status != 200:
                raise RuntimeError(f"Bilibili API HTTP {response.status}")
            if payload.get("code") != 0:
                raise RuntimeError(payload.get("message") or "Bilibili API failed")
            return payload.get("data") or {}

    async def get_danmu_info(self, room_id: int | str) -> dict[str, Any]:
        return await self._get_json(DANMU_INFO_URL, {"id": int(room_id), "type": 0})

    async def get_room_info(self, room_id: int | str) -> dict[str, Any]:
        return await self._get_json(ROOM_INFO_URL, {"room_id": int(room_id)})

import hashlib
import time
from urllib.parse import quote
from typing import Any


NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
DANMU_INFO_URL = "https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo"
ROOM_INFO_URL = "https://api.live.bilibili.com/room/v1/Room/get_info"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/132.0.0.0 Safari/537.36"
)
WBI_MIXIN_ORDER = [
    46, 47, 18, 2, 53, 8, 23, 32,
    15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19,
    29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63,
    57, 62, 11, 36, 20, 34, 44, 52,
]


class BilibiliApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: Any = None,
        http_status: int | None = None,
        url: str = "",
    ):
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.url = url


def extract_wbi_key(url: str) -> str:
    if not url:
        return ""
    return url.rsplit("/", 1)[-1].split(".", 1)[0]


def mixin_key(img_key: str, sub_key: str) -> str:
    seed = img_key + sub_key
    return "".join(seed[idx] for idx in WBI_MIXIN_ORDER if idx < len(seed))[:32]


def sanitize_wbi_value(value: Any) -> str:
    return str(value).translate(str.maketrans("", "", "!'()*"))


def sign_wbi(params: dict[str, Any], img_key: str, sub_key: str) -> dict[str, Any]:
    signed = {key: sanitize_wbi_value(value) for key, value in params.items()}
    signed["wts"] = str(int(time.time()))
    query = "&".join(
        f"{quote(str(key), safe='')}={quote(str(signed[key]), safe='')}"
        for key in sorted(signed)
    )
    signed["w_rid"] = hashlib.md5((query + mixin_key(img_key, sub_key)).encode()).hexdigest()
    return signed


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
                raise BilibiliApiError(
                    f"Bilibili API HTTP {response.status}",
                    http_status=int(response.status),
                    url=url,
                )
            if payload.get("code") != 0:
                raise BilibiliApiError(
                    payload.get("message") or "Bilibili API failed",
                    code=payload.get("code"),
                    http_status=int(response.status),
                    url=url,
                )
            return payload.get("data") or {}

    async def _wbi_keys(self) -> tuple[str, str]:
        data = await self._get_json(NAV_URL, {})
        wbi_img = data.get("wbi_img") or {}
        return (
            extract_wbi_key(str(wbi_img.get("img_url") or "")),
            extract_wbi_key(str(wbi_img.get("sub_url") or "")),
        )

    async def get_danmu_info(self, room_id: int | str) -> dict[str, Any]:
        img_key, sub_key = await self._wbi_keys()
        params = sign_wbi(
            {"id": int(room_id), "type": 0, "web_location": "444.8"},
            img_key,
            sub_key,
        )
        return await self._get_json(DANMU_INFO_URL, params)

    async def get_room_info(self, room_id: int | str) -> dict[str, Any]:
        return await self._get_json(ROOM_INFO_URL, {"room_id": int(room_id)})

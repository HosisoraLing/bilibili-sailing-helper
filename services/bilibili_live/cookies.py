from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeCookie:
    status: str
    version: int
    cookie: dict[str, str]


class RuntimeCookieProvider:
    def __init__(self, base_url: str, secret: str, session, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.secret = secret
        self.session = session
        self.timeout = timeout

    async def fetch_latest(self) -> RuntimeCookie:
        async with self.session.get(
            f"{self.base_url}/internal/runtime/cookie",
            headers={"Authorization": self.secret},
            timeout=self.timeout,
        ) as response:
            if int(response.status) >= 400:
                text = await response.text()
                raise RuntimeError(f"runtime cookie request failed: {response.status} {text}")
            payload = await response.json()
        return RuntimeCookie(
            status=str(payload.get("status") or "missing"),
            version=int(payload.get("version") or 0),
            cookie=dict(payload.get("cookie") or {}),
        )

    def fetch_latest_sync(self) -> RuntimeCookie:
        return asyncio.run(self.fetch_latest())

    @staticmethod
    def should_reload(current_version: int | None, latest: RuntimeCookie) -> bool:
        return latest.status == "valid" and int(latest.version or 0) > int(current_version or 0)

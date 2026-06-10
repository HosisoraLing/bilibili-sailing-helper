from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable


class InternalWebhookClient:
    def __init__(
        self,
        base_url: str,
        secret: str,
        session,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        timeout: float = 10.0,
        queue_size: int = 100,
        role: str = "danmaku-worker",
        instance_id: str = "danmaku-worker",
    ):
        self.base_url = base_url.rstrip("/")
        self.secret = secret
        self.session = session
        self.sleep = sleep
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.timeout = timeout
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=queue_size)
        self.role = role
        self.instance_id = instance_id
        self.last_delivery_error = ""

    def _headers(self) -> dict[str, str]:
        return {"Authorization": self.secret}

    async def _post_with_retry(self, path: str, payload: dict[str, Any]) -> bool:
        url = f"{self.base_url}{path}"
        for attempt in range(self.max_retries):
            try:
                async with self.session.post(
                    url,
                    headers=self._headers(),
                    json=payload,
                    timeout=self.timeout,
                ) as response:
                    if 200 <= int(response.status) < 300:
                        return True
                    if attempt >= self.max_retries - 1:
                        self.last_delivery_error = f"HTTP {response.status}"
                        return False
            except Exception as exc:
                self.last_delivery_error = str(exc)
                if attempt >= self.max_retries - 1:
                    return False
            await self.sleep(self.backoff_base * (2 ** attempt))
        return False

    async def deliver_auth_event(self, payload: dict[str, Any]) -> bool:
        delivered = await self._post_with_retry("/internal/danmaku/auth-event", payload)
        if not delivered:
            await self.report_heartbeat(
                role=self.role,
                instance_id=self.instance_id,
                state="delivery_error",
                delivery_error=self.last_delivery_error,
                retry_count=self.max_retries,
            )
        return delivered

    async def enqueue_auth_event(self, payload: dict[str, Any]) -> bool:
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            await self.report_heartbeat(
                role=self.role,
                instance_id=self.instance_id,
                state="queue_full",
                delivery_error="auth event queue full",
                retry_count=0,
            )
            return False
        return True

    async def drain_once(self) -> bool:
        payload = await self.queue.get()
        try:
            delivered = await self.deliver_auth_event(payload)
            if not delivered:
                try:
                    self.queue.put_nowait(payload)
                except asyncio.QueueFull:
                    pass
            return delivered
        finally:
            self.queue.task_done()

    async def report_heartbeat(
        self,
        *,
        role: str,
        instance_id: str,
        state: str,
        cookie_version: int | None = None,
        **extra,
    ) -> bool:
        payload = {
            "role": role,
            "instance_id": instance_id,
            "state": state,
            **extra,
        }
        if cookie_version is not None:
            payload["cookie_version"] = int(cookie_version)
        return await self._post_with_retry("/internal/runtime/heartbeat", payload)

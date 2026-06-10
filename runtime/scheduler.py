import asyncio
import os
from datetime import datetime, timezone
from typing import Awaitable, Callable

import aiohttp


class SchedulerStop(Exception):
    pass


async def post_json(session, url: str, *, secret: str, payload: dict):
    headers = {"Authorization": secret}
    response = await session.post(
        url,
        headers=headers,
        json=payload,
        timeout=15,
    )
    close = getattr(response, "release", None)
    try:
        status = int(getattr(response, "status", 200))
        if not 200 <= status < 300:
            text = ""
            read_text = getattr(response, "text", None)
            if callable(read_text):
                text = await read_text()
            raise RuntimeError(f"HTTP {status} from {url}: {text}")
    finally:
        if callable(close):
            close()


async def request_scheduler_jobs(
    *,
    session,
    internal_url: str,
    secret: str,
    instance_id: str,
):
    internal_url = internal_url.rstrip("/")

    await post_json(
        session,
        f"{internal_url}/internal/runtime/heartbeat",
        secret=secret,
        payload={
                "role": "scheduler",
                "instance_id": instance_id,
                "state": "running",
        },
    )
    await post_json(
        session,
        f"{internal_url}/internal/scheduler/job",
        secret=secret,
        payload={
            "job_name": "guard-sync",
            "requested_at": datetime.now(timezone.utc).isoformat(),
        },
    )


async def run_scheduler_loop(
    *,
    session,
    internal_url: str,
    secret: str,
    instance_id: str,
    interval_seconds: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
):
    failure_count = 0
    while True:
        try:
            await request_scheduler_jobs(
                session=session,
                internal_url=internal_url,
                secret=secret,
                instance_id=instance_id,
            )
            failure_count = 0
            await sleep(interval_seconds)
        except SchedulerStop:
            return
        except Exception as exc:
            failure_count += 1
            try:
                await post_json(
                    session,
                    f"{internal_url.rstrip('/')}/internal/runtime/heartbeat",
                    secret=secret,
                    payload={
                        "role": "scheduler",
                        "instance_id": instance_id,
                        "state": "delivery_error",
                        "last_error": str(exc),
                        "delivery_error": str(exc),
                        "retry_count": failure_count,
                    },
                )
            except Exception:
                pass
            try:
                await sleep(min(interval_seconds, 60))
            except SchedulerStop:
                return


async def run():
    internal_url = os.environ.get("INTERNAL_API_URL", "http://web:7111")
    secret = os.environ.get("INTERNAL_API_SECRET", "")
    instance_id = os.environ.get("RUNTIME_INSTANCE_ID", "scheduler")
    interval_seconds = float(os.environ.get("SCHEDULER_INTERVAL_SECONDS", "3600"))

    async with aiohttp.ClientSession() as session:
        await run_scheduler_loop(
            session=session,
            internal_url=internal_url,
            secret=secret,
            instance_id=instance_id,
            interval_seconds=interval_seconds,
        )


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()

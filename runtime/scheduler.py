import asyncio
import os
from datetime import datetime, timezone
from typing import Awaitable, Callable

import aiohttp


PERIODIC_JOBS = (
    "guard-sync",
    "guard-gift-refresh",
    "cookie-maintenance",
    "auth-cleanup",
)


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
    requested_at = datetime.now(timezone.utc).isoformat()
    errors = []
    for job_name in PERIODIC_JOBS:
        try:
            await post_json(
                session,
                f"{internal_url}/internal/scheduler/job",
                secret=secret,
                payload={
                    "job_name": job_name,
                    "requested_at": requested_at,
                },
            )
        except Exception as exc:
            errors.append(f"{job_name}: {exc}")

    if errors:
        raise RuntimeError("; ".join(errors))


async def report_scheduler_heartbeat(
    *,
    session,
    internal_url: str,
    secret: str,
    instance_id: str,
):
    await post_json(
        session,
        f"{internal_url.rstrip('/')}/internal/runtime/heartbeat",
        secret=secret,
        payload={
            "role": "scheduler",
            "instance_id": instance_id,
            "state": "running",
        },
    )


async def sleep_with_heartbeats(
    *,
    session,
    internal_url: str,
    secret: str,
    instance_id: str,
    total_seconds: float,
    heartbeat_interval_seconds: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
):
    remaining = total_seconds
    while remaining > 0:
        delay = min(remaining, heartbeat_interval_seconds)
        await sleep(delay)
        remaining -= delay
        if remaining > 0:
            await report_scheduler_heartbeat(
                session=session,
                internal_url=internal_url,
                secret=secret,
                instance_id=instance_id,
            )


async def run_scheduler_loop(
    *,
    session,
    internal_url: str,
    secret: str,
    instance_id: str,
    interval_seconds: float,
    heartbeat_interval_seconds: float = 30.0,
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
            await sleep_with_heartbeats(
                session=session,
                internal_url=internal_url,
                secret=secret,
                instance_id=instance_id,
                total_seconds=interval_seconds,
                heartbeat_interval_seconds=heartbeat_interval_seconds,
                sleep=sleep,
            )
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
    heartbeat_interval_seconds = float(os.environ.get("SCHEDULER_HEARTBEAT_INTERVAL_SECONDS", "30"))

    async with aiohttp.ClientSession() as session:
        await run_scheduler_loop(
            session=session,
            internal_url=internal_url,
            secret=secret,
            instance_id=instance_id,
            interval_seconds=interval_seconds,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
        )


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()

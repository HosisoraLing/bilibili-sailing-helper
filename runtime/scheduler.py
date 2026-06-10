import asyncio
import os
from datetime import datetime, timezone

import aiohttp


async def request_scheduler_jobs():
    internal_url = os.environ.get("INTERNAL_API_URL", "http://web:7111").rstrip("/")
    secret = os.environ.get("INTERNAL_API_SECRET", "")
    instance_id = os.environ.get("RUNTIME_INSTANCE_ID", "scheduler")
    headers = {"Authorization": secret}

    async with aiohttp.ClientSession() as session:
        await session.post(
            f"{internal_url}/internal/runtime/heartbeat",
            headers=headers,
            json={
                "role": "scheduler",
                "instance_id": instance_id,
                "state": "running",
            },
            timeout=15,
        )
        await session.post(
            f"{internal_url}/internal/scheduler/job",
            headers=headers,
            json={
                "job_name": "guard-sync",
                "requested_at": datetime.now(timezone.utc).isoformat(),
            },
            timeout=15,
        )


def main():
    asyncio.run(request_scheduler_jobs())


if __name__ == "__main__":
    main()

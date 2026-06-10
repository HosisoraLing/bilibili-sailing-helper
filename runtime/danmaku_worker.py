import asyncio
import os

import aiohttp

from services.bilibili_live.cookies import RuntimeCookieProvider
from services.bilibili_live.webhook import InternalWebhookClient


async def run_once():
    internal_url = os.environ.get("INTERNAL_API_URL", "http://web:7111")
    secret = os.environ.get("INTERNAL_API_SECRET", "")
    instance_id = os.environ.get("RUNTIME_INSTANCE_ID", "danmaku-worker")

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
        latest = await cookie_provider.fetch_latest()
        state = "running" if latest.status == "valid" else "cookie_unavailable"
        await webhook.report_heartbeat(
            role="danmaku-worker",
            instance_id=instance_id,
            state=state,
            cookie_version=latest.version,
        )


def main():
    asyncio.run(run_once())


if __name__ == "__main__":
    main()

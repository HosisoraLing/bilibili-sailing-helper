import asyncio
import json
import struct
import zlib

import pytest


def _packet(op, body=b"", version=0):
    packet_len = 16 + len(body)
    return struct.pack("!IHHII", packet_len, 16, version, op, 1) + body


def test_pack_heartbeat_has_bilibili_header():
    from services.bilibili_live.protocol import OP_HEARTBEAT, pack_heartbeat

    packet = pack_heartbeat()

    packet_len, header_len, version, operation, sequence = struct.unpack("!IHHII", packet[:16])
    assert packet_len == 16
    assert header_len == 16
    assert version == 1
    assert operation == OP_HEARTBEAT
    assert sequence == 1


def test_pack_auth_serializes_payload():
    from services.bilibili_live.protocol import OP_AUTH, pack_auth, unpack_packets

    packet = pack_auth({"roomid": 1, "key": "token"})

    unpacked = unpack_packets(packet)
    assert len(unpacked) == 1
    assert unpacked[0]["operation"] == OP_AUTH
    assert json.loads(unpacked[0]["body"].decode("utf-8")) == {"roomid": 1, "key": "token"}


def test_unpack_packets_expands_zlib_message_batch():
    from services.bilibili_live.protocol import OP_MESSAGE, unpack_packets

    first = _packet(OP_MESSAGE, json.dumps({"cmd": "A"}).encode("utf-8"))
    second = _packet(OP_MESSAGE, json.dumps({"cmd": "B"}).encode("utf-8"))
    compressed = zlib.compress(first + second)

    packets = unpack_packets(_packet(OP_MESSAGE, compressed, version=2))

    assert [json.loads(packet["body"].decode("utf-8"))["cmd"] for packet in packets] == ["A", "B"]


def test_unpack_packets_ignores_malformed_compressed_payloads():
    from services.bilibili_live.protocol import OP_MESSAGE, unpack_packets

    assert unpack_packets(_packet(OP_MESSAGE, b"not-zlib", version=2)) == []


def test_unpack_packets_expands_brotli_message_batch_if_available():
    brotli = pytest.importorskip("brotli")
    from services.bilibili_live.protocol import OP_MESSAGE, unpack_packets

    nested = _packet(OP_MESSAGE, json.dumps({"cmd": "DANMU_MSG"}).encode("utf-8"))

    packets = unpack_packets(_packet(OP_MESSAGE, brotli.compress(nested), version=3))

    assert json.loads(packets[0]["body"].decode("utf-8"))["cmd"] == "DANMU_MSG"


def test_normalize_danmaku_event_extracts_stable_fields():
    from services.bilibili_live.events import normalize_danmaku_event

    normalized = normalize_danmaku_event(
        {"cmd": "DANMU_MSG:4:0:2", "info": [[], "vc-abcdef1234", [42, "tester"]]},
        room_id=100,
    )

    assert normalized == {
        "uid": "42",
        "nickname": "tester",
        "content": "vc-abcdef1234",
        "room_id": "100",
        "raw_cmd": "DANMU_MSG:4:0:2",
    }


def test_normalize_danmaku_event_ignores_unsupported_or_malformed_payload():
    from services.bilibili_live.events import normalize_danmaku_event

    assert normalize_danmaku_event(None, room_id=100) is None
    assert normalize_danmaku_event(["DANMU_MSG"], room_id=100) is None
    assert normalize_danmaku_event({"cmd": "SEND_GIFT", "data": {}}, room_id=100) is None
    assert normalize_danmaku_event({"cmd": "DANMU_MSG", "info": []}, room_id=100) is None


def test_webhook_client_retries_and_reports_delivery_error():
    async def run_test():
        from services.bilibili_live.webhook import InternalWebhookClient

        class FakeResponse:
            def __init__(self, status):
                self.status = status

            async def text(self):
                return "bad gateway"

        class FakePostContext:
            def __init__(self, response):
                self.response = response

            async def __aenter__(self):
                return self.response

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return False

        class FakeSession:
            def __init__(self):
                self.calls = []

            def post(self, url, headers=None, json=None, timeout=None):
                self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
                status = 502 if len(self.calls) == 1 else 200
                return FakePostContext(FakeResponse(status))

        sleep_calls = []

        async def fake_sleep(delay):
            sleep_calls.append(delay)

        session = FakeSession()
        client = InternalWebhookClient(
            base_url="https://web.test",
            secret="secret",
            session=session,
            sleep=fake_sleep,
            max_retries=2,
            backoff_base=0.01,
            timeout=3,
        )

        delivered = await client.deliver_auth_event({"uid": "42", "content": "vc-1"})

        assert delivered is True
        assert [call["url"] for call in session.calls] == [
            "https://web.test/internal/danmaku/auth-event",
            "https://web.test/internal/danmaku/auth-event",
        ]
        assert session.calls[0]["headers"]["Authorization"] == "secret"
        assert sleep_calls == [0.01]

    asyncio.run(run_test())


def test_webhook_client_reports_delivery_error_after_network_failures():
    async def run_test():
        from services.bilibili_live.webhook import InternalWebhookClient

        class FakeResponse:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return False

            async def text(self):
                return "ok"

        class FakeSession:
            def __init__(self):
                self.calls = []

            def post(self, url, headers=None, json=None, timeout=None):
                self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
                if url.endswith("/internal/danmaku/auth-event"):
                    raise TimeoutError("web timeout")
                return FakeResponse()

        sleep_calls = []

        async def fake_sleep(delay):
            sleep_calls.append(delay)

        session = FakeSession()
        client = InternalWebhookClient(
            base_url="https://web.test",
            secret="secret",
            session=session,
            sleep=fake_sleep,
            max_retries=2,
            backoff_base=0.01,
        )

        delivered = await client.deliver_auth_event({"uid": "42", "content": "vc-1"})

        assert delivered is False
        assert [call["url"] for call in session.calls] == [
            "https://web.test/internal/danmaku/auth-event",
            "https://web.test/internal/danmaku/auth-event",
            "https://web.test/internal/runtime/heartbeat",
        ]
        assert session.calls[-1]["json"]["state"] == "delivery_error"
        assert session.calls[-1]["json"]["delivery_error"] == "web timeout"
        assert session.calls[-1]["json"]["retry_count"] == 2
        assert sleep_calls == [0.01]

    asyncio.run(run_test())


def test_webhook_client_uses_bounded_local_queue():
    async def run_test():
        from services.bilibili_live.webhook import InternalWebhookClient

        class FakeResponse:
            status = 200

            async def text(self):
                return "ok"

        class FakePostContext:
            async def __aenter__(self):
                return FakeResponse()

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return False

        class FakeSession:
            def __init__(self):
                self.calls = []

            def post(self, url, headers=None, json=None, timeout=None):
                self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
                return FakePostContext()

        session = FakeSession()
        client = InternalWebhookClient(
            base_url="https://web.test",
            secret="secret",
            session=session,
            queue_size=1,
        )

        assert await client.enqueue_auth_event({"uid": "1", "content": "vc-1"}) is True
        assert await client.enqueue_auth_event({"uid": "2", "content": "vc-2"}) is False

        delivered = await client.drain_once()

        assert delivered is True
        assert session.calls[-1]["json"] == {"uid": "1", "content": "vc-1"}

    asyncio.run(run_test())


def test_webhook_client_reports_queue_full_when_event_cannot_be_enqueued():
    async def run_test():
        from services.bilibili_live.webhook import InternalWebhookClient

        class FakeResponse:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return False

            async def text(self):
                return "ok"

        class FakeSession:
            def __init__(self):
                self.calls = []

            def post(self, url, headers=None, json=None, timeout=None):
                self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
                return FakeResponse()

        session = FakeSession()
        client = InternalWebhookClient(
            base_url="https://web.test",
            secret="secret",
            session=session,
            queue_size=1,
            instance_id="worker-queue",
        )

        assert await client.enqueue_auth_event({"uid": "1"}) is True
        assert await client.enqueue_auth_event({"uid": "2"}) is False

        assert session.calls == [
            {
                "url": "https://web.test/internal/runtime/heartbeat",
                "headers": {"Authorization": "secret"},
                "json": {
                    "role": "danmaku-worker",
                    "instance_id": "worker-queue",
                    "state": "queue_full",
                    "delivery_error": "auth event queue full",
                    "retry_count": 0,
                },
                "timeout": 10.0,
            }
        ]

    asyncio.run(run_test())


def test_webhook_client_retries_request_exceptions():
    async def run_test():
        from services.bilibili_live.webhook import InternalWebhookClient

        class FakeResponse:
            status = 200

            async def text(self):
                return "ok"

        class FakePostContext:
            async def __aenter__(self):
                return FakeResponse()

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return False

        class FakeSession:
            def __init__(self):
                self.calls = 0

            def post(self, url, headers=None, json=None, timeout=None):
                self.calls += 1
                if self.calls == 1:
                    raise OSError("network down")
                return FakePostContext()

        sleep_calls = []

        async def fake_sleep(delay):
            sleep_calls.append(delay)

        session = FakeSession()
        client = InternalWebhookClient(
            base_url="https://web.test",
            secret="secret",
            session=session,
            sleep=fake_sleep,
            max_retries=2,
            backoff_base=0.01,
        )

        assert await client.deliver_auth_event({"uid": "42", "content": "vc-1"}) is True
        assert session.calls == 2
        assert sleep_calls == [0.01]

    asyncio.run(run_test())


def test_webhook_client_requeues_failed_drain_payload():
    async def run_test():
        from services.bilibili_live.webhook import InternalWebhookClient

        class FakeResponse:
            status = 503

            async def text(self):
                return "unavailable"

        class FakePostContext:
            async def __aenter__(self):
                return FakeResponse()

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return False

        class FakeSession:
            def post(self, url, headers=None, json=None, timeout=None):
                return FakePostContext()

        client = InternalWebhookClient(
            base_url="https://web.test",
            secret="secret",
            session=FakeSession(),
            sleep=lambda delay: asyncio.sleep(0),
            max_retries=1,
            queue_size=1,
        )

        payload = {"uid": "42", "content": "vc-1"}
        assert await client.enqueue_auth_event(payload) is True
        assert await client.drain_once() is False
        assert client.queue.get_nowait() == payload

    asyncio.run(run_test())


def test_webhook_client_sends_cookie_version_in_heartbeat():
    async def run_test():
        from services.bilibili_live.webhook import InternalWebhookClient

        class FakeResponse:
            status = 200

            async def text(self):
                return "ok"

        class FakePostContext:
            async def __aenter__(self):
                return FakeResponse()

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return False

        class FakeSession:
            def __init__(self):
                self.calls = []

            def post(self, url, headers=None, json=None, timeout=None):
                self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
                return FakePostContext()

        session = FakeSession()
        client = InternalWebhookClient(
            base_url="https://web.test",
            secret="secret",
            session=session,
            sleep=asyncio.sleep,
        )

        await client.report_heartbeat(
            role="danmaku-worker",
            instance_id="worker-1",
            state="running",
            cookie_version=3,
        )

        assert session.calls[0]["url"] == "https://web.test/internal/runtime/heartbeat"
        assert session.calls[0]["json"]["cookie_version"] == 3

    asyncio.run(run_test())


def test_live_api_fetches_danmu_info_with_cookie_headers():
    async def run_test():
        from services.bilibili_live.api import BilibiliLiveApi

        class FakeResponse:
            status = 200
            headers = {}
            def __init__(self, payload):
                self.payload = payload

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return False

            async def json(self):
                return self.payload

        class FakeSession:
            def __init__(self):
                self.calls = []

            def get(self, url, params=None, headers=None, timeout=None):
                self.calls.append({
                    "url": url,
                    "params": params,
                    "headers": headers,
                    "timeout": timeout,
                })
                if url.endswith("/x/web-interface/nav"):
                    return FakeResponse({
                        "code": 0,
                        "data": {
                            "wbi_img": {
                                "img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png",
                                "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png",
                            }
                        },
                    })
                return FakeResponse({
                    "code": 0,
                    "data": {
                        "token": "token",
                        "host_list": [{"host": "broadcast.test", "wss_port": 443}],
                    },
                })

        session = FakeSession()
        api = BilibiliLiveApi(
            session=session,
            cookie_header="SESSDATA=sess; buvid3=buvid",
        )

        result = await api.get_danmu_info(room_id=123)

        assert result["token"] == "token"
        assert session.calls[0]["url"].endswith("/x/web-interface/nav")
        assert session.calls[1]["url"].endswith("/xlive/web-room/v1/index/getDanmuInfo")
        assert session.calls[1]["params"]["id"] == "123"
        assert session.calls[1]["params"]["type"] == "0"
        assert session.calls[1]["params"]["web_location"] == "444.8"
        assert session.calls[1]["params"]["wts"]
        assert session.calls[1]["params"]["w_rid"]
        assert session.calls[1]["headers"]["Cookie"] == "SESSDATA=sess; buvid3=buvid"

    asyncio.run(run_test())


def test_worker_adds_ephemeral_buvid3_for_cookie_without_persisted_buvid():
    from runtime.danmaku_worker import cookie_header, runtime_live_cookie

    original = {"SESSDATA": "sess", "bili_jct": "csrf", "buvid3": ""}

    live_cookie = runtime_live_cookie(original)

    assert original["buvid3"] == ""
    assert live_cookie["SESSDATA"] == "sess"
    assert live_cookie["bili_jct"] == "csrf"
    assert live_cookie["buvid3"]
    assert "buvid3=" in cookie_header(live_cookie)


def test_live_client_sends_auth_payload_and_heartbeat_packets():
    async def run_test():
        from services.bilibili_live.client import BilibiliLiveClient
        from services.bilibili_live.protocol import OP_AUTH, OP_HEARTBEAT, unpack_packets

        class FakeWebSocket:
            def __init__(self):
                self.sent = []

            async def send_bytes(self, data):
                self.sent.append(data)

        ws = FakeWebSocket()
        client = BilibiliLiveClient(
            room_id=123,
            uid=42,
            buvid3="buvid",
            cookie_version=5,
            heartbeat_interval=0.01,
        )

        await client.send_auth(ws, token="token")
        await client.send_heartbeat(ws)

        auth = unpack_packets(ws.sent[0])[0]
        heartbeat = unpack_packets(ws.sent[1])[0]
        assert auth["operation"] == OP_AUTH
        assert json.loads(auth["body"].decode("utf-8")) == {
            "uid": 42,
            "roomid": 123,
            "protover": 3,
            "buvid": "buvid",
            "platform": "web",
            "type": 2,
            "key": "token",
        }
        assert heartbeat["operation"] == OP_HEARTBEAT

    asyncio.run(run_test())


def test_live_client_reports_reconnecting_and_retries_bounded_connection():
    async def run_test():
        from services.bilibili_live.client import BilibiliLiveClient

        class FakeApi:
            async def get_danmu_info(self, room_id):
                return {
                    "token": "token",
                    "host_list": [{"host": "broadcast.test", "wss_port": 443}],
                }

        class FakeWebSocket:
            def __init__(self):
                self.sent = []

            async def send_bytes(self, data):
                self.sent.append(data)

        class FakeWebhook:
            def __init__(self):
                self.heartbeats = []

            async def report_heartbeat(self, **payload):
                self.heartbeats.append(payload)
                return True

        attempts = []

        async def websocket_factory(_url):
            attempts.append(_url)
            if len(attempts) == 1:
                raise RuntimeError("connect failed")
            return FakeWebSocket()

        sleeps = []

        async def fake_sleep(delay):
            sleeps.append(delay)

        webhook = FakeWebhook()
        client = BilibiliLiveClient(
            room_id=123,
            uid=42,
            buvid3="buvid",
            cookie_version=5,
        )

        connected = await client.connect_with_retries(
            api=FakeApi(),
            websocket_factory=websocket_factory,
            webhook=webhook,
            instance_id="worker-1",
            max_retries=2,
            sleep=fake_sleep,
        )

        assert connected is True
        assert len(attempts) == 2
        assert sleeps == [1]
        assert webhook.heartbeats[0]["state"] == "reconnecting"
        assert webhook.heartbeats[0]["retry_count"] == 1
        assert webhook.heartbeats[0]["cookie_version"] == 5
        assert webhook.heartbeats[-1]["state"] == "running"

    asyncio.run(run_test())


def test_worker_waits_for_new_cookie_after_bilibili_minus_352():
    async def run_test():
        from runtime.danmaku_worker import WorkerStop, run_worker_loop
        from services.bilibili_live.cookies import RuntimeCookie

        class FakeCookieProvider:
            def __init__(self):
                self.polls_after_rejection = 0

            async def fetch_latest(self):
                if api_attempts:
                    self.polls_after_rejection += 1
                    version = 8 if self.polls_after_rejection >= 2 else 7
                    return RuntimeCookie(
                        status="valid",
                        version=version,
                        cookie={"SESSDATA": f"sess-{version}"},
                    )
                return RuntimeCookie(
                    status="valid",
                    version=7,
                    cookie={"SESSDATA": "sess-7"},
                )

        class FakeWebhook:
            def __init__(self):
                self.heartbeats = []

            async def report_heartbeat(self, **payload):
                self.heartbeats.append(payload)
                return True

        api_attempts = []

        class FakeApi:
            def __init__(self, *_args, **_kwargs):
                pass

            async def get_danmu_info(self, _room_id):
                api_attempts.append(_room_id)
                if len(api_attempts) == 1:
                    raise RuntimeError("-352")
                raise WorkerStop()

        async def websocket_factory(_url):
            raise AssertionError("websocket must not connect after -352")

        sleeps = []

        async def fake_sleep(delay):
            sleeps.append(delay)

        webhook = FakeWebhook()

        await run_worker_loop(
            room_id=123,
            cookie_provider=FakeCookieProvider(),
            webhook=webhook,
            api_factory=FakeApi,
            websocket_factory=websocket_factory,
            instance_id="worker-rejected",
            idle_sleep=fake_sleep,
        )

        assert api_attempts == [123, 123]
        assert sleeps == [5.0, 5.0]
        assert webhook.heartbeats[0] == {
            "role": "danmaku-worker",
            "instance_id": "worker-rejected",
            "state": "bilibili_rejected",
            "cookie_version": 7,
            "last_error": "B站直播接口返回 -352，请扫码授权其他账号",
        }
        assert webhook.heartbeats[1] == {
            "role": "danmaku-worker",
            "instance_id": "worker-rejected",
            "state": "cookie_reloading",
            "cookie_version": 8,
        }

    asyncio.run(run_test())

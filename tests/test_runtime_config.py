import asyncio
from pathlib import Path

from sqlalchemy import inspect, text


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_runtime_entrypoints_exist_and_expose_main_functions():
    runtime_dir = ROOT / "runtime"
    assert (runtime_dir / "web.py").exists()
    assert (runtime_dir / "danmaku_worker.py").exists()
    assert (runtime_dir / "scheduler.py").exists()

    for path in ("runtime/web.py", "runtime/danmaku_worker.py", "runtime/scheduler.py"):
        source = read(path)
        assert "def main(" in source
        assert "if __name__ == \"__main__\":" in source


def test_compose_defines_split_runtime_roles():
    compose = read("docker-compose.yml")

    assert "\n  web:" in compose
    assert "\n  danmaku-worker:" in compose
    assert "\n  scheduler:" in compose
    assert "\n  app:" not in compose
    assert "command: [\"python\", \"-m\", \"runtime.web\"]" in compose
    assert "command: [\"python\", \"-m\", \"runtime.danmaku_worker\"]" in compose
    assert "command: [\"python\", \"-m\", \"runtime.scheduler\"]" in compose
    assert "INTERNAL_API_URL=http://web:7111" in compose
    assert "replace-this-internal-secret" not in compose
    assert "INTERNAL_API_SECRET=${INTERNAL_API_SECRET:?set INTERNAL_API_SECRET}" in compose


def test_worker_and_scheduler_do_not_mount_database_for_writes():
    compose = read("docker-compose.yml")
    worker_section = compose.split("  danmaku-worker:", 1)[1].split("\n  scheduler:", 1)[0]
    scheduler_section = compose.split("  scheduler:", 1)[1]
    for section in (worker_section, scheduler_section):
        assert "./data:/app/data" not in section
        assert "./data:/app/data:rw" not in section
        assert "healthcheck:" in section
        assert "disable: true" in section


def test_scheduler_entrypoint_uses_internal_api_not_business_writers():
    scheduler_source = read("runtime/scheduler.py")

    assert "db.session" not in scheduler_source
    assert "fetch_and_save_guards" not in scheduler_source
    assert "/internal/scheduler/job" in scheduler_source


def test_production_runtime_has_no_blivedm_playwright_or_runtime_git_pull():
    runtime_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            ROOT / "runtime" / "web.py",
            ROOT / "runtime" / "danmaku_worker.py",
            ROOT / "runtime" / "scheduler.py",
        ]
    )
    production_sources = "\n".join([
        read("requirements.txt"),
        read("Dockerfile"),
        read("app.py"),
        runtime_sources,
    ])

    assert "playwright" not in production_sources.lower()
    assert "chromium" not in production_sources.lower()
    assert "blivedm" not in read("requirements.txt")
    assert "git pull" not in production_sources
    assert "git', 'pull" not in production_sources


def test_web_startup_does_not_own_background_worker_loops():
    web_source = read("runtime/web.py")
    app_source = read("app.py")
    start_runtime_source = app_source.split("def start_runtime_services", 1)[1].split(
        "def run_web_server",
        1,
    )[0]

    assert "start_danmaku_auth_listener" not in web_source
    assert "start_auto_update_scheduler" not in web_source
    assert "CookieService.start_auto_refresh_scheduler" not in web_source
    assert "start_guards_scheduler" not in start_runtime_source
    assert "start_guard_gift_scheduler" not in start_runtime_source
    assert "start_session_cleanup_scheduler" not in start_runtime_source
    assert "start_runtime_services" in app_source


def test_web_startup_does_not_run_database_migrations():
    web_source = read("runtime/web.py")

    assert "run_migrations" not in web_source
    assert "if not inspector.get_table_names()" in web_source


def test_empty_database_initializer_only_creates_brand_new_schema(app):
    from db.models import db
    from runtime.web import initialize_empty_database_only

    with app.app_context():
        db.drop_all()
        initialize_empty_database_only()
        assert "users" in inspect(db.engine).get_table_names()

        db.drop_all()
        db.session.execute(
            text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid VARCHAR(32) UNIQUE NOT NULL,
                    nickname VARCHAR(64) NOT NULL,
                    password_hash VARCHAR(256),
                    is_admin BOOLEAN DEFAULT 0,
                    created_at DATETIME
                )
                """
            )
        )
        db.session.commit()

        initialize_empty_database_only()

        user_columns = {
            row[1]
            for row in db.session.execute(text("PRAGMA table_info(users)"))
        }
        assert "roles" not in user_columns


def test_settings_example_uses_canonical_internal_port():
    settings_example = read("settings.json.example")
    dockerfile = read("Dockerfile")
    compose = read("docker-compose.yml")

    assert '"port": 7111' in settings_example
    assert "EXPOSE 7111" in dockerfile
    assert "7111:7111" in compose


def test_auth_page_keeps_polling_after_socketio_connect():
    auth_source = read("templates/auth.html")
    connect_handler = auth_source.split("socket.on('connect'", 1)[1].split(
        "socket.on('connect_error'",
        1,
    )[0]

    assert "stopPolling()" not in connect_handler
    assert "startPolling()" in connect_handler


def test_admin_panel_displays_runtime_diagnostics():
    admin_source = read("templates/admin_panel.html")

    assert "last_error" in admin_source
    assert "delivery_error" in admin_source
    assert "retry_count" in admin_source
    assert "active_cookie_version" in admin_source
    assert "worker_cookie_version" in admin_source
    assert "Cookie版本" in admin_source
    assert "上报于" in admin_source
    assert 'id="accountStatusPanel"' in admin_source
    assert 'id="accountStatusUid"' in admin_source
    assert 'id="accountStatusAuth"' in admin_source
    assert 'id="accountStatusCookieVersion"' in admin_source
    assert 'id="accountStatusWorker"' in admin_source
    assert 'id="accountStatusReload"' in admin_source
    assert "function updateAccountStatus" in admin_source
    admin_actions = admin_source.split('<div class="admin-actions">', 1)[1].split("</div>", 1)[0]
    assert "startQrLogin()" in admin_actions
    assert "切换B站账号" in admin_actions
    listener_alert = admin_source.split('id="listenerAlert"', 1)[1].split('id="qrCodeArea"', 1)[0]
    assert "restartListener()" not in listener_alert
    assert "查看重启方式" not in listener_alert


class FakeCookieProvider:
    def __init__(self, *cookies):
        self.cookies = list(cookies)
        self.calls = 0

    async def fetch_latest(self):
        self.calls += 1
        if self.cookies:
            return self.cookies.pop(0)
        from services.bilibili_live.cookies import RuntimeCookie

        return RuntimeCookie(status="valid", version=1, cookie={"SESSDATA": "sess"})


class FakeWebhook:
    def __init__(self):
        self.heartbeats = []
        self.events = []

    async def report_heartbeat(self, **payload):
        self.heartbeats.append(payload)
        return True

    async def enqueue_auth_event(self, payload):
        self.events.append(payload)
        return True

    async def drain_once(self):
        return True


class FakeApi:
    def __init__(self, session, cookie_header=""):
        self.session = session
        self.cookie_header = cookie_header

    async def get_danmu_info(self, room_id):
        return {
            "token": "token",
            "host_list": [{"host": "live.example", "wss_port": 443}],
        }


class FakeWebSocket:
    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []

    async def send_bytes(self, payload):
        self.sent.append(payload)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.messages:
            raise StopAsyncIteration
        return self.messages.pop(0)

    async def close(self):
        self.closed = True


def test_danmaku_worker_runs_native_watcher_and_keeps_loop_until_stopped(monkeypatch):
    from services.bilibili_live.cookies import RuntimeCookie
    from services.bilibili_live.protocol import OP_MESSAGE, pack_packet
    from runtime import danmaku_worker

    raw_event = {
        "cmd": "DANMU_MSG",
        "info": [[], "vc-code", [42, "tester"]],
    }
    packet = pack_packet(OP_MESSAGE, danmaku_worker.json_dumps(raw_event))
    websocket = FakeWebSocket([packet])
    webhook = FakeWebhook()

    async def websocket_factory(_url):
        return websocket

    async def stop_after_first_iteration(_seconds):
        raise danmaku_worker.WorkerStop("test stop")

    asyncio.run(
        danmaku_worker.run_worker_loop(
            room_id=1,
            cookie_provider=FakeCookieProvider(
                RuntimeCookie(status="valid", version=1, cookie={"SESSDATA": "sess"}),
            ),
            webhook=webhook,
            api_factory=FakeApi,
            websocket_factory=websocket_factory,
            instance_id="worker-1",
            reconnect_delay=0,
            idle_sleep=stop_after_first_iteration,
        )
    )

    assert any(item["state"] == "running" for item in webhook.heartbeats)
    assert webhook.events == [
        {
            "uid": "42",
            "nickname": "tester",
            "content": "vc-code",
            "room_id": "1",
            "raw_cmd": "DANMU_MSG",
        }
    ]


def test_danmaku_worker_closes_connection_when_cookie_version_changes():
    from services.bilibili_live.cookies import RuntimeCookie
    from runtime import danmaku_worker

    websocket = FakeWebSocket([])
    websocket.closed = False
    webhook = FakeWebhook()

    async def websocket_factory(_url):
        return websocket

    async def fast_poll(_seconds):
        return None

    asyncio.run(
        danmaku_worker.run_connection(
            room_id=1,
            cookie=RuntimeCookie(status="valid", version=1, cookie={"SESSDATA": "old"}),
            cookie_provider=FakeCookieProvider(
                RuntimeCookie(status="valid", version=2, cookie={"SESSDATA": "new"}),
            ),
            webhook=webhook,
            api_factory=FakeApi,
            websocket_factory=websocket_factory,
            instance_id="worker-1",
            cookie_poll_interval=0,
            sleep=fast_poll,
        )
    )

    assert websocket.closed is True
    assert any(item["state"] == "cookie_reloading" for item in webhook.heartbeats)


def test_danmaku_worker_uses_short_default_cookie_poll_interval():
    from runtime import danmaku_worker

    assert danmaku_worker.default_cookie_poll_interval({}) == 10.0
    assert danmaku_worker.default_cookie_poll_interval({
        "DANMAKU_COOKIE_POLL_INTERVAL_SECONDS": "5",
    }) == 5.0


def test_danmaku_worker_cookie_monitor_survives_transient_fetch_failure():
    from services.bilibili_live.cookies import RuntimeCookie
    from runtime import danmaku_worker

    class FlakyCookieProvider:
        def __init__(self):
            self.calls = 0

        async def fetch_latest(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("web restarting")
            return RuntimeCookie(status="valid", version=2, cookie={"SESSDATA": "new"})

    websocket = FakeWebSocket([])
    websocket.closed = False
    webhook = FakeWebhook()
    provider = FlakyCookieProvider()

    async def fast_poll(_seconds):
        return None

    asyncio.run(
        danmaku_worker.monitor_cookie_version(
            cookie_provider=provider,
            current_version=1,
            websocket=websocket,
            webhook=webhook,
            instance_id="worker-1",
            poll_interval=0,
            sleep=fast_poll,
        )
    )

    assert provider.calls == 2
    assert websocket.closed is True
    assert any(item["state"] == "cookie_poll_error" for item in webhook.heartbeats)
    assert any(item["state"] == "cookie_reloading" for item in webhook.heartbeats)


def test_scheduler_runs_recurring_jobs_until_stopped():
    from runtime import scheduler

    posts = []

    class FakeResponse:
        status = 200

        def release(self):
            pass

    class FakeSession:
        async def post(self, url, headers=None, json=None, timeout=None):
            posts.append((url, json))
            return FakeResponse()

    async def stop_after_first_interval(_seconds):
        raise scheduler.SchedulerStop("test stop")

    asyncio.run(
        scheduler.run_scheduler_loop(
            session=FakeSession(),
            internal_url="http://web:7111",
            secret="secret",
            instance_id="scheduler-1",
            interval_seconds=60,
            sleep=stop_after_first_interval,
        )
    )

    assert any(url.endswith("/internal/runtime/heartbeat") for url, _ in posts)
    job_names = {
        payload["job_name"]
        for url, payload in posts
        if url.endswith("/internal/scheduler/job")
    }
    assert job_names == {
        "guard-sync",
        "guard-gift-refresh",
        "cookie-maintenance",
        "auth-cleanup",
    }


def test_scheduler_reports_heartbeat_while_waiting_between_job_cycles():
    from runtime import scheduler

    posts = []
    sleeps = []

    class FakeResponse:
        status = 200

        def release(self):
            pass

    class FakeSession:
        async def post(self, url, headers=None, json=None, timeout=None):
            posts.append((url, json))
            return FakeResponse()

    async def stop_after_two_sleeps(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 2:
            raise scheduler.SchedulerStop("test stop")

    asyncio.run(
        scheduler.run_scheduler_loop(
            session=FakeSession(),
            internal_url="http://web:7111",
            secret="secret",
            instance_id="scheduler-1",
            interval_seconds=3600,
            sleep=stop_after_two_sleeps,
            heartbeat_interval_seconds=30,
        )
    )

    heartbeat_payloads = [
        payload
        for url, payload in posts
        if url.endswith("/internal/runtime/heartbeat")
        and payload["role"] == "scheduler"
    ]
    assert [payload["state"] for payload in heartbeat_payloads] == ["running", "running"]
    assert sleeps == [30, 30]


def test_scheduler_attempts_all_jobs_when_one_request_fails():
    from runtime import scheduler

    posts = []

    class FakeResponse:
        def __init__(self, status=200):
            self.status = status

        async def text(self):
            return "job failed"

        def release(self):
            pass

    class FakeSession:
        async def post(self, url, headers=None, json=None, timeout=None):
            posts.append((url, json))
            if (
                url.endswith("/internal/scheduler/job")
                and json["job_name"] == "guard-gift-refresh"
            ):
                return FakeResponse(500)
            return FakeResponse()

    try:
        asyncio.run(
            scheduler.request_scheduler_jobs(
                session=FakeSession(),
                internal_url="http://web:7111",
                secret="secret",
                instance_id="scheduler-1",
            )
        )
    except RuntimeError as exc:
        assert "guard-gift-refresh" in str(exc)
    else:
        raise AssertionError("request_scheduler_jobs should raise after collecting failures")

    job_names = [
        payload["job_name"]
        for url, payload in posts
        if url.endswith("/internal/scheduler/job")
    ]
    assert job_names == [
        "guard-sync",
        "guard-gift-refresh",
        "cookie-maintenance",
        "auth-cleanup",
    ]


def test_scheduler_raises_on_internal_api_error():
    from runtime import scheduler

    class FakeResponse:
        status = 401

        async def text(self):
            return "unauthorized"

        def release(self):
            pass

    class FakeSession:
        async def post(self, url, headers=None, json=None, timeout=None):
            return FakeResponse()

    try:
        asyncio.run(
            scheduler.post_json(
                FakeSession(),
                "http://web:7111/internal/scheduler/job",
                secret="bad",
                payload={"job_name": "guard-sync"},
            )
        )
    except RuntimeError as exc:
        assert "HTTP 401" in str(exc)
    else:
        raise AssertionError("post_json should raise on non-2xx responses")


def test_scheduler_reports_error_heartbeat_when_job_request_fails():
    from runtime import scheduler

    posts = []

    class FakeResponse:
        def __init__(self, status=200):
            self.status = status

        async def text(self):
            return "failed"

        def release(self):
            pass

    class FakeSession:
        async def post(self, url, headers=None, json=None, timeout=None):
            posts.append((url, json))
            if url.endswith("/internal/scheduler/job"):
                return FakeResponse(502)
            return FakeResponse(200)

    async def stop_after_error(_seconds):
        raise scheduler.SchedulerStop("test stop")

    asyncio.run(
        scheduler.run_scheduler_loop(
            session=FakeSession(),
            internal_url="http://web:7111",
            secret="secret",
            instance_id="scheduler-1",
            interval_seconds=60,
            sleep=stop_after_error,
        )
    )

    assert any(
        url.endswith("/internal/runtime/heartbeat")
        and payload["state"] == "delivery_error"
        and "HTTP 502" in payload["last_error"]
        for url, payload in posts
    )

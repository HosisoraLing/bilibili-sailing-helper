from datetime import timedelta

from sqlalchemy import text

from db.models import CookieMetadata, RuntimeStatus, db, get_beijing_now


def test_qr_success_advances_cookie_version(app, monkeypatch):
    from services import bilibili_qr_service
    from services.bilibili_qr_service import poll_qr_login, start_qr_login
    from tests.test_qr_login import FakeHttpClient, FakeResponse

    monkeypatch.setattr(
        bilibili_qr_service.CookieService,
        "load_settings",
        staticmethod(lambda: {"bilibili": {"SESSDATA": "old", "bili_jct": "old-csrf"}}),
    )
    monkeypatch.setattr(
        bilibili_qr_service.CookieService,
        "save_settings",
        staticmethod(lambda settings: True),
    )
    http = FakeHttpClient([
        FakeResponse({
            "code": 0,
            "data": {
                "url": "https://passport.bilibili.com/qrcode/test",
                "qrcode_key": "key-cookie-version",
            },
        }),
        FakeResponse(
            {"code": 0, "data": {"code": 0, "message": "ok", "url": "https://bilibili.com"}},
            cookies={"SESSDATA": "new-sess", "bili_jct": "new-csrf", "DedeUserID": "42"},
        ),
        FakeResponse({"code": 0, "data": {"isLogin": True, "uname": "tester", "mid": 42}}),
    ])

    with app.app_context():
        task = start_qr_login(http_client=http)
        result = poll_qr_login(task["task_id"], http_client=http)

        metadata = CookieMetadata.query.filter_by(role="admin").one()
        assert result["status"] == "succeeded"
        assert metadata.cookie_version == 1


def test_internal_runtime_cookie_requires_secret(client):
    assert client.get("/internal/runtime/cookie").status_code == 401
    assert client.get(
        "/internal/runtime/cookie",
        headers={"Authorization": "wrong-secret"},
    ).status_code == 401


def test_internal_runtime_cookie_returns_validated_cookie_state(client, app, monkeypatch):
    from services.runtime_cookie_service import RuntimeCookieService

    monkeypatch.setattr(
        RuntimeCookieService,
        "load_cookie_settings",
        staticmethod(lambda: {
            "SESSDATA": "sess-value",
            "bili_jct": "csrf-value",
            "buvid3": "buvid-value",
        }),
    )

    with app.app_context():
        db.session.add(CookieMetadata(
            role="admin",
            status="valid",
            source="qr_login",
            masked_uid="42",
            cookie_version=7,
            last_validated_at=get_beijing_now(),
        ))
        db.session.commit()

    response = client.get(
        "/internal/runtime/cookie",
        headers={"Authorization": "test-secret"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "valid"
    assert payload["version"] == 7
    assert payload["cookie"]["SESSDATA"] == "sess-value"
    assert payload["cookie"]["bili_jct"] == "csrf-value"
    assert payload["cookie"]["buvid3"] == "buvid-value"


def test_internal_runtime_cookie_hides_incomplete_cookie_even_when_metadata_is_valid(
    client,
    app,
    monkeypatch,
):
    from services.runtime_cookie_service import RuntimeCookieService

    monkeypatch.setattr(
        RuntimeCookieService,
        "load_cookie_settings",
        staticmethod(lambda: {
            "SESSDATA": "",
            "bili_jct": "csrf-value",
            "buvid3": "buvid-value",
        }),
    )

    with app.app_context():
        db.session.add(CookieMetadata(
            role="admin",
            status="valid",
            source="qr_login",
            masked_uid="42",
            cookie_version=7,
            last_validated_at=get_beijing_now(),
        ))
        db.session.commit()

    response = client.get(
        "/internal/runtime/cookie",
        headers={"Authorization": "test-secret"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "invalid"
    assert payload["cookie"] == {}
    assert "缺少 SESSDATA" in payload["last_error"]


def test_runtime_heartbeat_persists_cookie_version(client, app):
    response = client.post(
        "/internal/runtime/heartbeat",
        headers={"Authorization": "test-secret"},
        json={
            "role": "danmaku-worker",
            "instance_id": "worker-cookie",
            "state": "running",
            "cookie_version": 5,
        },
    )
    assert response.status_code == 200

    with app.app_context():
        status = RuntimeStatus.query.filter_by(instance_id="worker-cookie").one()
        assert status.cookie_version == 5


def test_stale_worker_cookie_detection(app):
    from services.runtime_cookie_service import is_worker_cookie_stale

    with app.app_context():
        db.session.add(CookieMetadata(
            role="admin",
            status="valid",
            cookie_version=8,
            last_validated_at=get_beijing_now(),
        ))
        db.session.add(RuntimeStatus(
            role="danmaku-worker",
            instance_id="worker-stale",
            state="running",
            cookie_version=7,
            heartbeat_at=get_beijing_now() - timedelta(seconds=10),
        ))
        db.session.commit()

        status = RuntimeStatus.query.filter_by(instance_id="worker-stale").one()
        assert is_worker_cookie_stale(status) is True


def test_worker_cookie_provider_detects_reload(monkeypatch):
    from services.bilibili_live.cookies import RuntimeCookieProvider

    class FakeResponse:
        def __init__(self, payload, status=200):
            self._payload = payload
            self.status = status

        async def json(self):
            return self._payload

        async def text(self):
            return "ok"

    class FakeGetContext:
        def __init__(self, response):
            self.response = response

        async def __aenter__(self):
            return self.response

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

    class FakeSession:
        def __init__(self):
            self.responses = [
                {"status": "valid", "version": 1, "cookie": {"SESSDATA": "old"}},
                {"status": "valid", "version": 2, "cookie": {"SESSDATA": "new"}},
            ]

        def get(self, url, headers=None, timeout=None):
            return FakeGetContext(FakeResponse(self.responses.pop(0)))

    provider = RuntimeCookieProvider(
        base_url="https://web.test",
        secret="secret",
        session=FakeSession(),
    )

    first = provider.fetch_latest_sync()
    second = provider.fetch_latest_sync()

    assert first.version == 1
    assert second.version == 2
    assert provider.should_reload(current_version=1, latest=second) is True


def test_legacy_runtime_cookie_schema_is_migrated(app):
    from app import run_migrations

    with app.app_context():
        db.drop_all()
        db.session.execute(
            text(
                """
                CREATE TABLE cookie_metadata (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role VARCHAR(32) NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'unknown',
                    source VARCHAR(32),
                    masked_uid VARCHAR(32),
                    payload_json TEXT,
                    last_validated_at DATETIME,
                    last_error VARCHAR(512),
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        db.session.execute(
            text(
                """
                CREATE TABLE runtime_statuses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role VARCHAR(32) NOT NULL,
                    instance_id VARCHAR(64) NOT NULL,
                    state VARCHAR(32) NOT NULL DEFAULT 'unknown',
                    payload_json TEXT,
                    last_error VARCHAR(512),
                    delivery_error VARCHAR(512),
                    retry_count INTEGER DEFAULT 0,
                    last_event_at DATETIME,
                    heartbeat_at DATETIME,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        db.session.commit()

        run_migrations()

        cookie_columns = {
            row[1]
            for row in db.session.execute(text("PRAGMA table_info(cookie_metadata)"))
        }
        runtime_columns = {
            row[1]
            for row in db.session.execute(text("PRAGMA table_info(runtime_statuses)"))
        }
        assert "cookie_version" in cookie_columns
        assert "cookie_version" in runtime_columns

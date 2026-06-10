from datetime import timedelta

import pytest
from sqlalchemy import text

from db.models import CookieMetadata, db, get_beijing_now


TV_AUTH_PAYLOAD = {
    "mid": 42,
    "access_token": "access-secret",
    "refresh_token": "refresh-secret",
    "expires_in": 7776000,
    "cookie_info": {
        "cookies": [
            {
                "name": "SESSDATA",
                "value": "sess-secret",
                "expires": 1893456000,
            },
            {"name": "bili_jct", "value": "csrf-secret"},
            {"name": "buvid3", "value": "buvid-secret"},
            {"name": "DedeUserID", "value": "42"},
        ]
    },
}


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeHttpClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if not self.responses:
            raise AssertionError(f"unexpected GET {url}")
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if not self.responses:
            raise AssertionError(f"unexpected POST {url}")
        return self.responses.pop(0)


def test_parse_tv_auth_payload_extracts_refresh_credentials_and_web_cookie():
    from services.tv_auth_service import parse_tv_auth_payload

    parsed = parse_tv_auth_payload(TV_AUTH_PAYLOAD)

    assert parsed.mid == "42"
    assert parsed.access_token == "access-secret"
    assert parsed.refresh_token == "refresh-secret"
    assert parsed.cookie_map["SESSDATA"] == "sess-secret"
    assert parsed.cookie_map["bili_jct"] == "csrf-secret"
    assert parsed.cookie_map["buvid3"] == "buvid-secret"
    assert parsed.cookie_header.startswith("DedeUserID=42; ")
    assert parsed.sessdata_expires_at.isoformat().startswith("2030-01-01")


@pytest.mark.parametrize(
    "payload,error",
    [
        ({}, "access_token"),
        ({"access_token": "a"}, "refresh_token"),
        ({"access_token": "a", "refresh_token": "r"}, "SESSDATA"),
    ],
)
def test_parse_tv_auth_payload_rejects_missing_required_fields(payload, error):
    from services.tv_auth_service import parse_tv_auth_payload

    with pytest.raises(ValueError, match=error):
        parse_tv_auth_payload(payload)


def test_store_tv_auth_success_validates_cookie_saves_tokens_and_masks_status(
    app,
    monkeypatch,
):
    from services import tv_auth_service
    from services.tv_auth_service import store_tv_auth_success

    saved_settings = {}
    monkeypatch.setattr(
        tv_auth_service.CookieService,
        "load_settings",
        staticmethod(lambda: {"bilibili": {"SESSDATA": "old", "bili_jct": "old"}}),
    )
    monkeypatch.setattr(
        tv_auth_service.CookieService,
        "save_settings",
        staticmethod(lambda settings: saved_settings.update(settings) or True),
    )

    http = FakeHttpClient([
        FakeResponse({"code": 0, "data": {"isLogin": True, "uname": "tester", "mid": 42}})
    ])

    with app.app_context():
        status = store_tv_auth_success(TV_AUTH_PAYLOAD, http_client=http)

        metadata = CookieMetadata.query.filter_by(role="admin").one()
        assert metadata.status == "valid"
        assert metadata.source == "tv_auth"
        assert metadata.cookie_version == 1
        assert metadata.tv_access_token == "access-secret"
        assert metadata.tv_refresh_token == "refresh-secret"
        assert metadata.sessdata_expires_at.isoformat().startswith("2030-01-01")
        assert metadata.last_refresh_at is not None
        assert saved_settings["bilibili"]["SESSDATA"] == "sess-secret"
        assert saved_settings["bilibili"]["bili_jct"] == "csrf-secret"
        assert saved_settings["bilibili"]["buvid3"] == "buvid-secret"
        assert status["tv_auth"]["status"] == "valid"
        assert status["tv_auth"]["has_refresh_token"] is True
        assert "access-secret" not in str(status)
        assert "refresh-secret" not in str(status)
        assert "sess-secret" not in str(status)


def test_store_tv_auth_success_preserves_existing_cookie_when_validation_fails(
    app,
    monkeypatch,
):
    from services import tv_auth_service
    from services.tv_auth_service import store_tv_auth_success

    save_calls = []
    monkeypatch.setattr(
        tv_auth_service.CookieService,
        "load_settings",
        staticmethod(lambda: {"bilibili": {"SESSDATA": "old", "bili_jct": "old"}}),
    )
    monkeypatch.setattr(
        tv_auth_service.CookieService,
        "save_settings",
        staticmethod(lambda settings: save_calls.append(settings) or True),
    )

    http = FakeHttpClient([
        FakeResponse({"code": 0, "data": {"isLogin": False}, "message": "bad cookie"})
    ])

    with app.app_context():
        status = store_tv_auth_success(TV_AUTH_PAYLOAD, http_client=http)

        metadata = CookieMetadata.query.filter_by(role="admin").one()
        assert status["tv_auth"]["status"] == "invalid"
        assert metadata.status == "invalid"
        assert metadata.tv_access_token == ""
        assert metadata.tv_refresh_token == ""
        assert save_calls == []


def test_legacy_cookie_metadata_schema_gets_tv_auth_columns(app):
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
                    cookie_version INTEGER DEFAULT 0,
                    last_validated_at DATETIME,
                    last_error VARCHAR(512),
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        db.session.commit()

        run_migrations()

        columns = {
            row[1]
            for row in db.session.execute(text("PRAGMA table_info(cookie_metadata)"))
        }
        assert "tv_access_token" in columns
        assert "tv_refresh_token" in columns
        assert "sessdata_expires_at" in columns
        assert "last_refresh_at" in columns
        assert "tv_auth_payload_json" in columns


def test_tv_auth_status_reports_rescan_next_action_when_refresh_token_missing(app):
    from services.tv_auth_service import tv_auth_status_payload

    with app.app_context():
        db.session.add(
            CookieMetadata(
                role="admin",
                status="valid",
                source="tv_auth",
                cookie_version=3,
                sessdata_expires_at=get_beijing_now() + timedelta(days=3),
                tv_refresh_token="",
            )
        )
        db.session.commit()

        payload = tv_auth_status_payload()

    assert payload["status"] == "rescan_required"
    assert payload["has_refresh_token"] is False
    assert payload["next_action"] == "请重新扫码授权 B 站账号"


def test_start_tv_qr_login_persists_tv_task(app):
    from services.tv_auth_service import start_tv_qr_login

    http = FakeHttpClient([
        FakeResponse({
            "code": 0,
            "data": {
                "url": "https://passport.bilibili.com/tv/qrcode/test",
                "auth_code": "auth-code-1",
            },
        })
    ])

    with app.app_context():
        result = start_tv_qr_login(http_client=http)

        assert result["status"] == "pending"
        assert result["qr_url"] == "https://passport.bilibili.com/tv/qrcode/test"
        assert result["qrcode_key"] == "auth-code-1"
        assert result["tv_auth"]["status"] == "missing"


def test_poll_tv_qr_login_success_stores_tv_credentials(app, monkeypatch):
    from services import tv_auth_service
    from services.tv_auth_service import poll_tv_qr_login, start_tv_qr_login

    monkeypatch.setattr(
        tv_auth_service.CookieService,
        "load_settings",
        staticmethod(lambda: {"bilibili": {"SESSDATA": "old", "bili_jct": "old"}}),
    )
    monkeypatch.setattr(
        tv_auth_service.CookieService,
        "save_settings",
        staticmethod(lambda settings: True),
    )

    http = FakeHttpClient([
        FakeResponse({
            "code": 0,
            "data": {
                "url": "https://passport.bilibili.com/tv/qrcode/test",
                "auth_code": "auth-code-success",
            },
        }),
        FakeResponse({"code": 0, "data": {"code": 0, **TV_AUTH_PAYLOAD}}),
        FakeResponse({"code": 0, "data": {"isLogin": True, "uname": "tester", "mid": 42}}),
    ])

    with app.app_context():
        task = start_tv_qr_login(http_client=http)
        result = poll_tv_qr_login(task["task_id"], http_client=http)

        metadata = CookieMetadata.query.filter_by(role="admin").one()
        assert result["status"] == "succeeded"
        assert result["tv_auth"]["status"] == "valid"
        assert metadata.tv_refresh_token == "refresh-secret"


def test_poll_tv_qr_login_maps_waiting_and_expired_states(app):
    from services.tv_auth_service import poll_tv_qr_login, start_tv_qr_login

    http = FakeHttpClient([
        FakeResponse({
            "code": 0,
            "data": {
                "url": "https://passport.bilibili.com/tv/qrcode/test",
                "auth_code": "auth-code-wait",
            },
        }),
        FakeResponse({"code": 0, "data": {"code": 86039, "message": "not scanned"}}),
        FakeResponse({"code": 0, "data": {"code": 86090, "message": "scanned"}}),
        FakeResponse({"code": 0, "data": {"code": 86038, "message": "expired"}}),
    ])

    with app.app_context():
        task = start_tv_qr_login(http_client=http)
        assert poll_tv_qr_login(task["task_id"], http_client=http)["status"] == "pending"
        assert poll_tv_qr_login(task["task_id"], http_client=http)["status"] == "scanned"
        assert poll_tv_qr_login(task["task_id"], http_client=http)["status"] == "expired"

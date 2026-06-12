from db.models import CookieMetadata, QrLoginTask, db


class FakeResponse:
    def __init__(self, payload, cookies=None, status_code=200, text=None):
        self._payload = payload
        self.cookies = cookies or {}
        self.status_code = status_code
        self.text = text if text is not None else str(payload)

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeHttpClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError(f"unexpected GET {url}")
        return self.responses.pop(0)


def test_start_qr_login_persists_task(app):
    from services.bilibili_qr_service import start_qr_login

    http = FakeHttpClient([
        FakeResponse({
            "code": 0,
            "data": {
                "url": "https://passport.bilibili.com/qrcode/test",
                "qrcode_key": "key-123",
            },
        })
    ])

    with app.app_context():
        result = start_qr_login(http_client=http)

        assert result["status"] == "pending"
        assert result["qr_url"] == "https://passport.bilibili.com/qrcode/test"
        assert result["qrcode_key"] == "key-123"
        task = QrLoginTask.query.filter_by(task_id=result["task_id"]).one()
        assert task.status == "pending"
        assert task.qrcode_key == "key-123"
        assert "Chrome/132.0.0.0" in http.calls[0][1]["headers"]["User-Agent"]


def test_start_qr_login_reports_non_json_bilibili_response(app):
    import requests
    from services.bilibili_qr_service import start_qr_login

    http = FakeHttpClient([
        FakeResponse(
            requests.exceptions.JSONDecodeError("Expecting value", "", 0),
            status_code=412,
            text="<html>precondition failed</html>",
        )
    ])

    with app.app_context():
        try:
            start_qr_login(http_client=http)
        except RuntimeError as exc:
            assert "B 站二维码生成接口返回非 JSON 响应" in str(exc)
            assert "HTTP 412" in str(exc)
        else:
            raise AssertionError("start_qr_login should fail with readable non-JSON error")


def test_poll_qr_login_maps_waiting_states(app):
    from services.bilibili_qr_service import poll_qr_login, start_qr_login

    http = FakeHttpClient([
        FakeResponse({
            "code": 0,
            "data": {
                "url": "https://passport.bilibili.com/qrcode/test",
                "qrcode_key": "key-wait",
            },
        }),
        FakeResponse({"code": 0, "data": {"code": 86101, "message": "not scanned"}}),
        FakeResponse({"code": 0, "data": {"code": 86090, "message": "scanned"}}),
        FakeResponse({"code": 0, "data": {"code": 86038, "message": "expired"}}),
    ])

    with app.app_context():
        task = start_qr_login(http_client=http)
        assert poll_qr_login(task["task_id"], http_client=http)["status"] == "pending"
        assert poll_qr_login(task["task_id"], http_client=http)["status"] == "scanned"
        expired = poll_qr_login(task["task_id"], http_client=http)
        assert expired["status"] == "expired"
        assert QrLoginTask.query.filter_by(task_id=task["task_id"]).one().status == "expired"


def test_poll_qr_login_success_validates_and_saves_cookie(app, monkeypatch):
    from services import bilibili_qr_service
    from services.bilibili_qr_service import poll_qr_login, start_qr_login

    saved_settings = {}

    monkeypatch.setattr(
        bilibili_qr_service.CookieService,
        "load_settings",
        staticmethod(lambda: {"bilibili": {"SESSDATA": "old", "bili_jct": "old-csrf"}}),
    )
    monkeypatch.setattr(
        bilibili_qr_service.CookieService,
        "save_settings",
        staticmethod(lambda settings: saved_settings.update(settings) or True),
    )

    http = FakeHttpClient([
        FakeResponse({
            "code": 0,
            "data": {
                "url": "https://passport.bilibili.com/qrcode/test",
                "qrcode_key": "key-success",
            },
        }),
        FakeResponse(
            {"code": 0, "data": {"code": 0, "message": "ok", "url": "https://bilibili.com"}},
            cookies={
                "SESSDATA": "new-sess",
                "bili_jct": "new-csrf",
                "DedeUserID": "42",
                "DedeUserID__ckMd5": "ck-md5",
                "sid": "sid-value",
                "buvid3": "buvid-value",
            },
        ),
        FakeResponse({"code": 0, "data": {"isLogin": True, "uname": "tester", "mid": 42}}),
    ])

    with app.app_context():
        task = start_qr_login(http_client=http)
        result = poll_qr_login(task["task_id"], http_client=http)

        assert result["status"] == "succeeded"
        assert result["username"] == "tester"
        mirror = saved_settings["bilibili_auth_mirror"]
        assert mirror["source"] == "db.cookie_metadata"
        assert mirror["role"] == "admin"
        assert mirror["status"] == "valid"
        assert mirror["cookie_version"] == 1
        saved_cookie_header = mirror["cookie_header"]
        assert "SESSDATA=new-sess" in saved_cookie_header
        assert "bili_jct=new-csrf" in saved_cookie_header
        assert "DedeUserID=42" in saved_cookie_header
        assert "DedeUserID__ckMd5=ck-md5" in saved_cookie_header
        assert "sid=sid-value" in saved_cookie_header
        assert "buvid3=buvid-value" in saved_cookie_header
        metadata = CookieMetadata.query.filter_by(role="admin").one()
        assert metadata.status == "valid"
        assert metadata.masked_uid == "42"
        assert metadata.cookie_header == (
            "DedeUserID=42; DedeUserID__ckMd5=ck-md5; SESSDATA=new-sess; "
            "bili_jct=new-csrf; buvid3=buvid-value; sid=sid-value"
        )


def test_poll_qr_login_saves_web_refresh_token_only_after_valid_cookie(app, monkeypatch):
    from services import bilibili_qr_service
    from services.bilibili_qr_service import poll_qr_login, start_qr_login

    saved_settings = {}

    monkeypatch.setattr(
        bilibili_qr_service.CookieService,
        "load_settings",
        staticmethod(lambda: {"bilibili": {"SESSDATA": "old", "bili_jct": "old-csrf"}}),
    )
    monkeypatch.setattr(
        bilibili_qr_service.CookieService,
        "save_settings",
        staticmethod(lambda settings: saved_settings.update(settings) or True),
    )

    http = FakeHttpClient([
        FakeResponse({
            "code": 0,
            "data": {
                "url": "https://passport.bilibili.com/qrcode/test",
                "qrcode_key": "key-web-token",
            },
        }),
        FakeResponse(
            {
                "code": 0,
                "data": {
                    "code": 0,
                    "message": "ok",
                    "url": "https://bilibili.com",
                    "refresh_token": "web-refresh-secret",
                },
            },
            cookies={"SESSDATA": "new-sess", "bili_jct": "new-csrf", "DedeUserID": "42"},
        ),
        FakeResponse({"code": 0, "data": {"isLogin": True, "uname": "tester", "mid": 42}}),
    ])

    with app.app_context():
        task = start_qr_login(http_client=http)
        result = poll_qr_login(task["task_id"], http_client=http)

        metadata = CookieMetadata.query.filter_by(role="admin").one()
        assert result["status"] == "succeeded"
        assert metadata.source == "qr_login"
        assert metadata.web_refresh_token == "web-refresh-secret"
        assert metadata.cookie_header == "DedeUserID=42; SESSDATA=new-sess; bili_jct=new-csrf"
        assert "web-refresh-secret" not in str(result)


def test_poll_qr_login_does_not_replace_cookie_when_validation_fails(app, monkeypatch):
    from services import bilibili_qr_service
    from services.bilibili_qr_service import poll_qr_login, start_qr_login

    save_calls = []
    monkeypatch.setattr(
        bilibili_qr_service.CookieService,
        "load_settings",
        staticmethod(lambda: {"bilibili": {"SESSDATA": "old", "bili_jct": "old-csrf"}}),
    )
    monkeypatch.setattr(
        bilibili_qr_service.CookieService,
        "save_settings",
        staticmethod(lambda settings: save_calls.append(settings) or True),
    )

    http = FakeHttpClient([
        FakeResponse({
            "code": 0,
            "data": {
                "url": "https://passport.bilibili.com/qrcode/test",
                "qrcode_key": "key-invalid",
            },
        }),
        FakeResponse(
            {"code": 0, "data": {"code": 0, "message": "ok", "url": "https://bilibili.com"}},
            cookies={"SESSDATA": "bad-sess", "bili_jct": "bad-csrf"},
        ),
        FakeResponse({"code": 0, "data": {"isLogin": False}}),
    ])

    with app.app_context():
        task = start_qr_login(http_client=http)
        result = poll_qr_login(task["task_id"], http_client=http)

        assert result["status"] == "failed"
        assert save_calls == []
        metadata = CookieMetadata.query.filter_by(role="admin").one()
        assert metadata.status == "invalid"


def test_poll_qr_login_does_not_save_web_refresh_token_when_cookie_validation_fails(app, monkeypatch):
    from services import bilibili_qr_service
    from services.bilibili_qr_service import poll_qr_login, start_qr_login

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
                "qrcode_key": "key-invalid-web-token",
            },
        }),
        FakeResponse(
            {
                "code": 0,
                "data": {
                    "code": 0,
                    "message": "ok",
                    "url": "https://bilibili.com",
                    "refresh_token": "should-not-save",
                },
            },
            cookies={"SESSDATA": "bad-sess", "bili_jct": "bad-csrf"},
        ),
        FakeResponse({"code": 0, "data": {"isLogin": False}}),
    ])

    with app.app_context():
        task = start_qr_login(http_client=http)
        result = poll_qr_login(task["task_id"], http_client=http)

        metadata = CookieMetadata.query.filter_by(role="admin").one()
        assert result["status"] == "failed"
        assert metadata.status == "invalid"
        assert metadata.web_refresh_token in (None, "")


def test_poll_qr_login_unknown_status_is_preserved(app):
    from services.bilibili_qr_service import poll_qr_login, start_qr_login

    http = FakeHttpClient([
        FakeResponse({
            "code": 0,
            "data": {
                "url": "https://passport.bilibili.com/qrcode/test",
                "qrcode_key": "key-unknown",
            },
        }),
        FakeResponse({"code": 0, "data": {"code": 12345, "message": "new state"}}),
    ])

    with app.app_context():
        task = start_qr_login(http_client=http)
        result = poll_qr_login(task["task_id"], http_client=http)

        assert result["status"] == "unknown"
        assert result["message"] == "new state"


def test_poll_qr_login_persists_db_cookie_when_legacy_settings_sync_fails(app, monkeypatch):
    from services import bilibili_qr_service
    from services.bilibili_qr_service import poll_qr_login, start_qr_login

    monkeypatch.setattr(
        bilibili_qr_service.CookieService,
        "load_settings",
        staticmethod(lambda: {"bilibili": {"SESSDATA": "old", "bili_jct": "old-csrf"}}),
    )
    monkeypatch.setattr(
        bilibili_qr_service.CookieService,
        "save_settings",
        staticmethod(lambda settings: False),
    )

    http = FakeHttpClient([
        FakeResponse({
            "code": 0,
            "data": {
                "url": "https://passport.bilibili.com/qrcode/test",
                "qrcode_key": "key-save-fails",
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

        assert result["status"] == "succeeded"
        metadata = CookieMetadata.query.filter_by(role="admin").one()
        assert metadata.status == "valid"
        assert metadata.cookie_header == "DedeUserID=42; SESSDATA=new-sess; bili_jct=new-csrf"


def test_validate_cookie_header_rejects_missing_sessdata(app):
    from services.bilibili_qr_service import validate_cookie_header

    with app.app_context():
        result = validate_cookie_header("bili_jct=csrf")

    assert result["valid"] is False
    assert "SESSDATA" in result["message"]

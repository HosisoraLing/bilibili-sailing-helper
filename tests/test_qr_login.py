from db.models import CookieMetadata, QrLoginTask, db


class FakeResponse:
    def __init__(self, payload, cookies=None):
        self._payload = payload
        self.cookies = cookies or {}

    def json(self):
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
            cookies={"SESSDATA": "new-sess", "bili_jct": "new-csrf", "DedeUserID": "42"},
        ),
        FakeResponse({"code": 0, "data": {"isLogin": True, "uname": "tester", "mid": 42}}),
    ])

    with app.app_context():
        task = start_qr_login(http_client=http)
        result = poll_qr_login(task["task_id"], http_client=http)

        assert result["status"] == "succeeded"
        assert result["username"] == "tester"
        assert saved_settings["bilibili"]["SESSDATA"] == "new-sess"
        assert saved_settings["bilibili"]["bili_jct"] == "new-csrf"
        metadata = CookieMetadata.query.filter_by(role="admin").one()
        assert metadata.status == "valid"
        assert metadata.masked_uid == "42"


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


def test_poll_qr_login_unknown_status_is_failed(app):
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

        assert result["status"] == "failed"
        assert result["message"] == "new state"


def test_validate_cookie_header_rejects_missing_sessdata(app):
    from services.bilibili_qr_service import validate_cookie_header

    with app.app_context():
        result = validate_cookie_header("bili_jct=csrf")

    assert result["valid"] is False
    assert "SESSDATA" in result["message"]

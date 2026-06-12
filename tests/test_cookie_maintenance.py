from db.models import CookieMetadata, SchedulerJob, db, get_beijing_now


class FakeResponse:
    def __init__(self, payload, cookies=None, status_code=200, text=""):
        self._payload = payload
        self.cookies = cookies or {}
        self.status_code = status_code
        self.text = text

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


def _add_web_qr_metadata(**kwargs):
    defaults = {
        "role": "admin",
        "status": "valid",
        "source": "qr_login",
        "masked_uid": "42",
        "cookie_version": 5,
        "web_refresh_token": "old-web-refresh",
        "cookie_header": "SESSDATA=old-sess; bili_jct=old-csrf; DedeUserID=42",
        "last_validated_at": get_beijing_now(),
    }
    defaults.update(kwargs)
    metadata = CookieMetadata(**defaults)
    db.session.add(metadata)
    db.session.commit()
    return metadata


def test_cookie_maintenance_noops_when_web_cookie_refresh_not_required(app, monkeypatch):
    from services import bilibili_qr_service
    from services.cookie_maintenance_service import run_cookie_maintenance

    monkeypatch.setattr(
        bilibili_qr_service.CookieService,
        "load_settings",
        staticmethod(lambda: {"bilibili": {"SESSDATA": "settings-sess", "bili_jct": "settings-csrf"}}),
    )
    http = FakeHttpClient([
        FakeResponse({"code": 0, "data": {"refresh": False, "timestamp": 1700000000000}}),
    ])

    with app.app_context():
        _add_web_qr_metadata()

        result = run_cookie_maintenance(http_client=http)

        metadata = CookieMetadata.query.filter_by(role="admin").one()
        assert result["status"] == "success"
        assert result["action"] == "noop"
        assert metadata.cookie_version == 5
        assert http.calls[0][2]["headers"]["Cookie"].startswith("DedeUserID=42")
        assert "SESSDATA=old-sess" in http.calls[0][2]["headers"]["Cookie"]


def test_cookie_maintenance_refreshes_web_qr_cookie_and_advances_cookie_version(
    app,
    monkeypatch,
):
    from services import bilibili_qr_service
    from services.cookie_maintenance_service import run_cookie_maintenance

    saved_settings = {}
    monkeypatch.setattr(
        bilibili_qr_service.CookieService,
        "load_settings",
        staticmethod(lambda: {"bilibili": {"SESSDATA": "old-sess", "bili_jct": "old-csrf"}}),
    )
    monkeypatch.setattr(
        bilibili_qr_service.CookieService,
        "save_settings",
        staticmethod(lambda settings: saved_settings.update(settings) or True),
    )
    monkeypatch.setattr(
        bilibili_qr_service,
        "generate_correspond_path",
        lambda timestamp_ms=None: "correspond-path",
    )

    http = FakeHttpClient([
        FakeResponse({"code": 0, "data": {"refresh": True, "timestamp": 1700000000000}}),
        FakeResponse({}, text='<html><div id="1-name">refresh-csrf</div></html>'),
        FakeResponse(
            {"code": "0", "message": "0", "data": {"refresh_token": "new-web-refresh"}},
            cookies={
                "SESSDATA": "new-sess",
                "bili_jct": "new-csrf",
                "DedeUserID": "42",
                "DedeUserID__ckMd5": "ck-md5",
                "sid": "sid-value",
            },
        ),
        FakeResponse({"code": 0, "data": {"isLogin": True, "uname": "tester", "mid": 42}}),
        FakeResponse({"code": "0", "message": "0"}),
    ])

    with app.app_context():
        _add_web_qr_metadata()

        result = run_cookie_maintenance(http_client=http)

        metadata = CookieMetadata.query.filter_by(role="admin").one()
        assert result["status"] == "success"
        assert result["action"] == "refreshed"
        assert metadata.cookie_version == 6
        assert metadata.source == "qr_login"
        assert metadata.web_refresh_token == "new-web-refresh"
        assert metadata.last_refresh_at is not None
        db.session.expire_all()
        persisted = CookieMetadata.query.filter_by(role="admin").one()
        assert persisted.cookie_version == 6
        assert persisted.web_refresh_token == "new-web-refresh"
        mirror = saved_settings["bilibili_auth_mirror"]
        assert mirror["source"] == "db.cookie_metadata"
        assert mirror["status"] == "valid"
        assert mirror["cookie_version"] == 6
        assert "SESSDATA=new-sess" in mirror["cookie_header"]
        assert "bili_jct=new-csrf" in mirror["cookie_header"]
        assert "SESSDATA=old-sess" in http.calls[1][2]["headers"]["Cookie"]
        assert http.calls[2][2]["data"]["refresh_token"] == "old-web-refresh"
        assert http.calls[4][2]["data"]["refresh_token"] == "old-web-refresh"
        assert persisted.cookie_header == (
            "DedeUserID=42; DedeUserID__ckMd5=ck-md5; SESSDATA=new-sess; "
            "bili_jct=new-csrf; sid=sid-value"
        )


def test_cookie_maintenance_failure_preserves_last_usable_cookie(app, monkeypatch):
    from services import bilibili_qr_service
    from services.cookie_maintenance_service import run_cookie_maintenance

    save_calls = []
    monkeypatch.setattr(
        bilibili_qr_service.CookieService,
        "load_settings",
        staticmethod(lambda: {"bilibili": {"SESSDATA": "old-sess", "bili_jct": "old-csrf"}}),
    )
    monkeypatch.setattr(
        bilibili_qr_service.CookieService,
        "save_settings",
        staticmethod(lambda settings: save_calls.append(settings) or True),
    )
    monkeypatch.setattr(
        bilibili_qr_service,
        "generate_correspond_path",
        lambda timestamp_ms=None: "correspond-path",
    )

    http = FakeHttpClient([
        FakeResponse({"code": 0, "data": {"refresh": True, "timestamp": 1700000000000}}),
        FakeResponse({}, status_code=404, text="not found"),
    ])

    with app.app_context():
        _add_web_qr_metadata()

        result = run_cookie_maintenance(http_client=http)

        metadata = CookieMetadata.query.filter_by(role="admin").one()
        assert result["status"] == "failed"
        assert result["action"] == "rescan_required"
        assert "重新扫码" in result["next_action"]
        assert metadata.cookie_version == 5
        assert metadata.status == "rescan_required"
        assert metadata.last_error == "correspondPath 过期或错误"
        assert save_calls == []


def test_cookie_maintenance_keeps_valid_cookie_when_forced_refresh_is_rejected(
    app,
    monkeypatch,
):
    from services import bilibili_qr_service
    from services.cookie_maintenance_service import run_cookie_maintenance

    monkeypatch.setattr(
        bilibili_qr_service.CookieService,
        "load_settings",
        staticmethod(lambda: {"bilibili": {"SESSDATA": "old-sess", "bili_jct": "old-csrf"}}),
    )
    monkeypatch.setattr(
        bilibili_qr_service,
        "generate_correspond_path",
        lambda timestamp_ms=None: "correspond-path",
    )

    http = FakeHttpClient([
        FakeResponse({"code": 0, "data": {"refresh": True, "timestamp": 1700000000000}}),
        FakeResponse({}, text='<html><div id="1-name">refresh-csrf</div></html>'),
        FakeResponse({"code": -101, "message": "账号未登录"}),
        FakeResponse({"code": 0, "data": {"isLogin": True, "uname": "tester", "mid": 42}}),
    ])

    with app.app_context():
        _add_web_qr_metadata()

        result = run_cookie_maintenance(http_client=http)

        metadata = CookieMetadata.query.filter_by(role="admin").one()
        assert result["status"] == "failed"
        assert result["action"] == "refresh_rejected"
        assert metadata.status == "valid"
        assert metadata.cookie_version == 5
        assert metadata.last_error == "账号未登录"


def test_cookie_maintenance_requires_db_cookie_header(app):
    from services.cookie_maintenance_service import run_cookie_maintenance

    with app.app_context():
        _add_web_qr_metadata(cookie_header="")

        result = run_cookie_maintenance(http_client=FakeHttpClient([]))

        metadata = CookieMetadata.query.filter_by(role="admin").one()
        assert result["status"] == "failed"
        assert result["action"] == "rescan_required"
        assert metadata.status == "rescan_required"
        assert "SESSDATA" in metadata.last_error


def test_scheduler_cookie_maintenance_runs_web_refresh_service(app, monkeypatch):
    from routes import run_pending_scheduler_job
    import routes

    class FakeCookieMaintenanceService:
        @staticmethod
        def run_cookie_maintenance():
            return {
                "status": "success",
                "action": "refreshed",
                "summary": "cookie-maintenance refreshed Web QR Cookie",
                "next_action": "无需操作",
            }

    monkeypatch.setattr(routes, "CookieMaintenanceService", FakeCookieMaintenanceService)

    with app.app_context():
        job = SchedulerJob(
            job_id="cookie-maintenance-success",
            job_type="cookie-maintenance",
            status="requested",
        )
        db.session.add(job)
        db.session.commit()

        result = run_pending_scheduler_job(job)

        refreshed = SchedulerJob.query.filter_by(job_id="cookie-maintenance-success").one()
        assert result == {"executed": True, "job_status": "success"}
        assert refreshed.status == "success"
        assert "cookie-maintenance refreshed Web QR Cookie" in refreshed.result_json

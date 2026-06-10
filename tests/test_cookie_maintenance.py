from datetime import timedelta

from db.models import CookieMetadata, SchedulerJob, db, get_beijing_now


TV_REFRESH_PAYLOAD = {
    "mid": 42,
    "token_info": {
        "access_token": "new-access",
        "refresh_token": "new-refresh",
        "expires_in": 7776000,
    },
    "cookie_info": {
        "cookies": [
            {
                "name": "SESSDATA",
                "value": "new-sess",
                "expires": 1893456000,
            },
            {"name": "bili_jct", "value": "new-csrf"},
            {"name": "buvid3", "value": "new-buvid"},
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


def _add_tv_metadata(**kwargs):
    defaults = {
        "role": "admin",
        "status": "valid",
        "source": "tv_auth",
        "masked_uid": "42",
        "cookie_version": 5,
        "tv_access_token": "old-access",
        "tv_refresh_token": "old-refresh",
        "sessdata_expires_at": get_beijing_now() + timedelta(days=30),
        "last_validated_at": get_beijing_now(),
    }
    defaults.update(kwargs)
    metadata = CookieMetadata(**defaults)
    db.session.add(metadata)
    db.session.commit()
    return metadata


def test_cookie_maintenance_noops_when_sessdata_is_not_near_expiry(app):
    from services.cookie_maintenance_service import run_cookie_maintenance

    with app.app_context():
        _add_tv_metadata(sessdata_expires_at=get_beijing_now() + timedelta(days=30))

        result = run_cookie_maintenance(refresh_threshold_days=10)

        metadata = CookieMetadata.query.filter_by(role="admin").one()
        assert result["status"] == "success"
        assert result["action"] == "noop"
        assert metadata.cookie_version == 5


def test_cookie_maintenance_refreshes_expiring_tv_auth_and_advances_cookie_version(
    app,
    monkeypatch,
):
    from services import tv_auth_service
    from services.cookie_maintenance_service import run_cookie_maintenance

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
        FakeResponse({"code": 0, "data": TV_REFRESH_PAYLOAD}),
        FakeResponse({"code": 0, "data": {"isLogin": True, "uname": "tester", "mid": 42}}),
    ])

    with app.app_context():
        _add_tv_metadata(sessdata_expires_at=get_beijing_now() + timedelta(days=3))

        result = run_cookie_maintenance(http_client=http, refresh_threshold_days=10)

        metadata = CookieMetadata.query.filter_by(role="admin").one()
        assert result["status"] == "success"
        assert result["action"] == "refreshed"
        assert metadata.cookie_version == 6
        assert metadata.tv_access_token == "new-access"
        assert metadata.tv_refresh_token == "new-refresh"
        assert saved_settings["bilibili"]["SESSDATA"] == "new-sess"


def test_cookie_maintenance_failure_preserves_last_usable_cookie(app, monkeypatch):
    from services import tv_auth_service
    from services.cookie_maintenance_service import run_cookie_maintenance

    save_calls = []
    monkeypatch.setattr(
        tv_auth_service.CookieService,
        "save_settings",
        staticmethod(lambda settings: save_calls.append(settings) or True),
    )

    http = FakeHttpClient([
        FakeResponse({"code": -101, "message": "refresh token expired"}),
    ])

    with app.app_context():
        _add_tv_metadata(sessdata_expires_at=get_beijing_now() + timedelta(days=3))

        result = run_cookie_maintenance(http_client=http, refresh_threshold_days=10)

        metadata = CookieMetadata.query.filter_by(role="admin").one()
        assert result["status"] == "failed"
        assert result["action"] == "rescan_required"
        assert "重新扫码" in result["next_action"]
        assert metadata.cookie_version == 5
        assert metadata.status == "rescan_required"
        assert metadata.last_error == "refresh token expired"
        assert save_calls == []


def test_scheduler_cookie_maintenance_reaches_terminal_success(app, monkeypatch):
    from routes import run_pending_scheduler_job
    import routes

    class FakeCookieMaintenanceService:
        @staticmethod
        def run_cookie_maintenance():
            return {"status": "success", "action": "noop", "summary": "cookie-maintenance noop"}

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
        assert "cookie-maintenance noop" in refreshed.result_json

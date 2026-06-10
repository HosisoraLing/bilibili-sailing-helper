from datetime import timedelta

from sqlalchemy import text

from services import internal_api_service
from services.internal_api_service import is_runtime_status_stale
from db.models import (
    AuthSession,
    CookieMetadata,
    RuntimeStatus,
    SchedulerJob,
    User,
    db,
    get_beijing_now,
)


def test_internal_api_rejects_missing_secret(client):
    response = client.post(
        "/internal/runtime/heartbeat",
        json={"role": "danmaku-worker"},
    )
    assert response.status_code == 401


def test_internal_api_rejects_wrong_secret(client):
    response = client.post(
        "/internal/runtime/heartbeat",
        headers={"Authorization": "wrong-secret"},
        json={"role": "danmaku-worker"},
    )
    assert response.status_code == 401


def test_internal_api_secret_is_loaded_from_config(client):
    response = client.post(
        "/internal/runtime/heartbeat",
        headers={"Authorization": "test-secret"},
        json={"role": "danmaku-worker", "instance_id": "from-config", "state": "running"},
    )
    assert response.status_code == 200


def test_internal_api_accepts_runtime_heartbeat(client, app):
    response = client.post(
        "/internal/runtime/heartbeat",
        headers={"Authorization": "test-secret"},
        json={
            "role": "danmaku-worker",
            "instance_id": "test-1",
            "state": "running",
            "last_event_at": "2026-06-10T00:00:00+08:00",
            "last_error": "",
            "delivery_error": "",
            "retry_count": 2,
        },
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"

    with app.app_context():
        status = RuntimeStatus.query.filter_by(role="danmaku-worker").one()
        assert status.instance_id == "test-1"
        assert status.state == "running"
        assert status.last_event_at is not None
        assert status.last_error == ""
        assert status.delivery_error == ""
        assert status.retry_count == 2


def test_runtime_status_stale_heartbeat_detection(app):
    with app.app_context():
        status = RuntimeStatus(
            role="danmaku-worker",
            instance_id="old-worker",
            state="running",
            heartbeat_at=get_beijing_now() - timedelta(seconds=91),
        )
        db.session.add(status)
        db.session.commit()

        assert is_runtime_status_stale(status, threshold_seconds=90) is True


def test_runtime_status_keeps_roles_separate(client, app):
    for role in ("danmaku-worker", "scheduler"):
        response = client.post(
            "/internal/runtime/heartbeat",
            headers={"Authorization": "test-secret"},
            json={"role": role, "instance_id": "same-id", "state": "running"},
        )
        assert response.status_code == 200

    with app.app_context():
        statuses = RuntimeStatus.query.filter_by(instance_id="same-id").all()
        assert {status.role for status in statuses} == {"danmaku-worker", "scheduler"}


def test_admin_cookie_status_reports_runtime_health_and_next_action(client, app, monkeypatch):
    with app.app_context():
        admin = User(uid="admin-1", nickname="admin")
        admin.add_role("admin")
        db.session.add(admin)
        db.session.add(
            CookieMetadata(
                role="admin",
                status="valid",
                cookie_version=3,
                masked_uid="12***34",
                last_validated_at=get_beijing_now(),
            )
        )
        db.session.add(
            RuntimeStatus(
                role="danmaku-worker",
                instance_id="worker-1",
                state="running",
                retry_count=1,
                cookie_version=2,
                last_error="",
                delivery_error="",
                last_event_at=get_beijing_now() - timedelta(seconds=10),
                heartbeat_at=get_beijing_now() - timedelta(seconds=20),
            )
        )
        db.session.add(
            RuntimeStatus(
                role="scheduler",
                instance_id="scheduler-1",
                state="running",
                heartbeat_at=get_beijing_now() - timedelta(seconds=5),
            )
        )
        db.session.commit()
        admin_id = admin.id

    with client.session_transaction() as flask_session:
        flask_session["_user_id"] = str(admin_id)

    monkeypatch.setattr(
        "services.cookie_service.CookieService.load_settings",
        lambda: {
            "bilibili": {
                "SESSDATA": "sess",
                "bili_jct": "csrf",
                "buvid3": "buvid",
            }
        },
    )
    monkeypatch.setattr(
        "services.cookie_service.CookieService.validate_cookie",
        lambda _sessdata: (True, "tester"),
    )

    response = client.get("/admin/cookie/status")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["runtime"]["active_cookie_version"] == 3
    assert payload["runtime"]["worker_cookie_stale"] is True
    assert payload["runtime"]["next_action"] == "等待 danmaku-worker 重新加载 Cookie"
    assert payload["runtime"]["roles"]["danmaku-worker"]["heartbeat_age_seconds"] >= 20
    assert payload["runtime"]["roles"]["danmaku-worker"]["last_event_at"]
    assert payload["listener"]["role"] == "danmaku-worker"


def test_auth_status_reports_listener_unavailable_for_pending_session(client, app):
    with app.app_context():
        db.session.add(
            AuthSession(
                uid="listener-down",
                code="vc-down",
                status="pending",
                expires_at=get_beijing_now() + timedelta(minutes=5),
            )
        )
        db.session.add(
            RuntimeStatus(
                role="danmaku-worker",
                instance_id="worker-down",
                state="failed",
                last_error="connect failed",
                heartbeat_at=get_beijing_now() - timedelta(seconds=10),
            )
        )
        db.session.commit()

    response = client.get("/auth/status?uid=listener-down")

    assert response.status_code == 503
    payload = response.get_json()
    assert payload["status"] == "listener_unavailable"
    assert payload["next_action"] == "管理员需要检查 danmaku-worker"


def test_auth_status_reports_retrying_for_reconnecting_worker(client, app):
    with app.app_context():
        db.session.add(
            AuthSession(
                uid="retrying-user",
                code="vc-retry",
                status="pending",
                expires_at=get_beijing_now() + timedelta(minutes=5),
            )
        )
        db.session.add(
            RuntimeStatus(
                role="danmaku-worker",
                instance_id="worker-retry",
                state="reconnecting",
                retry_count=2,
                last_error="temporary disconnect",
                heartbeat_at=get_beijing_now() - timedelta(seconds=3),
            )
        )
        db.session.commit()

    response = client.get("/auth/status?uid=retrying-user")

    assert response.status_code == 202
    payload = response.get_json()
    assert payload["status"] == "retrying"
    assert payload["retry_count"] == 2


def test_auth_status_reports_delivery_delay_for_queue_full_worker(client, app):
    with app.app_context():
        db.session.add(
            AuthSession(
                uid="queue-full-user",
                code="vc-queue",
                status="pending",
                expires_at=get_beijing_now() + timedelta(minutes=5),
            )
        )
        db.session.add(
            RuntimeStatus(
                role="danmaku-worker",
                instance_id="worker-queue",
                state="queue_full",
                retry_count=1,
                delivery_error="auth event queue full",
                heartbeat_at=get_beijing_now() - timedelta(seconds=3),
            )
        )
        db.session.commit()

    response = client.get("/auth/status?uid=queue-full-user")

    assert response.status_code == 202
    payload = response.get_json()
    assert payload["status"] == "internal_delivery_delayed"
    assert payload["retry_count"] == 1


def test_danmaku_webhook_marks_auth_success(client, app):
    with app.app_context():
        session = AuthSession(
            uid="42",
            code="vc-abc123def0",
            status="pending",
            expires_at=get_beijing_now() + timedelta(minutes=5),
        )
        db.session.add(session)
        db.session.commit()

    response = client.post(
        "/internal/danmaku/auth-event",
        headers={"Authorization": "test-secret"},
        json={
            "uid": "42",
            "nickname": "tester",
            "content": "vc-abc123def0",
            "room_id": 123,
            "event_ts": "2026-06-10T00:00:00+08:00",
        },
    )
    assert response.status_code == 200
    assert response.get_json()["matched"] is True

    with app.app_context():
        session = AuthSession.query.filter_by(uid="42").one()
        assert session.status == "success"


def test_danmaku_webhook_ignores_non_matching_code(client, app):
    with app.app_context():
        session = AuthSession(
            uid="43",
            code="vc-expected",
            status="pending",
            expires_at=get_beijing_now() + timedelta(minutes=5),
        )
        db.session.add(session)
        db.session.commit()

    response = client.post(
        "/internal/danmaku/auth-event",
        headers={"Authorization": "test-secret"},
        json={
            "uid": "43",
            "nickname": "tester",
            "content": "vc-other",
            "room_id": 123,
            "event_ts": "2026-06-10T00:00:00+08:00",
        },
    )
    assert response.status_code == 200
    assert response.get_json()["matched"] is False

    with app.app_context():
        session = AuthSession.query.filter_by(uid="43").one()
        assert session.status == "pending"


def test_danmaku_webhook_rejects_stale_code_after_session_code_rotates(client, app):
    with app.app_context():
        session = AuthSession(
            uid="45",
            code="vc-old",
            status="pending",
            expires_at=get_beijing_now() + timedelta(minutes=5),
        )
        db.session.add(session)
        db.session.commit()

        # Simulate code rotation after a stale danmaku event was matched.
        session.code = "vc-new"
        db.session.commit()

    response = client.post(
        "/internal/danmaku/auth-event",
        headers={"Authorization": "test-secret"},
        json={
            "uid": "45",
            "nickname": "tester",
            "content": "vc-old",
            "room_id": 123,
            "event_ts": "2026-06-10T00:00:00+08:00",
        },
    )
    assert response.status_code == 200
    assert response.get_json()["matched"] is False

    with app.app_context():
        session = AuthSession.query.filter_by(uid="45").one()
        assert session.status == "pending"


def test_danmaku_webhook_reports_false_when_success_transition_fails(
    client,
    app,
    monkeypatch,
):
    with app.app_context():
        session = AuthSession(
            uid="44",
            code="vc-race",
            status="pending",
            expires_at=get_beijing_now() + timedelta(minutes=5),
        )
        db.session.add(session)
        db.session.commit()

    monkeypatch.setattr(
        internal_api_service,
        "mark_auth_success",
        lambda session, expected_code=None: False,
    )

    response = client.post(
        "/internal/danmaku/auth-event",
        headers={"Authorization": "test-secret"},
        json={
            "uid": "44",
            "nickname": "tester",
            "content": "vc-race",
            "room_id": 123,
            "event_ts": "2026-06-10T00:00:00+08:00",
        },
    )
    assert response.status_code == 200
    assert response.get_json()["matched"] is False

    with app.app_context():
        attempt = db.session.query(internal_api_service.AuthAttempt).filter_by(uid="44").one()
        assert attempt.status == "conflict"


def test_runtime_heartbeat_preserves_previous_error_fields_when_omitted(client, app):
    first = client.post(
        "/internal/runtime/heartbeat",
        headers={"Authorization": "test-secret"},
        json={
            "role": "danmaku-worker",
            "instance_id": "preserve-errors",
            "state": "degraded",
            "last_error": "ws disconnected",
            "delivery_error": "web unavailable",
            "retry_count": 3,
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/internal/runtime/heartbeat",
        headers={"Authorization": "test-secret"},
        json={
            "role": "danmaku-worker",
            "instance_id": "preserve-errors",
            "state": "running",
        },
    )
    assert second.status_code == 200

    with app.app_context():
        status = RuntimeStatus.query.filter_by(instance_id="preserve-errors").one()
        assert status.state == "running"
        assert status.last_error == "ws disconnected"
        assert status.delivery_error == "web unavailable"
        assert status.retry_count == 3


def test_internal_scheduler_job_records_request_and_result(client, app, monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "fetch_and_save_guards", lambda: None)

    job_response = client.post(
        "/internal/scheduler/job",
        headers={"Authorization": "test-secret"},
        json={
            "job_name": "guard-sync",
            "requested_at": "2026-06-10T00:00:00+08:00",
            "parameters": {"force": True},
        },
    )
    assert job_response.status_code == 200
    job_id = job_response.get_json()["job_id"]

    result_response = client.post(
        "/internal/scheduler/result",
        headers={"Authorization": "test-secret"},
        json={
            "job_id": job_id,
            "job_name": "guard-sync",
            "status": "success",
            "started_at": "2026-06-10T00:00:01+08:00",
            "finished_at": "2026-06-10T00:00:02+08:00",
            "summary": "synced",
            "error": "",
        },
    )
    assert result_response.status_code == 200

    with app.app_context():
        job = SchedulerJob.query.filter_by(job_id=job_id).one()
        assert job.job_type == "guard-sync"
        assert job.status == "success"
        assert "synced" in job.result_json


def test_internal_scheduler_job_accepts_guard_sync_without_running_network_task(
    client,
    app,
    monkeypatch,
):
    import app as app_module

    def fake_fetch_and_save_guards():
        raise AssertionError("guard-sync must not run inside the scheduler request")

    monkeypatch.setattr(app_module, "fetch_and_save_guards", fake_fetch_and_save_guards)

    job_response = client.post(
        "/internal/scheduler/job",
        headers={"Authorization": "test-secret"},
        json={
            "job_name": "guard-sync",
            "requested_at": "2026-06-10T00:00:00+08:00",
        },
    )
    assert job_response.status_code == 200
    payload = job_response.get_json()
    assert payload["job_status"] == "requested"
    assert payload["accepted"] is True

    with app.app_context():
        job = SchedulerJob.query.filter_by(job_id=job_response.get_json()["job_id"]).one()
        assert job.status == "requested"


def test_run_pending_scheduler_job_executes_guard_sync_inside_web(app, monkeypatch):
    import app as app_module
    from routes import run_pending_scheduler_job

    calls = []

    def fake_fetch_and_save_guards():
        calls.append("guard-sync")

    monkeypatch.setattr(app_module, "fetch_and_save_guards", fake_fetch_and_save_guards)

    with app.app_context():
        job = SchedulerJob(job_id="guard-job-1", job_type="guard-sync", status="requested")
        db.session.add(job)
        db.session.commit()

        result = run_pending_scheduler_job(job)

        assert result == {"executed": True, "job_status": "success"}
        assert calls == ["guard-sync"]
        refreshed = SchedulerJob.query.filter_by(job_id="guard-job-1").one()
        assert refreshed.status == "success"
        assert "guard-sync completed" in refreshed.result_json


def test_internal_scheduler_result_can_record_by_job_name_without_job_id(client, app):
    job_response = client.post(
        "/internal/scheduler/job",
        headers={"Authorization": "test-secret"},
        json={
            "job_name": "cookie-refresh",
            "requested_at": "2026-06-10T00:00:00+08:00",
        },
    )
    assert job_response.status_code == 200

    result_response = client.post(
        "/internal/scheduler/result",
        headers={"Authorization": "test-secret"},
        json={
            "job_name": "cookie-refresh",
            "status": "success",
            "started_at": "2026-06-10T00:00:01+08:00",
            "finished_at": "2026-06-10T00:00:02+08:00",
            "summary": "refreshed",
            "error": "",
        },
    )
    assert result_response.status_code == 200

    with app.app_context():
        job = SchedulerJob.query.filter_by(job_type="cookie-refresh").one()
        assert job.status == "success"
        assert "refreshed" in job.result_json


def test_internal_scheduler_job_is_idempotent_for_duplicate_job_id(client, app, monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "fetch_and_save_guards", lambda: None)

    payload = {
        "job_id": "fixed-job-id",
        "job_name": "guard-sync",
        "requested_at": "2026-06-10T00:00:00+08:00",
        "parameters": {"force": True},
    }
    first = client.post(
        "/internal/scheduler/job",
        headers={"Authorization": "test-secret"},
        json=payload,
    )
    second = client.post(
        "/internal/scheduler/job",
        headers={"Authorization": "test-secret"},
        json=payload,
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.get_json()["job_id"] == "fixed-job-id"

    with app.app_context():
        assert SchedulerJob.query.filter_by(job_id="fixed-job-id").count() == 1


def test_internal_scheduler_result_requires_job_id_or_job_name(client):
    response = client.post(
        "/internal/scheduler/result",
        headers={"Authorization": "test-secret"},
        json={"status": "success"},
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "job_id or job_name is required"


def test_internal_scheduler_result_rejects_mismatched_job_name(client, monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "fetch_and_save_guards", lambda: None)

    job_response = client.post(
        "/internal/scheduler/job",
        headers={"Authorization": "test-secret"},
        json={"job_id": "job-mismatch", "job_name": "guard-sync"},
    )
    assert job_response.status_code == 200

    result_response = client.post(
        "/internal/scheduler/result",
        headers={"Authorization": "test-secret"},
        json={"job_id": "job-mismatch", "job_name": "cookie-refresh", "status": "success"},
    )
    assert result_response.status_code == 409
    assert result_response.get_json()["error"] == "job_name_mismatch"


def test_legacy_runtime_status_schema_is_migrated(app):
    from app import run_migrations

    with app.app_context():
        db.drop_all()
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

        columns = {
            row[1]
            for row in db.session.execute(text("PRAGMA table_info(runtime_statuses)"))
        }
        assert {"delivery_error", "retry_count"} <= columns

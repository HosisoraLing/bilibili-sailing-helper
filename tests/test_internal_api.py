from datetime import timedelta

from sqlalchemy import text

from services import internal_api_service
from services.internal_api_service import is_runtime_status_stale
from db.models import AuthSession, RuntimeStatus, SchedulerJob, db, get_beijing_now


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


def test_internal_scheduler_job_records_request_and_result(client, app):
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


def test_internal_scheduler_job_is_idempotent_for_duplicate_job_id(client, app):
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


def test_internal_scheduler_result_rejects_mismatched_job_name(client):
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

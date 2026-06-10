import hmac
import json
import uuid
from datetime import datetime
from typing import Any

from flask import current_app

from db.models import (
    AuthAttempt,
    AuthSession,
    RuntimeStatus,
    SchedulerJob,
    db,
    get_beijing_now,
)
from services.auth_service import mark_auth_success


class ConflictError(ValueError):
    pass


def verify_internal_secret(provided_secret: str | None) -> bool:
    expected_secret = current_app.config.get("INTERNAL_API_SECRET") or ""
    if not expected_secret or not provided_secret:
        return False
    return hmac.compare_digest(str(provided_secret), str(expected_secret))


def parse_datetime(value: Any):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed.replace(tzinfo=None)
    return None


def to_json_text(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def record_runtime_heartbeat(payload: dict[str, Any]) -> RuntimeStatus:
    role = str(payload.get("role") or "").strip()
    instance_id = str(payload.get("instance_id") or "").strip()
    state = str(payload.get("state") or "unknown").strip()
    if not role or not instance_id:
        raise ValueError("role and instance_id are required")

    status = RuntimeStatus.query.filter_by(
        role=role,
        instance_id=instance_id,
    ).first()
    if status is None:
        status = RuntimeStatus(role=role, instance_id=instance_id)
        db.session.add(status)

    status.state = state
    status.payload_json = to_json_text(payload)
    if "last_error" in payload:
        status.last_error = payload.get("last_error") or ""
    if "delivery_error" in payload:
        status.delivery_error = payload.get("delivery_error") or ""
    if "retry_count" in payload:
        status.retry_count = int(payload.get("retry_count") or 0)
    if "cookie_version" in payload:
        status.cookie_version = int(payload.get("cookie_version") or 0)
    if "last_event_at" in payload:
        status.last_event_at = parse_datetime(payload.get("last_event_at"))
    status.heartbeat_at = get_beijing_now()
    db.session.commit()
    return status


def is_runtime_status_stale(
    status: RuntimeStatus,
    threshold_seconds: int = 90,
) -> bool:
    if not status.heartbeat_at:
        return True
    age = get_beijing_now() - status.heartbeat_at
    return age.total_seconds() > threshold_seconds


def process_danmaku_auth_event(payload: dict[str, Any]) -> dict[str, Any]:
    uid = str(payload.get("uid") or "").strip()
    content = str(payload.get("content") or "").strip()
    if not uid or not content:
        raise ValueError("uid and content are required")

    session = AuthSession.query.filter_by(
        uid=uid,
        status="pending",
        code=content,
    ).order_by(AuthSession.created_at.desc()).first()
    matched = bool(session and not session.is_expired())

    attempt = AuthAttempt(
        session_id=session.id if session else None,
        uid=uid,
        status="matched" if matched else "ignored",
        code=content,
        nickname=payload.get("nickname") or "",
        room_id=str(payload.get("room_id") or ""),
        payload_json=to_json_text(payload),
    )
    db.session.add(attempt)

    if matched:
        matched = mark_auth_success(session, expected_code=content)
        if not matched:
            attempt.status = "conflict"
            db.session.commit()
    else:
        db.session.commit()

    return {"matched": matched, "uid": uid}


def create_scheduler_job(payload: dict[str, Any]) -> SchedulerJob:
    job_name = str(payload.get("job_name") or "").strip()
    if not job_name:
        raise ValueError("job_name is required")

    job_id = str(payload.get("job_id") or uuid.uuid4())
    job = SchedulerJob.query.filter_by(job_id=job_id).first()
    if job is None:
        job = SchedulerJob(job_id=job_id)
        db.session.add(job)
    elif job.job_type and job.job_type != job_name:
        raise ConflictError("job_name_mismatch")

    job.job_type = job_name
    job.status = "requested"
    job.payload_json = to_json_text(payload.get("parameters") or payload)
    job.scheduled_at = parse_datetime(payload.get("requested_at"))
    db.session.commit()
    return job


def record_scheduler_result(payload: dict[str, Any]) -> SchedulerJob:
    job_id = str(payload.get("job_id") or "").strip()
    job_name = str(payload.get("job_name") or "").strip()
    if not job_id and not job_name:
        raise ValueError("job_id or job_name is required")

    if job_id:
        job = SchedulerJob.query.filter_by(job_id=job_id).first()
    else:
        job = SchedulerJob.query.filter_by(job_type=job_name).order_by(
            SchedulerJob.created_at.desc()
        ).first()

    if job is None:
        job = SchedulerJob(
            job_id=job_id or str(uuid.uuid4()),
            job_type=job_name,
            status="requested",
        )
        db.session.add(job)
    elif job_name and job.job_type and job.job_type != job_name:
        raise ConflictError("job_name_mismatch")

    job.job_type = job_name or job.job_type
    job.status = str(payload.get("status") or "unknown")
    job.started_at = parse_datetime(payload.get("started_at"))
    job.finished_at = parse_datetime(payload.get("finished_at"))
    job.result_json = to_json_text({
        "summary": payload.get("summary") or "",
        "error": payload.get("error") or "",
    })
    job.last_error = payload.get("error") or ""
    db.session.commit()
    return job

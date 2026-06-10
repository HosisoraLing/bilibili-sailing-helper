import os
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import text

import db.models as model_module
import services.auth_service as auth_service
from db.models import AuthSession, db, get_beijing_now
from services.auth_service import (
    create_auth_session,
    get_active_auth_session,
    mark_auth_success,
)


def test_config_uses_isolated_settings_file(app):
    import config

    repo_settings_path = Path(__file__).resolve().parents[1] / "settings.json"
    assert config.SETTINGS_PATH == os.environ["BILIBILI_SAILING_SETTINGS"]
    assert Path(config.SETTINGS_PATH) != repo_settings_path


def test_success_session_remains_visible(app):
    with app.app_context():
        session, code = create_auth_session("1001")
        assert session.code == code

        assert mark_auth_success(session) is True
        assert session.succeeded_at is not None

        active = get_active_auth_session("1001")
        assert active is not None
        assert active.status == "success"
        assert active.code == code


def test_expired_session_is_rejected(app):
    with app.app_context():
        session = AuthSession(
            uid="1002",
            status="pending",
            expires_at=get_beijing_now() - timedelta(seconds=1),
        )
        db.session.add(session)
        db.session.commit()

        assert mark_auth_success(session) is False
        assert session.status == "expired"


def test_session_expiry_is_checked_in_atomic_success_update(app, monkeypatch):
    before_expiry = datetime(2026, 1, 1, 12, 0, 0)
    expires_at = before_expiry + timedelta(seconds=1)
    after_expiry = expires_at + timedelta(seconds=1)
    model_times = iter([before_expiry, after_expiry])
    auth_times = iter([before_expiry, after_expiry])

    monkeypatch.setattr(
        model_module,
        "get_beijing_now",
        lambda: next(model_times, after_expiry),
    )
    monkeypatch.setattr(
        auth_service,
        "get_beijing_now",
        lambda: next(auth_times, after_expiry),
    )

    with app.app_context():
        session = AuthSession(
            uid="1006",
            code="vc-expiring",
            status="pending",
            expires_at=expires_at,
        )
        db.session.add(session)
        db.session.commit()

        assert mark_auth_success(session) is False
        assert session.status == "expired"


def test_duplicate_success_only_wins_once(app):
    with app.app_context():
        session, _ = create_auth_session("1003")
        assert mark_auth_success(session) is True
        assert mark_auth_success(session) is False


def test_consumed_session_is_rejected(app):
    with app.app_context():
        session = AuthSession(
            uid="1004",
            code="vc-consumed",
            status="consumed",
            expires_at=get_beijing_now() + timedelta(minutes=5),
            consumed_at=get_beijing_now(),
        )
        db.session.add(session)
        db.session.commit()

        assert mark_auth_success(session) is False
        assert session.status == "consumed"


def test_legacy_auth_session_schema_is_migrated(app):
    from app import run_migrations

    with app.app_context():
        db.drop_all()
        db.session.execute(
            text(
                """
                CREATE TABLE auth_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid VARCHAR(32) NOT NULL,
                    status VARCHAR(16) NOT NULL DEFAULT 'pending',
                    expires_at DATETIME NOT NULL,
                    created_at DATETIME
                )
                """
            )
        )
        db.session.commit()

        run_migrations()

        session, code = create_auth_session("1005")
        assert session.code == code

        columns = {
            row[1]
            for row in db.session.execute(text("PRAGMA table_info(auth_sessions)"))
        }
        assert {"code", "succeeded_at", "consumed_at", "last_attempt_at"} <= columns

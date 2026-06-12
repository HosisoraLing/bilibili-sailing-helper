import json
import sqlite3
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "migrate_legacy_db.py"


def create_upstream_like_db(path: Path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE guards (
                uid VARCHAR(32) PRIMARY KEY,
                nickname VARCHAR(64) NOT NULL,
                last_guard_date DATE NOT NULL,
                in_guard BOOLEAN DEFAULT 1,
                guard_level VARCHAR(16) DEFAULT 'guard',
                accompany_days INTEGER DEFAULT 0,
                updated_at DATETIME
            );
            CREATE TABLE addresses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid VARCHAR(32) NOT NULL UNIQUE,
                nickname VARCHAR(64) NOT NULL,
                province VARCHAR(32),
                city VARCHAR(32),
                area VARCHAR(32),
                address VARCHAR(256),
                receiver VARCHAR(64),
                phone VARCHAR(32),
                last_guard_date DATE,
                submitted_at DATETIME,
                guard_level VARCHAR(16) DEFAULT 'guard'
            );
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid VARCHAR(32) UNIQUE NOT NULL,
                nickname VARCHAR(64) NOT NULL,
                password_hash VARCHAR(256),
                is_admin BOOLEAN DEFAULT 0,
                roles VARCHAR(256) DEFAULT '[]',
                created_at DATETIME
            );
            CREATE TABLE auth_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid VARCHAR(32) NOT NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'pending',
                expires_at DATETIME NOT NULL,
                created_at DATETIME
            );
            CREATE TABLE guard_gift_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid VARCHAR(32) NOT NULL,
                nickname VARCHAR(64) NOT NULL,
                month VARCHAR(7) NOT NULL,
                guard_level VARCHAR(16) DEFAULT 'guard',
                accompany_days INTEGER DEFAULT 0,
                received BOOLEAN DEFAULT 0,
                received_at DATETIME,
                created_at DATETIME,
                updated_at DATETIME,
                UNIQUE(uid, month)
            );
            """
        )
        conn.execute(
            """
            INSERT INTO users
                (uid, nickname, password_hash, is_admin, roles, created_at)
            VALUES
                ('1001', 'admin-user', 'hash', 1, '[]', '2026-06-10 12:00:00'),
                ('1002', 'normal-user', 'hash', 0, '[]', '2026-06-10 12:00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO auth_sessions
                (uid, status, expires_at, created_at)
            VALUES
                ('1002', 'pending', '2026-06-11 12:00:00', '2026-06-10 12:00:00')
            """
        )
        conn.commit()
    finally:
        conn.close()


def rows(conn, query):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query).fetchall()]


def test_script_migrates_upstream_db_to_split_runtime_schema(tmp_path):
    db_path = tmp_path / "app.db"
    settings_path = tmp_path / "settings.json"
    backup_dir = tmp_path / "backups"
    create_upstream_like_db(db_path)
    settings_path.write_text(
        json.dumps(
            {
                "bilibili": {
                    "SESSDATA": "legacy-sess",
                    "bili_jct": "legacy-csrf",
                    "buvid3": "legacy-buvid",
                }
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            str(SCRIPT),
            "--db",
            str(db_path),
            "--settings",
            str(settings_path),
            "--backup-dir",
            str(backup_dir),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    assert "Migrated legacy admin flags" in result.stdout
    assert "Initialized cookie metadata" in result.stdout
    assert list(backup_dir.glob("app.db.*.bak"))

    conn = sqlite3.connect(db_path)
    try:
        user_rows = rows(conn, "SELECT uid, roles FROM users ORDER BY uid")
        assert json.loads(user_rows[0]["roles"]) == ["admin"]
        assert json.loads(user_rows[1]["roles"]) == []

        auth_columns = {row["name"] for row in rows(conn, "PRAGMA table_info(auth_sessions)")}
        assert {"code", "succeeded_at", "consumed_at", "last_attempt_at"} <= auth_columns

        cookie_columns = {row["name"] for row in rows(conn, "PRAGMA table_info(cookie_metadata)")}
        assert "web_refresh_token" in cookie_columns
        assert "cookie_header" in cookie_columns

        for table in ("qr_login_tasks", "cookie_metadata", "auth_attempts", "runtime_statuses", "scheduler_jobs"):
            assert rows(
                conn,
                f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'",
            )

        metadata = rows(conn, "SELECT * FROM cookie_metadata WHERE role='admin'")[0]
        assert metadata["status"] == "missing"
        assert metadata["source"] == "migration"
        assert metadata["cookie_version"] == 0
        assert metadata["reload_requested_version"] == 0
        assert metadata["cookie_header"] == ""
        assert "重新扫码" in metadata["last_error"]
    finally:
        conn.close()


def test_script_dry_run_does_not_modify_database(tmp_path):
    db_path = tmp_path / "app.db"
    settings_path = tmp_path / "settings.json"
    create_upstream_like_db(db_path)
    settings_path.write_text(json.dumps({"bilibili": {"SESSDATA": "legacy"}}), encoding="utf-8")

    result = subprocess.run(
        [
            str(SCRIPT),
            "--db",
            str(db_path),
            "--settings",
            str(settings_path),
            "--dry-run",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    assert "Dry run only" in result.stdout

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row["name"]
            for row in rows(conn, "SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "cookie_metadata" not in tables
        assert "runtime_statuses" not in tables
    finally:
        conn.close()


def test_script_marks_valid_cookie_metadata_without_db_cookie_for_rescan(tmp_path):
    db_path = tmp_path / "app.db"
    settings_path = tmp_path / "settings.json"
    backup_dir = tmp_path / "backups"
    create_upstream_like_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE cookie_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role VARCHAR(32) NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'unknown',
                source VARCHAR(32),
                masked_uid VARCHAR(32),
                payload_json TEXT,
                cookie_version INTEGER NOT NULL DEFAULT 6,
                reload_requested_version INTEGER NOT NULL DEFAULT 6,
                reload_requested_at DATETIME,
                web_refresh_token TEXT DEFAULT '',
                last_validated_at DATETIME,
                last_error VARCHAR(512),
                created_at DATETIME,
                updated_at DATETIME
            );
            INSERT INTO cookie_metadata (
                role, status, source, masked_uid, payload_json,
                cookie_version, reload_requested_version, web_refresh_token, last_error
            )
            VALUES (
                'admin', 'valid', 'qr_login', '42', '{}',
                6, 6, 'old-refresh-token', ''
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
    settings_path.write_text(json.dumps({"bilibili": {"SESSDATA": "legacy"}}), encoding="utf-8")

    result = subprocess.run(
        [
            str(SCRIPT),
            "--db",
            str(db_path),
            "--settings",
            str(settings_path),
            "--backup-dir",
            str(backup_dir),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    assert "Marked 1 cookie metadata row(s) for Web QR rescan" in result.stdout
    conn = sqlite3.connect(db_path)
    try:
        metadata = rows(conn, "SELECT status, cookie_header, last_error FROM cookie_metadata WHERE role='admin'")[0]
        assert metadata["status"] == "rescan_required"
        assert metadata["cookie_header"] == ""
        assert "重新扫码" in metadata["last_error"]
    finally:
        conn.close()

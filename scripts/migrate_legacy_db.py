#!/usr/bin/env python3
"""Migrate an upstream single-process SQLite DB to the split-runtime schema.

This script is intentionally explicit and operator-run. It does not import the
Flask app and it is not called during normal service startup.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "app.db"
DEFAULT_SETTINGS = ROOT / "settings.json"
DEFAULT_BACKUP_DIR = ROOT / "backups"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def backup_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def columns(conn: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
    if not table_exists(conn, table):
        return {}
    return {
        row["name"]: row
        for row in conn.execute(f"PRAGMA table_info({quote_identifier(table)})")
    }


def add_column(conn: sqlite3.Connection, table: str, name: str, ddl: str) -> bool:
    if name in columns(conn, table):
        return False
    conn.execute(f"ALTER TABLE {quote_identifier(table)} ADD COLUMN {quote_identifier(name)} {ddl}")
    return True


def drop_legacy_tv_auth_cookie_metadata_columns(conn: sqlite3.Connection) -> list[str]:
    table_columns = columns(conn, "cookie_metadata")
    legacy_columns = {"tv_access_token", "tv_refresh_token", "tv_auth_payload_json"}
    existing_drop_columns = [name for name in legacy_columns if name in table_columns]
    if not existing_drop_columns:
        return []

    target_columns = [
        "id",
        "role",
        "status",
        "source",
        "masked_uid",
        "payload_json",
        "cookie_version",
        "reload_requested_version",
        "reload_requested_at",
        "web_refresh_token",
        "cookie_header",
        "sessdata_expires_at",
        "last_refresh_at",
        "last_validated_at",
        "last_error",
        "created_at",
        "updated_at",
    ]
    retained_columns = [name for name in target_columns if name in table_columns]
    retained_sql = ", ".join(quote_identifier(name) for name in retained_columns)
    temp_table = "cookie_metadata__without_legacy_tv_auth"
    conn.execute(f"DROP TABLE IF EXISTS {quote_identifier(temp_table)}")
    conn.executescript(
        f"""
        CREATE TABLE {quote_identifier(temp_table)} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role VARCHAR(32) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'unknown',
            source VARCHAR(32),
            masked_uid VARCHAR(32),
            payload_json TEXT,
            cookie_version INTEGER NOT NULL DEFAULT 0,
            reload_requested_version INTEGER NOT NULL DEFAULT 0,
            reload_requested_at DATETIME,
            web_refresh_token TEXT DEFAULT '',
            cookie_header TEXT DEFAULT '',
            sessdata_expires_at DATETIME,
            last_refresh_at DATETIME,
            last_validated_at DATETIME,
            last_error VARCHAR(512),
            created_at DATETIME,
            updated_at DATETIME
        );
        """
    )
    conn.execute(
        f"INSERT INTO {quote_identifier(temp_table)} ({retained_sql}) "
        f"SELECT {retained_sql} FROM cookie_metadata"
    )
    conn.execute("DROP TABLE cookie_metadata")
    conn.execute(
        f"ALTER TABLE {quote_identifier(temp_table)} RENAME TO cookie_metadata"
    )
    create_index(conn, "ix_cookie_metadata_role", "cookie_metadata", "role")
    create_index(conn, "ix_cookie_metadata_status", "cookie_metadata", "status")
    create_index(conn, "ix_cookie_metadata_masked_uid", "cookie_metadata", "masked_uid")
    return [f"Dropped cookie_metadata.{name}" for name in existing_drop_columns]


def create_index(conn: sqlite3.Connection, name: str, table: str, columns_sql: str, unique: bool = False):
    unique_sql = "UNIQUE " if unique else ""
    conn.execute(
        f"CREATE {unique_sql}INDEX IF NOT EXISTS {quote_identifier(name)} "
        f"ON {quote_identifier(table)} ({columns_sql})"
    )


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def normalize_roles(raw: Any) -> list[str]:
    if raw in (None, ""):
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw if item]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return normalize_roles(parsed)
    return []


def update_roles_for_legacy_admins(conn: sqlite3.Connection) -> int:
    user_columns = columns(conn, "users")
    if "users" not in table_names(conn) or "is_admin" not in user_columns:
        return 0
    if "roles" not in user_columns:
        add_column(conn, "users", "roles", "VARCHAR(256) DEFAULT '[]'")

    changed = 0
    rows = conn.execute("SELECT id, is_admin, roles FROM users").fetchall()
    for row in rows:
        roles = normalize_roles(row["roles"])
        if int(row["is_admin"] or 0) and "admin" not in roles:
            roles.append("admin")
            conn.execute(
                "UPDATE users SET roles=? WHERE id=?",
                (json.dumps(roles, ensure_ascii=False), row["id"]),
            )
            changed += 1
    return changed


def table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def migrate_nullable_user_password(conn: sqlite3.Connection) -> bool:
    if not table_exists(conn, "users"):
        return False
    user_columns = columns(conn, "users")
    password_column = user_columns.get("password_hash")
    if not password_column or not int(password_column["notnull"] or 0):
        return False

    is_admin_sql = "is_admin BOOLEAN DEFAULT 0," if "is_admin" in user_columns else ""
    is_admin_insert = "is_admin," if "is_admin" in user_columns else ""
    is_admin_select = "is_admin," if "is_admin" in user_columns else ""
    roles_sql = "roles VARCHAR(256) DEFAULT '[]'," if "roles" in user_columns else ""
    roles_insert = "roles," if "roles" in user_columns else ""
    roles_select = "roles," if "roles" in user_columns else ""

    conn.executescript(
        f"""
        CREATE TABLE users_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid VARCHAR(32) UNIQUE NOT NULL,
            nickname VARCHAR(64) NOT NULL,
            password_hash VARCHAR(256),
            {is_admin_sql}
            {roles_sql}
            created_at DATETIME
        );
        INSERT INTO users_new (
            id, uid, nickname, password_hash, {is_admin_insert} {roles_insert} created_at
        )
        SELECT
            id, uid, nickname, password_hash, {is_admin_select} {roles_select} created_at
        FROM users;
        DROP TABLE users;
        ALTER TABLE users_new RENAME TO users;
        """
    )
    create_index(conn, "ix_users_uid", "users", "uid")
    return True


def ensure_core_columns(conn: sqlite3.Connection) -> list[str]:
    changes: list[str] = []

    if table_exists(conn, "users"):
        if migrate_nullable_user_password(conn):
            changes.append("Made users.password_hash nullable")
        if add_column(conn, "users", "roles", "VARCHAR(256) DEFAULT '[]'"):
            changes.append("Added users.roles")
        create_index(conn, "ix_users_uid", "users", "uid")

    if table_exists(conn, "guards"):
        for name, ddl in (
            ("guard_level", "VARCHAR(16) DEFAULT 'guard'"),
            ("accompany_days", "INTEGER DEFAULT 0"),
            ("in_guard", "BOOLEAN DEFAULT 1"),
        ):
            if add_column(conn, "guards", name, ddl):
                changes.append(f"Added guards.{name}")

    if table_exists(conn, "addresses"):
        if add_column(conn, "addresses", "guard_level", "VARCHAR(16) DEFAULT 'guard'"):
            changes.append("Added addresses.guard_level")

    if table_exists(conn, "auth_sessions"):
        for name, ddl in (
            ("code", "VARCHAR(32)"),
            ("succeeded_at", "DATETIME"),
            ("consumed_at", "DATETIME"),
            ("last_attempt_at", "DATETIME"),
        ):
            if add_column(conn, "auth_sessions", name, ddl):
                changes.append(f"Added auth_sessions.{name}")
        create_index(conn, "ix_auth_sessions_code", "auth_sessions", "code")

    return changes


def ensure_new_tables(conn: sqlite3.Connection) -> list[str]:
    before = table_names(conn)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS qr_login_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id VARCHAR(64) NOT NULL UNIQUE,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            role VARCHAR(32),
            qrcode_key VARCHAR(128),
            qr_url VARCHAR(512),
            payload_json TEXT,
            error_message VARCHAR(512),
            created_at DATETIME,
            updated_at DATETIME,
            expires_at DATETIME,
            completed_at DATETIME
        );
        CREATE TABLE IF NOT EXISTS cookie_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role VARCHAR(32) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'unknown',
            source VARCHAR(32),
            masked_uid VARCHAR(32),
            payload_json TEXT,
            cookie_version INTEGER NOT NULL DEFAULT 0,
            reload_requested_version INTEGER NOT NULL DEFAULT 0,
            reload_requested_at DATETIME,
            web_refresh_token TEXT DEFAULT '',
            cookie_header TEXT DEFAULT '',
            sessdata_expires_at DATETIME,
            last_refresh_at DATETIME,
            last_validated_at DATETIME,
            last_error VARCHAR(512),
            created_at DATETIME,
            updated_at DATETIME
        );
        CREATE TABLE IF NOT EXISTS auth_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            uid VARCHAR(32) NOT NULL,
            status VARCHAR(32) NOT NULL,
            code VARCHAR(32),
            nickname VARCHAR(64),
            room_id VARCHAR(32),
            payload_json TEXT,
            error_message VARCHAR(512),
            created_at DATETIME
        );
        CREATE TABLE IF NOT EXISTS runtime_statuses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role VARCHAR(32) NOT NULL,
            instance_id VARCHAR(64) NOT NULL,
            state VARCHAR(32) NOT NULL DEFAULT 'unknown',
            payload_json TEXT,
            last_error VARCHAR(512),
            delivery_error VARCHAR(512),
            retry_count INTEGER DEFAULT 0,
            cookie_version INTEGER DEFAULT 0,
            last_event_at DATETIME,
            heartbeat_at DATETIME,
            created_at DATETIME,
            updated_at DATETIME,
            UNIQUE(role, instance_id)
        );
        CREATE TABLE IF NOT EXISTS scheduler_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id VARCHAR(64) NOT NULL UNIQUE,
            job_type VARCHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            requested_by VARCHAR(64),
            payload_json TEXT,
            result_json TEXT,
            last_error VARCHAR(512),
            created_at DATETIME,
            updated_at DATETIME,
            scheduled_at DATETIME,
            started_at DATETIME,
            finished_at DATETIME
        );
        CREATE TABLE IF NOT EXISTS guard_gift_records (
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
    create_index(conn, "ix_qr_login_tasks_task_id", "qr_login_tasks", "task_id")
    create_index(conn, "ix_qr_login_tasks_status", "qr_login_tasks", "status")
    create_index(conn, "ix_cookie_metadata_role", "cookie_metadata", "role")
    create_index(conn, "ix_cookie_metadata_status", "cookie_metadata", "status")
    create_index(conn, "ix_cookie_metadata_masked_uid", "cookie_metadata", "masked_uid")
    create_index(conn, "ix_auth_attempts_session_id", "auth_attempts", "session_id")
    create_index(conn, "ix_auth_attempts_uid", "auth_attempts", "uid")
    create_index(conn, "ix_auth_attempts_status", "auth_attempts", "status")
    create_index(conn, "ix_auth_attempts_code", "auth_attempts", "code")
    create_index(conn, "ix_auth_attempts_room_id", "auth_attempts", "room_id")
    create_index(conn, "ix_runtime_statuses_role", "runtime_statuses", "role")
    create_index(conn, "ix_runtime_statuses_instance_id", "runtime_statuses", "instance_id")
    create_index(conn, "ix_runtime_statuses_state", "runtime_statuses", "state")
    create_index(conn, "ix_runtime_statuses_heartbeat_at", "runtime_statuses", "heartbeat_at")
    create_index(conn, "ix_scheduler_jobs_job_id", "scheduler_jobs", "job_id")
    create_index(conn, "ix_scheduler_jobs_job_type", "scheduler_jobs", "job_type")
    create_index(conn, "ix_scheduler_jobs_status", "scheduler_jobs", "status")
    create_index(conn, "ix_scheduler_jobs_requested_by", "scheduler_jobs", "requested_by")
    create_index(conn, "ix_scheduler_jobs_scheduled_at", "scheduler_jobs", "scheduled_at")
    create_index(conn, "ix_guard_gift_records_uid", "guard_gift_records", "uid")
    create_index(conn, "ix_guard_gift_records_month", "guard_gift_records", "month")

    created = sorted(table_names(conn) - before)
    return [f"Created {table}" for table in created]


def ensure_cookie_metadata_columns(conn: sqlite3.Connection) -> list[str]:
    changes: list[str] = []
    if not table_exists(conn, "cookie_metadata"):
        return changes
    changes.extend(drop_legacy_tv_auth_cookie_metadata_columns(conn))
    for name, ddl in (
        ("cookie_version", "INTEGER NOT NULL DEFAULT 0"),
        ("reload_requested_version", "INTEGER NOT NULL DEFAULT 0"),
        ("reload_requested_at", "DATETIME"),
        ("web_refresh_token", "TEXT DEFAULT ''"),
        ("cookie_header", "TEXT DEFAULT ''"),
        ("sessdata_expires_at", "DATETIME"),
        ("last_refresh_at", "DATETIME"),
        ("last_validated_at", "DATETIME"),
        ("last_error", "VARCHAR(512)"),
        ("created_at", "DATETIME"),
        ("updated_at", "DATETIME"),
    ):
        if add_column(conn, "cookie_metadata", name, ddl):
            changes.append(f"Added cookie_metadata.{name}")
    return changes


def ensure_runtime_status_columns(conn: sqlite3.Connection) -> list[str]:
    changes: list[str] = []
    if not table_exists(conn, "runtime_statuses"):
        return changes
    for name, ddl in (
        ("delivery_error", "VARCHAR(512)"),
        ("retry_count", "INTEGER DEFAULT 0"),
        ("cookie_version", "INTEGER DEFAULT 0"),
    ):
        if add_column(conn, "runtime_statuses", name, ddl):
            changes.append(f"Added runtime_statuses.{name}")
    return changes


def initialize_cookie_metadata(conn: sqlite3.Connection, settings_path: Path) -> bool:
    if not table_exists(conn, "cookie_metadata"):
        return False
    existing = conn.execute(
        "SELECT 1 FROM cookie_metadata WHERE role='admin' LIMIT 1"
    ).fetchone()
    if existing is not None:
        return False

    cookie_header = ""
    status = "missing"
    source = "migration"
    version = 0
    now = now_text()
    last_error = "请重新扫码授权 B 站账号"
    conn.execute(
        """
        INSERT INTO cookie_metadata (
            role, status, source, masked_uid, payload_json,
            cookie_version, reload_requested_version, reload_requested_at,
            web_refresh_token, cookie_header,
            sessdata_expires_at, last_refresh_at, last_validated_at, last_error,
            created_at, updated_at
        )
        VALUES (
            'admin', ?, ?, '', '{}',
            ?, ?, ?,
            '', ?,
            NULL, NULL, ?, ?,
            ?, ?
        )
        """,
        (
            status,
            source,
            version,
            version,
            None,
            cookie_header,
            None,
            last_error,
            now,
            now,
        ),
    )
    return True


def normalize_cookie_metadata_auth_state(conn: sqlite3.Connection) -> int:
    if not table_exists(conn, "cookie_metadata"):
        return 0
    cookie_columns = columns(conn, "cookie_metadata")
    if "cookie_header" not in cookie_columns:
        return 0
    conn.execute(
        """
        UPDATE cookie_metadata
        SET source = 'migration'
        WHERE source = 'tv_auth'
        """
    )
    cursor = conn.execute(
        """
        UPDATE cookie_metadata
        SET status = 'rescan_required',
            source = CASE
                WHEN source IS NULL OR source = '' THEN 'migration'
                ELSE source
            END,
            last_error = '当前 DB 缺少 Web Cookie，请重新扫码授权 B 站账号'
        WHERE status = 'valid'
          AND (cookie_header IS NULL OR cookie_header = '')
        """
    )
    return cursor.rowcount or 0


def migrate_database(db_path: Path, settings_path: Path) -> list[str]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    changes: list[str] = []
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN")
        changes.extend(ensure_core_columns(conn))
        admin_count = update_roles_for_legacy_admins(conn)
        if admin_count:
            changes.append(f"Migrated legacy admin flags for {admin_count} user(s)")
        changes.extend(ensure_new_tables(conn))
        changes.extend(ensure_cookie_metadata_columns(conn))
        changes.extend(ensure_runtime_status_columns(conn))
        if initialize_cookie_metadata(conn, settings_path):
            changes.append("Initialized cookie metadata from legacy settings")
        normalized_count = normalize_cookie_metadata_auth_state(conn)
        if normalized_count:
            changes.append(f"Marked {normalized_count} cookie metadata row(s) for Web QR rescan")
        conn.commit()
        return changes
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def backup_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{db_path.name}.{backup_stamp()}.bak"
    shutil.copy2(db_path, backup_path)
    return backup_path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Migrate an upstream bilibili-sailing-helper SQLite DB to the split-runtime schema.",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite DB path. Default: data/app.db")
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS, help="settings.json path")
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR, help="backup output directory")
    parser.add_argument("--dry-run", action="store_true", help="inspect inputs without modifying the DB")
    parser.add_argument("--no-backup", action="store_true", help="skip the automatic DB backup")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = args.db.resolve()
    settings_path = args.settings.resolve()
    backup_dir = args.backup_dir.resolve()

    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    print(f"Database: {db_path}")
    print(f"Settings: {settings_path}")

    if args.dry_run:
        print("Dry run only; database was not modified.")
        return 0

    if not args.no_backup:
        backup_path = backup_database(db_path, backup_dir)
        print(f"Backup: {backup_path}")

    changes = migrate_database(db_path, settings_path)
    if changes:
        for change in changes:
            print(f"- {change}")
    else:
        print("- Database already matched the target schema")
    print("Migration completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

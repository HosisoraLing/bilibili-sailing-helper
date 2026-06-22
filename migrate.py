"""
Database migration script to handle schema changes.
Run this when you make changes to the database models.
"""
import sqlite3
import os
from pathlib import Path

def find_database():
    """Find the database file in the project directory."""
    # Check common locations
    possible_paths = [
        './data/app.db',
        './app.db',
        'data/app.db',
    ]

    for path in possible_paths:
        if os.path.exists(path):
            return path

    # Search recursively
    for root, dirs, files in os.walk('.'):
        for file in files:
            if file.endswith('.db'):
                return os.path.join(root, file)

    return None


def migrate_users_password_hash(conn):
    """Migrate users.password_hash to be nullable."""
    cursor = conn.cursor()

    # Check current schema
    cursor.execute("PRAGMA table_info(users)")
    columns = cursor.fetchall()

    # Find password_hash column
    password_hash_col = next((col for col in columns if col[1] == 'password_hash'), None)

    if password_hash_col and password_hash_col[3] == 1:  # 3rd index is notnull (1 = NOT NULL)
        print("  Migrating: Altering users.password_hash to be nullable...")

        # Create new table with nullable password_hash
        cursor.execute("""
            CREATE TABLE users_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid VARCHAR(32) UNIQUE NOT NULL,
                nickname VARCHAR(64) NOT NULL,
                password_hash VARCHAR(256),
                is_admin BOOLEAN DEFAULT 0,
                created_at DATETIME
            )
        """)

        # Copy data
        cursor.execute("""
            INSERT INTO users_new (id, uid, nickname, password_hash, is_admin, created_at)
            SELECT id, uid, nickname, password_hash, is_admin, created_at FROM users
        """)

        # Drop old table and rename
        cursor.execute("DROP TABLE users")
        cursor.execute("ALTER TABLE users_new RENAME TO users")

        # Recreate indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_users_uid ON users(uid)")

        conn.commit()
        print("  ✓ Migration completed: users.password_hash is now nullable")
        return True

    print("  ✓ users.password_hash is already nullable")
    return False


def run_migrations():
    """Run all database migrations."""
    db_path = find_database()

    if not db_path:
        print("No database file found. The database will be created with the new schema.")
        return

    print(f"Found database: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        print("\nRunning migrations...")

        migrated = False
        migrated |= migrate_users_password_hash(conn)

        if migrated:
            print("\n✓ All migrations completed successfully!")
        else:
            print("\n✓ Database is up to date. No migrations needed.")

    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    run_migrations()

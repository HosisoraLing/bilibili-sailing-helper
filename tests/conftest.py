import json
import os
import tempfile
from pathlib import Path

import pytest

from db.models import db


TEST_DIR = tempfile.TemporaryDirectory(prefix="bsh-tests-")
TEST_DIR_PATH = Path(TEST_DIR.name)
TEST_SETTINGS_PATH = TEST_DIR_PATH / "settings.json"
TEST_DB_PATH = TEST_DIR_PATH / "test.db"
TEST_SETTINGS_PATH.write_text(
    json.dumps(
        {
            "anchor": {
                "nickname": "test-anchor",
                "room_id": 1,
                "ruid": 2,
            },
            "bilibili": {
                "SESSDATA": "",
                "bili_jct": "",
                "buvid3": "",
            },
            "database": {"url": f"sqlite:///{TEST_DB_PATH}"},
            "flask": {
                "secret_key": "test-secret-key",
                "debug": False,
                "host": "127.0.0.1",
                "port": 7111,
            },
            "ssl": {
                "enabled": False,
                "cert_file": "",
                "key_file": "",
                "port": 7112,
            },
            "admin": {"uids": []},
        }
    ),
    encoding="utf-8",
)
os.environ["BILIBILI_SAILING_SETTINGS"] = str(TEST_SETTINGS_PATH)


def pytest_sessionfinish(session, exitstatus):
    TEST_DIR.cleanup()


@pytest.fixture
def app():
    from app import create_app

    app, _ = create_app()
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        INTERNAL_API_SECRET="test-secret",
    )
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()

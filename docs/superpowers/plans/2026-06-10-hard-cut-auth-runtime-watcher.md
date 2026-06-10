---
change: hard-cut-auth-runtime-watcher
design-doc: docs/superpowers/specs/2026-06-10-hard-cut-auth-runtime-watcher-design.md
base-ref: 80b9c3b16cb08c0ccec876c1203b23e47500a952
---

# Hard-Cut Auth Runtime Watcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Playwright and `blivedm`, split runtime roles, and route worker/scheduler writes through web/app internal APIs.

**Architecture:** `web` owns all direct business DB writes and exposes public/admin/internal APIs. `danmaku-worker` owns Bilibili WebSocket listening and reports candidate auth events/status to `web`. `scheduler` owns periodic triggers and reports job requests/results to `web`.

**Tech Stack:** Flask, Flask-SQLAlchemy, SQLite, aiohttp/websocket-client, requests, Docker Compose, pytest.

---

## File Structure

- Create `tests/conftest.py`: app/db test fixture and isolated SQLite setup.
- Create `tests/test_auth_state.py`: auth session state machine and duplicate success tests.
- Create `tests/test_internal_api.py`: internal secret auth, danmaku webhook, runtime heartbeat, scheduler job endpoints.
- Create `tests/test_qr_login.py`: mocked Passport QR flow and Cookie validation.
- Create `tests/test_watcher_protocol.py`: Bilibili packet codec and event normalization fixtures.
- Create `tests/test_runtime_config.py`: dependency, Docker, Compose, and production-runtime guard checks.
- Modify `db/models.py`: add QR login, Cookie metadata, auth attempt, runtime status, scheduler job models.
- Create `services/repositories.py`: short DB write helpers used only by web/app service layer.
- Modify `services/auth_service.py`: DB-backed auth codes and atomic success transition.
- Create `services/internal_api_service.py`: shared-secret validation and internal endpoint handlers.
- Create `services/bilibili_qr_service.py`: HTTP Passport QR begin/poll and Cookie integrity validation.
- Create `services/bilibili_live/`: native watcher package with `api.py`, `protocol.py`, `client.py`, `events.py`, `webhook.py`.
- Create `runtime/web.py`, `runtime/danmaku_worker.py`, `runtime/scheduler.py`: explicit role entrypoints.
- Modify `routes.py`: admin QR/status routes and internal routes.
- Modify `app.py`: app factory/startup cleanup; remove background role ownership from web startup.
- Modify `services/cookie_service.py`: remove Playwright QR/buvid behavior or delegate to QR service.
- Modify `services/danmaku_listener.py`: remove production `blivedm` listener path after replacement.
- Modify `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `settings.json.example`, `DOCKER_README.md`: dependency and runtime contract updates.

## Task 1: Test Harness And Persistent State Models

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_auth_state.py`
- Modify: `requirements.txt`
- Modify: `db/models.py`
- Modify: `db/init_db.py`
- Modify: `services/auth_service.py`

- [x] **Step 1: Add pytest dependencies**

Add active dependency lines to `requirements.txt`:

```text
pytest>=7.4.0,<9.0.0
pytest-flask>=1.2.0,<2.0.0
```

- [x] **Step 2: Create isolated test fixture**

Create `tests/conftest.py` with an app fixture that uses temporary SQLite:

```python
import pytest
from app import create_app
from db.models import db


@pytest.fixture
def app(tmp_path):
    app = create_app()
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'test.db'}",
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
```

- [x] **Step 3: Write failing auth state tests**

Create `tests/test_auth_state.py`:

```python
from datetime import timedelta

from db.models import AuthSession, db, get_beijing_now
from services.auth_service import create_auth_session, get_active_auth_session, mark_auth_success


def test_success_session_remains_visible(app):
    with app.app_context():
        session, _ = create_auth_session("1001")
        assert mark_auth_success(session) is True

        active = get_active_auth_session("1001")
        assert active is not None
        assert active.status == "success"


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


def test_duplicate_success_only_wins_once(app):
    with app.app_context():
        session, _ = create_auth_session("1003")
        assert mark_auth_success(session) is True
        assert mark_auth_success(session) is False
```

- [x] **Step 4: Run tests and verify failure**

Run:

```bash
pytest tests/test_auth_state.py -q
```

Expected now: fail if the fixture cannot create app with temporary DB or if auth code remains memory-only in ways that block DB-backed flows.

- [x] **Step 5: Add state models**

Extend `db/models.py` with models for QR login, Cookie metadata, auth attempts, runtime status, and scheduler jobs. Use simple columns only: string status, timestamps, JSON text for payloads, and indexes on role/job/session identifiers.

- [x] **Step 6: Make auth code durable**

Update `AuthSession` to store `code`, `succeeded_at`, `consumed_at`, and an optional `last_attempt_at`. Update `create_auth_session()` and `mark_auth_success()` so the code is attached to the DB session and success transition is atomic from pending to success.

- [x] **Step 7: Run focused tests**

Run:

```bash
pytest tests/test_auth_state.py -q
```

Expected: all tests pass.

- [x] **Step 8: Commit Task 1**

```bash
git add requirements.txt db/models.py db/init_db.py services/auth_service.py tests/conftest.py tests/test_auth_state.py
git commit -m "feat: add durable auth state models"
```

## Task 2: Internal API Boundary

**Files:**
- Create: `services/internal_api_service.py`
- Create: `tests/test_internal_api.py`
- Modify: `routes.py`
- Modify: `app.py`
- Modify: `db/models.py`

- [x] **Step 1: Write failing internal API tests**

Create `tests/test_internal_api.py` with tests for missing secret, wrong secret, valid heartbeat, and valid danmaku event.

```python
from datetime import timedelta

from db.models import AuthSession, RuntimeStatus, db, get_beijing_now


def test_internal_api_rejects_missing_secret(client):
    response = client.post("/internal/runtime/heartbeat", json={"role": "danmaku-worker"})
    assert response.status_code == 401


def test_internal_api_accepts_runtime_heartbeat(client, app):
    response = client.post(
        "/internal/runtime/heartbeat",
        headers={"Authorization": "test-secret"},
        json={"role": "danmaku-worker", "instance_id": "test-1", "state": "running"},
    )
    assert response.status_code == 200
    with app.app_context():
        status = RuntimeStatus.query.filter_by(role="danmaku-worker").one()
        assert status.state == "running"


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
    with app.app_context():
        assert AuthSession.query.filter_by(uid="42").one().status == "success"
```

- [x] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_internal_api.py -q
```

Expected: fail because internal routes and models do not exist.

- [x] **Step 3: Implement internal service helpers**

Create `services/internal_api_service.py` with `verify_internal_secret()`, `record_runtime_heartbeat()`, `process_danmaku_auth_event()`, and scheduler job helpers. Use constant-time comparison for the secret.

- [x] **Step 4: Register internal routes**

Add routes under `/internal/danmaku/auth-event`, `/internal/runtime/heartbeat`, `/internal/scheduler/job`, and `/internal/scheduler/result`. Keep responses small and machine-readable.

- [x] **Step 5: Run tests**

Run:

```bash
pytest tests/test_internal_api.py tests/test_auth_state.py -q
```

Expected: all pass.

- [x] **Step 6: Commit Task 2**

```bash
git add routes.py app.py db/models.py services/internal_api_service.py tests/test_internal_api.py
git commit -m "feat: add internal runtime API boundary"
```

## Task 3: Browserless QR Login

**Files:**
- Create: `services/bilibili_qr_service.py`
- Create: `tests/test_qr_login.py`
- Modify: `services/cookie_service.py`
- Modify: `routes.py`
- Modify: `templates/admin.html` or the current admin Cookie template if different
- Modify: `requirements.txt`

- [x] **Step 1: Write QR service tests**

Create `tests/test_qr_login.py` with mocked HTTP responses covering begin, scanned, expired, success, invalid Cookie, and unknown status. Mock `requests.get` or inject a small HTTP client object.

- [x] **Step 2: Run QR tests and verify failure**

Run:

```bash
pytest tests/test_qr_login.py -q
```

Expected: fail because `services.bilibili_qr_service` does not exist.

- [x] **Step 3: Implement QR begin/poll service**

Implement `start_qr_login()`, `poll_qr_login(task_id)`, and `validate_cookie_header(cookie_header)` using:

```text
https://passport.bilibili.com/x/passport-login/web/qrcode/generate
https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key=...
https://api.bilibili.com/x/web-interface/nav
```

Persist QR task state in DB and do not replace the current Cookie until validation succeeds.

- [x] **Step 4: Replace admin QR routes**

Update admin routes so `/cookie/start-qr-login` returns task id and QR URL, and polling returns explicit states: `pending`, `scanned`, `expired`, `failed`, `succeeded`.

- [x] **Step 5: Remove Playwright QR code path**

Remove Playwright imports and QR screenshot behavior from `services/cookie_service.py`. Replace admin error copy that mentions installing Playwright.

- [x] **Step 6: Run QR and auth tests**

Run:

```bash
pytest tests/test_qr_login.py tests/test_internal_api.py tests/test_auth_state.py -q
```

Expected: all pass.

- [x] **Step 7: Commit Task 3**

```bash
git add services/bilibili_qr_service.py services/cookie_service.py routes.py templates requirements.txt tests/test_qr_login.py
git commit -m "feat: replace qr login with passport api"
```

## Task 4: Native Watcher Protocol And Webhook Client

**Files:**
- Create: `services/bilibili_live/__init__.py`
- Create: `services/bilibili_live/api.py`
- Create: `services/bilibili_live/protocol.py`
- Create: `services/bilibili_live/events.py`
- Create: `services/bilibili_live/webhook.py`
- Create: `tests/test_watcher_protocol.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Write protocol and event tests**

Create tests for packet header parsing, heartbeat packet creation, compressed payload expansion, and `DANMU_MSG` normalization into `uid`, `nickname`, `content`, and `room_id`.

- [ ] **Step 2: Run protocol tests and verify failure**

Run:

```bash
pytest tests/test_watcher_protocol.py -q
```

Expected: fail because live modules do not exist.

- [ ] **Step 3: Implement protocol codec**

Implement packet constants, `pack_heartbeat()`, `pack_auth(payload)`, and `unpack_packets(raw)` with zlib and brotli support. Keep it independent from Flask and DB.

- [ ] **Step 4: Implement event normalizer**

Implement `normalize_danmaku_event(raw_event, room_id)` and return `None` for unsupported events or malformed payloads.

- [ ] **Step 5: Implement internal webhook client**

Implement an async webhook client with bounded queue, retry count, timeout, exponential backoff, and delivery error reporting payloads for `/internal/runtime/heartbeat`.

- [ ] **Step 6: Run watcher tests**

Run:

```bash
pytest tests/test_watcher_protocol.py -q
```

Expected: pass.

- [ ] **Step 7: Commit Task 4**

```bash
git add services/bilibili_live tests/test_watcher_protocol.py requirements.txt
git commit -m "feat: add native bilibili watcher protocol"
```

## Task 5: Runtime Entrypoints And Role Split

**Files:**
- Create: `runtime/__init__.py`
- Create: `runtime/web.py`
- Create: `runtime/danmaku_worker.py`
- Create: `runtime/scheduler.py`
- Create: `tests/test_runtime_config.py`
- Modify: `app.py`
- Modify: `services/danmaku_listener.py`
- Modify: `docker-compose.yml`
- Modify: `Dockerfile`
- Modify: `settings.json.example`

- [ ] **Step 1: Write runtime config tests**

Create tests that assert production runtime no longer imports `blivedm`, Playwright is not required, compose has `web`, `danmaku-worker`, and `scheduler`, and worker/scheduler commands do not mount or require direct DB writes.

- [ ] **Step 2: Run runtime tests and verify failure**

Run:

```bash
pytest tests/test_runtime_config.py -q
```

Expected: fail because current runtime is still single service and dependencies remain.

- [ ] **Step 3: Create role entrypoints**

Implement:

```bash
python -m runtime.web
python -m runtime.danmaku_worker
python -m runtime.scheduler
```

`runtime.web` starts Flask/SocketIO. `runtime.danmaku_worker` starts the native watcher and posts internal events. `runtime.scheduler` triggers internal job endpoints on schedule.

- [ ] **Step 4: Remove web ownership of background loops**

Update `app.py` so web startup no longer owns danmaku WebSocket, Cookie refresh scheduler, or session cleanup scheduler in production role mode.

- [ ] **Step 5: Update Docker and Compose**

Use one canonical internal web port. Define `web`, `danmaku-worker`, and `scheduler` services. Pass `INTERNAL_API_URL` and `INTERNAL_API_SECRET` to worker/scheduler. Remove Playwright browser install and `blivedm` git dependency.

- [ ] **Step 6: Run runtime checks**

Run:

```bash
pytest tests/test_runtime_config.py -q
docker compose config >/tmp/bsh-compose-config.yml
python -m compileall .
```

Expected: pytest passes, compose config renders, compileall succeeds.

- [ ] **Step 7: Commit Task 5**

```bash
git add runtime app.py services/danmaku_listener.py Dockerfile docker-compose.yml settings.json.example tests/test_runtime_config.py
git commit -m "feat: split runtime roles"
```

## Task 6: Admin UX, Documentation, And Final Verification

**Files:**
- Modify: `routes.py`
- Modify: `templates/`
- Modify: `static/`
- Modify: `DOCKER_README.md`
- Modify: `openspec/changes/hard-cut-auth-runtime-watcher/tasks.md`

- [ ] **Step 1: Update admin health response**

Admin status must show role, state, heartbeat age, last event time, last error, delivery error, retry count, and next action.

- [ ] **Step 2: Update auth polling response**

User-facing auth status must distinguish waiting, success, expired, listener unavailable, internal delivery delayed, and retrying.

- [ ] **Step 3: Update docs**

Document the role split, internal secret, how to restart only `danmaku-worker` or `scheduler`, and SQLite backup before migration.

- [ ] **Step 4: Run full verification**

Run:

```bash
pytest -q
python -m compileall .
docker compose config >/tmp/bsh-compose-config.yml
rg -n "playwright|blivedm|git pull|db\\.session\\.commit\\(" runtime services routes.py app.py
```

Expected:

- pytest passes
- compileall succeeds
- compose config renders
- no production Playwright or `blivedm` path remains
- worker/scheduler runtime code does not directly commit business DB state

- [ ] **Step 5: Update OpenSpec tasks**

Mark completed items in `openspec/changes/hard-cut-auth-runtime-watcher/tasks.md` only after verification evidence exists.

- [ ] **Step 6: Commit Task 6**

```bash
git add routes.py templates static DOCKER_README.md openspec/changes/hard-cut-auth-runtime-watcher/tasks.md
git commit -m "docs: document split runtime operation"
```

## Coverage Check

- `passport-qr-login`: Task 3 covers browserless QR generation, polling, Cookie validation, and admin feedback.
- `database-backed-auth`: Tasks 1 and 2 cover durable auth state, internal ingestion auth, atomic success, and role status.
- `native-danmaku-watcher`: Task 4 covers native protocol, normalization, reconnect, and webhook retry.
- `split-runtime-roles`: Tasks 5 and 6 cover entrypoints, Compose roles, internal API boundary, port contract, and admin health.

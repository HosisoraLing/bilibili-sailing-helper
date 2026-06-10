# Verification Report

## Evidence

- `.venv/bin/python -m pytest -q`: 81 passed.
- `.venv/bin/python -m compileall .`: passed.
- `INTERNAL_API_SECRET=test-secret docker compose config >/tmp/bsh-compose-config.yml`: passed.
- `INTERNAL_API_SECRET=test-secret docker compose build`: first direct Docker Hub token request timed out; retry with local proxy env passed and built `web`, `danmaku-worker`, and `scheduler` images.
- `rg -n "playwright|blivedm|git pull|git', 'pull" runtime services routes.py app.py requirements.txt Dockerfile docker-compose.yml`: no matches.
- `rg -n "db\\.session\\.commit\\(" runtime services routes.py app.py`: no `runtime/` matches; DB writes remain in web/app service paths.

## Complaint Mapping

- Danmaku auth sessions disappearing after success: `AuthSession` now persists code/status and `mark_auth_success()` validates expected codes atomically. Covered by `tests/test_auth_state.py` and `tests/test_internal_api.py`.
- Playwright QR dependency: admin QR login uses browserless Passport QR APIs with safe Cookie persistence and version increments. Covered by `tests/test_qr_login.py` and `tests/test_browserless_qr_contract.py`.
- `blivedm` watcher instability: production watcher is native packet/API/webhook code under `services/bilibili_live/`, with protocol, event normalization, retry, queue, and Cookie reload tests. Covered by `tests/test_watcher_protocol.py` and `tests/test_runtime_config.py`.
- Web process owning all runtime work: Compose now splits `web`, `danmaku-worker`, and `scheduler`; worker/scheduler use internal APIs and do not mount/write SQLite data. Covered by `tests/test_runtime_config.py`.
- Cookie update requiring web restart: QR success increments Cookie version; `danmaku-worker` polls runtime Cookie state, survives transient poll failures, and closes the old websocket when a newer version appears. Covered by `tests/test_cookie_runtime_contract.py` and `tests/test_runtime_config.py`.
- Admin/user feedback ambiguity: admin status reports role state, heartbeat age, errors, retry count, Cookie versions, stale worker state, and next action; auth polling distinguishes pending, success, expired, listener unavailable, delivery delayed, and retrying. Covered by `tests/test_internal_api.py`.
- SocketIO success dependency after role split: auth polling remains active after SocketIO connects, so DB-backed success state remains the canonical redirect path. Covered by `tests/test_runtime_config.py`.

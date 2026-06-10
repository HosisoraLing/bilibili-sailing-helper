# Hard-Cut Auth Runtime Watcher Verify Report

## Summary

| Dimension | Status |
| --- | --- |
| Completeness | 41/41 OpenSpec tasks checked |
| Correctness | 4/4 capability specs implemented with one scheduler scope warning |
| Coherence | Follows internal-API role split design |

## Verification Evidence

- `.venv/bin/python -m pytest -q`: 81 passed.
- `.venv/bin/python -m compileall .`: passed.
- `INTERNAL_API_SECRET=test-secret docker compose config >/tmp/bsh-compose-config.yml`: passed.
- `INTERNAL_API_SECRET=test-secret docker compose build`: first direct Docker Hub token request timed out; retry with local proxy env passed and built `web`, `danmaku-worker`, and `scheduler` images.
- `rg -n "playwright|blivedm|git pull|git', 'pull" runtime services routes.py app.py requirements.txt Dockerfile docker-compose.yml`: no matches.
- `rg -n "db\\.session\\.commit\\(" runtime services routes.py app.py`: no `runtime/` matches; DB writes remain in web/app service paths.

## Completeness

All OpenSpec task checkboxes are complete in `openspec/changes/hard-cut-auth-runtime-watcher/tasks.md`.

Implemented coverage:

- `passport-qr-login`: browserless Passport QR begin/poll, Cookie validation, safe persistence, Cookie versioning, and admin feedback.
- `database-backed-auth`: durable auth sessions, atomic success transition, auth attempts, internal secret validation, runtime status persistence.
- `native-danmaku-watcher`: native Bilibili protocol codec, event normalization, webhook retry, Cookie version polling/reload, and visible worker state.
- `split-runtime-roles`: explicit `web`, `danmaku-worker`, `scheduler` entrypoints, Compose roles, internal API secret, canonical port, no runtime code mutation.

## Correctness

### PASS: Auth State

`AuthSession` stores durable code/status fields and `mark_auth_success()` checks expected codes. Internal danmaku events mutate auth state only through authenticated web internal API.

Evidence: `tests/test_auth_state.py`, `tests/test_internal_api.py`.

### PASS: Browserless QR Login

QR login uses Bilibili Passport HTTP APIs and validates Cookies before replacing usable settings. Successful QR login increments Cookie version for worker reload.

Evidence: `tests/test_qr_login.py`, `tests/test_browserless_qr_contract.py`, `tests/test_cookie_runtime_contract.py`.

### PASS: Native Watcher

Production dependency on `blivedm` is removed. The native watcher decodes compressed packets, normalizes `DANMU_MSG`, retries webhook delivery, reports failures, and detects Cookie version changes. Transient Cookie poll failures now report `cookie_poll_error` and continue polling.

Evidence: `tests/test_watcher_protocol.py`, `tests/test_runtime_config.py`.

### PASS: Runtime Role Split

`web` owns HTTP/admin/internal APIs and business DB writes. `danmaku-worker` owns Bilibili WebSocket listening and reports internal events. `scheduler` runs as a separate long-running role and triggers web internal jobs. Worker/scheduler runtime entrypoints do not call `db.session.commit()`.

Evidence: `tests/test_runtime_config.py`, Compose config render, DB write scan.

### WARNING: Scheduler Job Breadth

The scheduler role currently has a long-running loop and triggers `guard-sync` through `/internal/scheduler/job`. The design/spec names additional periodic ownership areas such as gift/stat refresh, Cookie maintenance, and expired auth cleanup. Those are not all wired as distinct scheduled jobs in this implementation.

Impact: the role boundary is in place, but not every historical background job has a dedicated scheduler trigger yet. Existing tests cover the internal job mechanism and `guard-sync`, not every periodic job name.

Recommendation: either accept this as a follow-up scheduler expansion or return to build to add job definitions/tests for each periodic task before archive.

## Coherence

Implementation follows the design decision that internal HTTP is the cross-role boundary and web/app owns business DB writes. Admin and user feedback now reads runtime role health instead of old listener-thread state:

- Admin status includes role state, heartbeat age, errors, retry count, Cookie versions, stale worker state, and next action.
- Auth polling distinguishes pending, success, expired, listener unavailable, delivery delayed, and retrying.
- Docker documentation describes `web`, `danmaku-worker`, `scheduler`, `INTERNAL_API_SECRET`, role restart commands, Cookie reload, and SQLite backup.

## Review Gates

Subagent review checkpoints were requested after major runtime stages. Critical findings were fixed before proceeding:

- one-shot worker/scheduler converted to long-running roles;
- weak default internal secret removed from Compose;
- active Cookie version changes close the old WebSocket;
- Cookie poll errors no longer stop future Cookie reload polling;
- scheduler non-2xx internal API responses are surfaced as errors and heartbeat delivery failures.
- auth polling remains active after SocketIO connects, so split-runtime DB state is the canonical success redirect path.
- queue-full worker state is surfaced as delivery delay instead of misleading pending state.

## Final Assessment

No CRITICAL issues remain. One WARNING remains for scheduler job breadth. Archive readiness depends on the branch-handling decision and whether the scheduler breadth warning is accepted as a follow-up or sent back to build.

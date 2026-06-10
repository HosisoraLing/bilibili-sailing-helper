## 1. State Model And Tests

- [ ] 1.1 Inventory current auth, Cookie, listener, scheduler, auto-update, Docker port, and healthcheck code paths.
- [ ] 1.2 Add DB schema/models for QR login tasks, Cookie integrity metadata, auth attempts/success transitions, scheduler jobs, and runtime role status.
- [ ] 1.3 Design internal API contracts for danmaku event reporting, role heartbeat/status, scheduler job requests/results, and shared-secret authentication.
- [ ] 1.4 Configure SQLite for web/app-owned writes, including short transactions, busy timeout, and WAL if compatible with deployment.
- [ ] 1.5 Add focused tests for pending, success, expired, duplicate, and consumed auth session states.
- [ ] 1.6 Add tests for internal API authentication, runtime status heartbeat, stale heartbeat, last error, delivery error, and role separation fields.

## 2. Browserless QR Login

- [ ] 2.1 Study local `/Users/nowanti/Play/Projects/bili-cli` QR begin, poll, cookie import, and integrity code paths and map the project-specific subset.
- [ ] 2.2 Implement Bilibili Passport QR begin/poll service without Playwright.
- [ ] 2.3 Implement Cookie validation and integrity classification with safe persistence that does not replace a usable Cookie on failed validation.
- [ ] 2.4 Update admin QR login routes/templates/API responses with actionable statuses and retry guidance.
- [ ] 2.5 Remove Playwright runtime dependency and obsolete browser automation code.
- [ ] 2.6 Add mocked QR login tests for pending, scanned, expired, success, invalid Cookie, and unknown status code.

## 3. Native Danmaku Watcher

- [ ] 3.1 Study `/Users/nowanti/Play/Projects/v-nexus-core-monorepo/services/watcher` API/client/protocol/webhook modules and copy only the protocol and internal-reporting patterns needed here.
- [ ] 3.2 Implement Bilibili live API client for room/server auth data, including WBI signing only if required by the selected endpoint.
- [ ] 3.3 Implement packet pack/unpack, heartbeat, zlib/brotli handling, and fixture-based protocol tests.
- [ ] 3.4 Implement WebSocket client lifecycle with auth payload, heartbeat loop, bounded reconnect, and internal status reporting.
- [ ] 3.5 Implement event normalization and local webhook delivery queue with bounded retry/backoff.
- [ ] 3.6 Implement web/app internal danmaku webhook that authenticates requests, matches auth code, and atomically writes successful sessions to DB.
- [ ] 3.7 Remove `blivedm` production dependency and obsolete listener wrapper paths.
- [ ] 3.8 Add mocked watcher/internal-webhook tests for connect/auth, compressed message decode, matching auth code, duplicate events, webhook retry, disconnect, and reconnect status.

## 4. Runtime Role Split

- [ ] 4.1 Create explicit role entrypoints for `web`, `danmaku-worker`, and `scheduler`.
- [ ] 4.2 Move scheduler ownership out of Flask startup into the scheduler role and make it call web/app internal APIs instead of writing business DB state directly.
- [ ] 4.3 Move danmaku WebSocket ownership out of web startup into the danmaku worker role and make it call web/app internal APIs instead of writing business DB state directly.
- [ ] 4.4 Remove runtime `git pull` or auto-update behavior from normal role startup.
- [ ] 4.5 Update Dockerfile and Compose to run separate services with shared config/data volumes and role-specific commands.
- [ ] 4.6 Configure `INTERNAL_API_URL` and `INTERNAL_API_SECRET` for worker/scheduler-to-web communication.
- [ ] 4.7 Unify `settings.json.example`, Dockerfile `EXPOSE`, Compose ports, and healthcheck URL around one internal web port.
- [ ] 4.8 Add entrypoint smoke tests or command-level checks that do not require live Bilibili connectivity.

## 5. Admin UX And Documentation

- [ ] 5.1 Update admin status API/UI to show role, state, heartbeat age, last event time, last error, retry count, and next suggested action.
- [ ] 5.2 Update auth page polling responses so user-visible states distinguish waiting, success, expired, listener unavailable, and retrying.
- [ ] 5.3 Update Docker/manual operation docs for the new roles and clarify how to restart only the failed role.
- [ ] 5.4 Add migration/backup note for SQLite before applying the hard cut.

## 6. Verification

- [ ] 6.1 Run focused unit tests for auth state, QR login, watcher protocol/lifecycle, and runtime status.
- [ ] 6.2 Run `python3 -m compileall .`.
- [ ] 6.3 Run Docker Compose config/build checks supported by the local environment.
- [ ] 6.4 Verify no Playwright, `blivedm`, or runtime `git pull` path remains in production runtime.
- [ ] 6.5 Verify `danmaku-worker` and `scheduler` do not directly write business DB state in production runtime.
- [ ] 6.6 Produce a final implementation review report mapping each original user complaint to the fixed behavior and tests.

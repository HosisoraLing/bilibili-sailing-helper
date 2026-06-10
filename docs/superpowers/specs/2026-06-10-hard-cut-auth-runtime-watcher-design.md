---
comet_change: hard-cut-auth-runtime-watcher
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-10-hard-cut-auth-runtime-watcher
status: final
---

# Hard-Cut Auth Runtime Watcher Design

## Summary

This change replaces the current single-process runtime with explicit roles and removes the two heaviest reliability risks: Playwright-based QR login and the old `blivedm` listener. The final boundary is not shared SQLite across containers. The boundary is internal HTTP: `danmaku-worker` and `scheduler` report to `web`, and `web/app` owns all direct business database writes.

SQLite remains the current source of truth, but only behind the web/app service layer. This keeps the implementation light now and leaves a clean PostgreSQL migration path later.

## Architecture

### Runtime Roles

- `web`: Flask, SocketIO, public pages, admin APIs, internal APIs, QR login, Cookie validation, auth state machine, and all direct business DB writes.
- `danmaku-worker`: Bilibili live WebSocket connection, protocol decoding, event normalization, local retry queue, and internal webhook delivery.
- `scheduler`: periodic triggers for guard sync, gift/stat refresh, auth cleanup, Cookie maintenance, and internal API delivery.

The worker and scheduler do not import business DB writers and do not call `db.session.commit()` for production business state. They communicate with `web` through `INTERNAL_API_URL` and `INTERNAL_API_SECRET`.

### Data Flow

```text
User sends auth danmaku
  -> danmaku-worker receives Bilibili WS packet
  -> worker decodes and normalizes candidate event
  -> worker POSTs internal webhook to web/app
  -> web authenticates internal secret
  -> web matches uid/code against DB auth session
  -> web atomically marks success
  -> user polling /auth/status sees success
```

Scheduler follows the same ownership rule:

```text
scheduler tick
  -> scheduler POSTs internal job request/result to web/app
  -> web service layer performs DB mutation
  -> admin status reads persisted job/role status
```

## Internal API Contracts

Use a small set of internal endpoints instead of a generic RPC system:

- `POST /internal/danmaku/auth-event`
  - Payload: `uid`, `nickname`, `content`, `room_id`, `event_ts`, optional `avatar_url`, optional raw command metadata.
  - Behavior: authenticate secret, reject invalid payloads, idempotently process matching auth sessions.
- `POST /internal/runtime/heartbeat`
  - Payload: `role`, `instance_id`, `state`, `last_event_at`, `last_error`, `delivery_error`, `retry_count`, optional `cookie_version`.
  - Behavior: upsert role health and persist the worker's active Cookie version when present.
- `GET /internal/runtime/cookie`
  - Behavior: authenticate secret and return the currently validated runtime Cookie state for `danmaku-worker`: `status`, `version`, `updated_at`, integrity metadata, and the Cookie fields required for Bilibili API/WebSocket authentication.
  - Alternative: if Cookie bytes must not cross HTTP, this endpoint returns only `status`, `version`, and `updated_at`, while the worker reads the Cookie from an explicitly shared config volume after detecting a newer version.
- `POST /internal/scheduler/job`
  - Payload: `job_name`, `requested_at`, optional parameters.
  - Behavior: web/app runs or records the job through existing service layer.
- `POST /internal/scheduler/result`
  - Payload: `job_name`, `status`, `started_at`, `finished_at`, `summary`, `error`.
  - Behavior: persist last run status for admin health.

Authentication should be simple and explicit: compare the configured internal secret using constant-time comparison. Missing or invalid secrets return 401 and must not mutate state.

## QR Login

Replace Playwright with Bilibili Passport HTTP QR flow:

- Generate QR: `GET /x/passport-login/web/qrcode/generate`
- Poll QR: `GET /x/passport-login/web/qrcode/poll?qrcode_key=...`
- Validate Cookie: `/x/web-interface/nav`

Implementation reference:

- `/Users/nowanti/Play/Projects/bili-cli/internal/biliapi/client.go`
- `/Users/nowanti/Play/Projects/bili-cli/internal/cli/services.go`
- `/Users/nowanti/Play/Projects/bili-cli/internal/util/cookies.go`

Store QR task state in DB so admin refreshes and web restarts do not lose status. Do not replace the currently usable Cookie until the new Cookie validates successfully.

Successful validation must also advance a durable Cookie version. A timestamp such as `CookieMetadata.updated_at` is acceptable if tests can reliably compare it, but an explicit monotonically increasing `cookie_version` is preferred because it makes worker reload decisions and admin stale-state display unambiguous.

The old single-process compatibility path may restart the legacy listener after QR success, but the split-runtime contract must not depend on `web` calling an in-process listener restart. The durable flow is: QR success updates validated Cookie and version, `danmaku-worker` observes the newer version through the internal runtime Cookie contract, then reconnects its Bilibili WebSocket with the new Cookie.

## Native Watcher

Build a minimal in-repo watcher with these layers:

- Bilibili API client: room/server data, `getDanmuInfo`, WBI only if required.
- Protocol codec: packet pack/unpack, heartbeat, zlib/brotli expansion.
- Cookie provider: internal runtime Cookie status/access client, active version tracking, and reload signal.
- Live client: WebSocket connect, auth payload, heartbeat loop, reconnect/backoff, and reconnect-on-Cookie-version-change.
- Event normalizer: stable auth event shape from raw `DANMU_MSG`.
- Internal webhook client: bounded local queue, retry/backoff, delivery failure status.

Implementation reference:

- `/Users/nowanti/Play/Projects/v-nexus-core-monorepo/services/watcher/apps/watcher_bot/main.py`
- `/Users/nowanti/Play/Projects/v-nexus-core-monorepo/services/watcher/libs/bilibili/api.py`
- `/Users/nowanti/Play/Projects/v-nexus-core-monorepo/services/watcher/libs/bilibili/client.py`
- `/Users/nowanti/Play/Projects/v-nexus-core-monorepo/services/watcher/libs/bilibili/protocol.py`

The watcher should not decide whether a user is authenticated. It only reports candidate events. The web/app auth service owns matching, idempotency, expiration, and DB writes.

The watcher should decide only whether it has a usable Bilibili Cookie for its own connection. When no usable Cookie is available, it reports a Cookie-unavailable health state instead of silently running unauthenticated. When a newer validated Cookie appears while it is connected, it closes the old WebSocket and reconnects with the new Cookie without requiring a web restart.

## Database Ownership

SQLite remains the current DB. The important rule is ownership:

- web/app service layer owns business tables and commits.
- worker/scheduler use internal API and do not directly mutate business state.
- DB schema should be migration-friendly for PostgreSQL: keep repository/service boundaries explicit and avoid SQLite-only behavior in business logic where practical.

SQLite tuning is still useful inside web/app:

- short transactions
- `busy_timeout`
- WAL where compatible with deployment volume
- idempotent upserts for role status and auth attempts

## Admin And User Feedback

Admin status should show role-level health:

- role name
- state
- heartbeat age
- last event time
- last error
- delivery error
- retry count
- active Cookie version
- whether the worker Cookie is stale compared with the latest validated Cookie
- suggested next action

User auth polling should distinguish:

- waiting for danmaku
- success
- expired
- listener unavailable
- internal event delivery delayed
- retrying

The user should not need to know whether the failure is WebSocket, webhook delivery, Cookie, or scheduler. The UI should state what is happening and whether the user should wait, retry, or contact an admin.

## Testing Strategy

Add tests before implementation where the current code allows it, then expand tests as modules are introduced:

- Auth state: pending, success, expired, consumed, duplicate event idempotency.
- Internal API auth: missing secret, wrong secret, valid secret.
- Internal danmaku webhook: matching event marks success, non-matching event does not mutate.
- QR login: generated, scanned, expired, success, invalid Cookie, unknown Bilibili status.
- Protocol fixtures: heartbeat packet, compressed message batch, normalized `DANMU_MSG`.
- Worker retry: web unavailable, bounded retry, delivery error visible.
- Cookie reload: QR success advances Cookie version, worker heartbeat reports active version, stale worker state is visible, and worker reconnects when a newer Cookie appears.
- Scheduler: job trigger/result through internal API, no direct production DB writes.
- Runtime checks: Compose roles, canonical port, no Playwright, no `blivedm`, no runtime `git pull`.

## Risks And Mitigations

- Internal API unavailable blocks state writes: worker/scheduler use bounded retry/backoff and report delivery failure.
- SQLite remains a single-writer DB: only web/app writes business state, transactions stay short, and role status upserts are small.
- Bilibili protocol drift: isolate protocol code and test with fixtures from the watcher reference.
- Hard cut size: implement in dependency order and keep old compatibility paths out of production rather than maintaining dual modes.
- SocketIO cross-role events: polling remains canonical; SocketIO push is best-effort unless a later queue is introduced.

## Implementation Order

1. Add state models/repositories and internal API auth helpers.
2. Add internal endpoints and tests.
3. Replace QR login flow and remove Playwright.
4. Implement native watcher protocol/client and webhook delivery.
5. Split runtime entrypoints and Compose roles.
6. Move scheduler to internal API boundary.
7. Remove `blivedm`, runtime `git pull`, and inconsistent port contracts.
8. Run focused tests, compileall, Compose config/build checks, and final review mapping original complaints to fixes.

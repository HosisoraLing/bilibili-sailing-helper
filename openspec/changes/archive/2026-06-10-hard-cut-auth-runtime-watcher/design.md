## Context

Current runtime mixes HTTP serving, SocketIO, DB initialization, Bilibili guard syncing, gift/session cleanup, Cookie refresh, auto-update checks, and danmaku listening in one process. The old design made sense for a small helper script, but it creates three user-visible failure modes:

- Auth state can be lost or become unreadable after a successful danmaku because code/session state is not consistently database-backed.
- Listener restart can report success while the old thread is still exiting or the new listener is not actually receiving events.
- QR login depends on Playwright, which pulls in a browser runtime for a flow Bilibili exposes through HTTP endpoints.

The allowed hard cut changes the target: stop preserving the old listener/runtime shape and build the smallest reliable system on the existing stack.

## Goals / Non-Goals

**Goals:**

- Make SQLite the durable source of truth for auth sessions, QR login state, Cookie integrity, and runtime health, with web/app backend services as the only direct business-state writer.
- Replace Playwright QR login with Passport HTTP QR APIs inspired by the local `/Users/nowanti/Play/Projects/bili-cli` implementation.
- Replace `blivedm` with an in-repo native watcher using Bilibili `getDanmuInfo`, WebSocket auth, heartbeat, packet unpacking, and normalized event handling.
- Split deployment roles into `web`, `danmaku-worker`, and `scheduler` containers while keeping the same repo and Python stack.
- Give users and admins actionable feedback: waiting, scanned, expired, success, reconnecting, failed, last error, last event time, next retry.
- Add tests that can run without live Bilibili connectivity.

**Non-Goals:**

- No Redis, Celery, Postgres, Kubernetes, or language rewrite in this change.
- No route/admin modularization beyond what is necessary to support the runtime cut.
- No compatibility wrapper that keeps Playwright or `blivedm` available as an alternate production path.
- No promise that `python app.py` keeps starting every background role exactly as before; local convenience can exist, but Docker/runtime correctness wins.

## Decisions

### 1. Internal API is the runtime boundary; database is owned by web/app

Auth sessions, QR login tasks, Cookie integrity metadata, scheduler job state, and worker health SHALL live in SQLite. Direct business-state writes SHALL be owned by web/app backend services. `danmaku-worker` and `scheduler` SHALL report events, heartbeats, and job results through internal HTTP APIs protected by a shared internal secret.

**Why:** multi-container runtime cannot rely on globals, but exposing the SQLite file as the service boundary makes watcher/scheduler depend on schema details and makes future PostgreSQL migration harder. The local `v-nexus` watcher uses this cleaner shape: watcher captures Bilibili events and posts them to an internal webhook; the backend owns business decisions and persistence.

**Alternative considered:** all roles directly share the SQLite file. Rejected as the primary architecture because it creates multi-writer locking risk and couples worker code to the current DB schema. It may remain an implementation detail only inside the web/app process, not a cross-container contract.

**Alternative considered:** Redis or a queue. Rejected for now because the actual need is durable shared state and low-volume internal event ingestion, not high-throughput async jobs.

**User impact:** after sending the correct danmaku, refreshes, reconnects, and web restarts should not erase the success state.

### 2. QR login uses Bilibili Passport HTTP endpoints

The login service SHALL call:

- `GET /x/passport-login/web/qrcode/generate`
- `GET /x/passport-login/web/qrcode/poll?qrcode_key=...`
- `/x/web-interface/nav` for Cookie validation

The code should follow the local `/Users/nowanti/Play/Projects/bili-cli` shape: begin QR task, poll status, persist complete Cookie header, classify integrity (`invalid`, `auth_minimal`, `auth_recommended`, `search_ready` or project equivalents), and present clear admin messages.

Reference files for implementation:

- `/Users/nowanti/Play/Projects/bili-cli/internal/biliapi/client.go`
- `/Users/nowanti/Play/Projects/bili-cli/internal/cli/services.go`
- `/Users/nowanti/Play/Projects/bili-cli/internal/util/cookies.go`

**Why:** QR login is an HTTP protocol, not a browser automation problem. Removing Playwright reduces image size, startup cost, flaky browser install errors, and operational surprise.

**Alternative considered:** keep Playwright as fallback. Rejected because hard cut is explicitly allowed and fallback paths make production behavior harder to reason about.

**User impact:** admins can login/update Cookie faster and with clearer failure states: not scanned, scanned waiting confirm, expired, rejected, success, invalid Cookie.

### 3. Native watcher replaces `blivedm`

Implement a minimal in-repo watcher with clear layers:

- Bilibili API client: `getDanmuInfo`, WBI signing if needed, room id resolution.
- Protocol codec: packet pack/unpack, heartbeat, zlib/brotli handling.
- Live client: WebSocket connect, auth payload, heartbeat loop, reconnect policy.
- Event normalizer: convert raw commands into auth-relevant events.
- Internal webhook client: enqueue and POST candidate auth events to web/app.
- Web/app auth handler: authenticate internal calls, match UID/code, and write success to DB atomically.

**Why:** current issue is core listener reliability. Keeping an old library while splitting runtime preserves the highest-risk dependency.

**Alternative considered:** adapt existing `blivedm` wrapper with locks/status. Rejected because earlier review already showed lifecycle and observability gaps; a native minimal watcher is easier to test against known packets and status transitions.

Reference files for implementation:

- `/Users/nowanti/Play/Projects/v-nexus-core-monorepo/services/watcher/apps/watcher_bot/main.py`
- `/Users/nowanti/Play/Projects/v-nexus-core-monorepo/services/watcher/libs/bilibili/api.py`
- `/Users/nowanti/Play/Projects/v-nexus-core-monorepo/services/watcher/libs/bilibili/client.py`
- `/Users/nowanti/Play/Projects/v-nexus-core-monorepo/services/watcher/libs/bilibili/protocol.py`

**User impact:** “弹幕鉴权总出问题” gets addressed at the event source, not just by improving the HTTP polling layer.

### 4. Runtime roles are separate containers, not microservices

Docker Compose SHALL define at least:

- `web`: Flask, SocketIO, HTTP routes, templates, admin API, internal API, and all direct business DB writes.
- `danmaku-worker`: Bilibili live WebSocket watcher, event normalization, internal webhook reporting, and local process health.
- `scheduler`: periodic guard sync, gift/stat refresh, auth cleanup triggers, Cookie maintenance triggers, and internal API reporting.

Only `web` requires direct DB volume access for business state. `danmaku-worker` and `scheduler` use `INTERNAL_API_URL` plus `INTERNAL_API_SECRET`, matching the watcher reference project shape. Each role has its own entrypoint and log prefix.

**Why:** a watcher crash should not take down the web UI, and scheduler errors should not be mistaken for listener failure.

**Alternative considered:** one container with a process supervisor. Rejected because Docker Compose already provides role boundaries, logs, restart policies, and health checks with less custom code.

**User impact:** admins can see and restart the failed part; the website can keep explaining what is happening instead of disappearing.

### 5. Remove runtime code mutation

Business runtime SHALL NOT execute `git pull` or auto-update code while serving users. Updates belong to deployment, not request/runtime logic.

**Why:** changing code under a running process makes crashes and data state hard to diagnose.

**User impact:** server behavior becomes predictable; upgrades can be tested and rolled back as deployment events.

## Risks / Trade-offs

- Web/app internal API availability becomes a dependency for worker/scheduler state writes -> keep payloads small, add bounded retry/backoff queues, and surface webhook delivery failures in role health.
- SQLite write contention remains possible inside web/app -> keep writes short, use WAL/busy timeout where compatible, and centralize repository/service functions.
- Bilibili protocol drift -> isolate API/protocol code, add packet fixtures and explicit error classification, keep admin messages factual.
- SocketIO cross-container notification gap -> web polling remains the durable UX path; realtime push can be best-effort unless a future queue is added.
- Hard cut increases short-term change size -> tasks are grouped by testable boundaries; old Playwright/`blivedm` paths are removed rather than maintained in parallel.
- QR status code mapping may drift -> implement named status constants and tests around observed mappings; unknown codes become actionable admin errors.

## Migration Plan

1. Add DB schema/state services and internal API contracts first with tests.
2. Implement QR login service and admin endpoints without Playwright.
3. Implement native watcher with fixture-based protocol tests before wiring to internal webhook reporting.
4. Add runtime entrypoints and Compose roles; keep manual local commands documented.
5. Remove Playwright/`blivedm` dependencies and runtime `git pull`.
6. Run syntax/tests/config checks; then verify Docker Compose config/build as local environment allows.

Rollback is code-level: redeploy the previous commit and keep the SQLite DB backup created before migration. New tables should be additive where practical, but production behavior does not need to preserve old Playwright/`blivedm` paths.

## Open Questions

- Final QR rendering shape: backend returns QR URL only, backend renders PNG, or admin page renders QR client-side. Default should minimize server dependencies: return URL/key and let the page render.
- Exact Cookie integrity labels: reuse `bili-cli` labels verbatim or map them to Chinese admin-facing labels.
- Whether SocketIO needs cross-container event broadcast in this change. Default: polling is canonical, SocketIO remains web-local best effort.

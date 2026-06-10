# Comet Design Handoff

- Change: hard-cut-auth-runtime-watcher
- Phase: design
- Mode: compact
- Context hash: bb7d997821944dd02e37eb8330812208dc6d3aeb9e331e44efb009ac68299806

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/hard-cut-auth-runtime-watcher/proposal.md

- Source: openspec/changes/hard-cut-auth-runtime-watcher/proposal.md
- Lines: 1-38
- SHA256: 92de2c43a4326b7b2b10fe636089e9a5c592d50ec6352626cbd60ffe9a7a37d3

```md
## Why

弹幕鉴权和服务器稳定性问题的根因不是单点 bug，而是认证、弹幕监听、后台任务、部署健康检查都挤在同一进程里，并且关键状态散落在内存、线程和临时对象中。用户看到的结果是扫码重、鉴权飘、弹幕发了没反馈、管理员点重启也不知道是否真的恢复。

本变更允许一次性硬切：在基础技术栈保持 Python、Flask、SQLite、Docker Compose 的前提下，移除 Playwright 和老旧 `blivedm` 依赖，把认证与监听链路改成由 web/app 后端统一落库、其他运行角色通过 internal API 上报的可观测、可重启、可测试模型。

## What Changes

- **BREAKING**: 移除 Playwright 扫码登录运行依赖，改为 Bilibili Passport HTTP QR flow：生成二维码、轮询状态、保存 Cookie、校验 Cookie 完整性。
- **BREAKING**: 移除 `blivedm` 作为弹幕监听核心，改为项目内原生最小 Bilibili live WebSocket watcher，参考本机 `/Users/nowanti/Play/Projects/v-nexus-core-monorepo/services/watcher` 和 `/Users/nowanti/Play/Projects/bili-cli` 的已验证实现思路。
- **BREAKING**: Docker Compose 从单容器多职责改为多容器运行角色：`web`、`danmaku-worker`、`scheduler`。
- 将 `AuthSession`、二维码登录任务、Cookie 完整性、worker health/status 这类跨进程状态落到 SQLite，但 DB 写入 owner 归一到 web/app 后端服务层；`danmaku-worker` 和 `scheduler` 通过内部 API/webhook 上报事件、心跳和任务结果。
- 修复 Docker port、healthcheck、示例配置的运行契约不一致问题。
- 移除业务运行时内的 `git pull`/自动更新行为。
- 管理端状态从“线程是否活着”升级为“哪个角色健康、最近错误是什么、下一步建议是什么”。
- 为认证状态流、QR 登录、原生 watcher 协议解析/重连、worker 启停、Docker 配置一致性补充回归测试。
- 保持一个合并 change，不拆多个 OpenSpec changes：这是一次有意硬切，认证状态、监听核心、运行角色和部署契约互相依赖，拆开会保留旧债并延长用户可见不稳定期。

## Capabilities

### New Capabilities

- `passport-qr-login`: 定义无浏览器依赖的 Bilibili QR 登录、Cookie 校验和管理员反馈。
- `database-backed-auth`: 定义弹幕鉴权状态、登录任务、Cookie/worker 状态以 web/app 后端管理的数据库为事实源。
- `native-danmaku-watcher`: 定义原生 Bilibili 弹幕监听、协议处理、重连、事件归一化和内部 webhook 上报。
- `split-runtime-roles`: 定义 Web、弹幕 worker、scheduler 多容器职责、内部 API 边界、健康检查和部署契约。

### Modified Capabilities

- None. 当前仓库没有已归档主 specs，本变更新增能力规格。

## Impact

- Affected code: `app.py`, `routes.py`, `services/auth_service.py`, `services/cookie_service.py`, `services/danmaku_listener.py`, new watcher/runtime modules, scheduler setup, DB models/init, admin status routes/templates.
- Affected operations: local manual run, Docker Compose deployment, admin Cookie login, auth page polling, listener restart/status, periodic guard/gift/session cleanup.
- Dependencies: remove Playwright runtime/browser dependency and `blivedm`; add only small protocol/HTTP dependencies if not already present. Do not introduce Redis, Celery, Postgres, or a new language runtime in this change.
- Data: SQLite remains the source of truth for this change, but only web/app backend services write business state directly. New tables/columns are acceptable for QR login sessions, cookie integrity metadata, auth attempts, scheduler jobs, and worker status. The worker/scheduler boundary must remain HTTP/internal-API based so future PostgreSQL migration does not require rewriting the watcher.
- User impact: users should no longer experience “弹幕发了但系统没认”； admins should see actionable status and can restart only the failed runtime role instead of treating the whole server as crashed.
```

## openspec/changes/hard-cut-auth-runtime-watcher/design.md

- Source: openspec/changes/hard-cut-auth-runtime-watcher/design.md
- Lines: 1-137
- SHA256: 53f288210bda5cc8a2f52cfdba1699b40378bbe1550dfa551b598f40ba017c07

[TRUNCATED]

```md
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
```

Full source: openspec/changes/hard-cut-auth-runtime-watcher/design.md

## openspec/changes/hard-cut-auth-runtime-watcher/tasks.md

- Source: openspec/changes/hard-cut-auth-runtime-watcher/tasks.md
- Lines: 1-55
- SHA256: 466d31667eef29b18670a19714413bcd72cd1dae0400c81714136915ab4cca31

```md
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
```

## openspec/changes/hard-cut-auth-runtime-watcher/specs/database-backed-auth/spec.md

- Source: openspec/changes/hard-cut-auth-runtime-watcher/specs/database-backed-auth/spec.md
- Lines: 1-37
- SHA256: b2dfd48b6b130b4a8bda396b5a0b0183e8594477726712fbf925f73d71e3d0d5

```md
## ADDED Requirements

### Requirement: Auth state is durable
The system SHALL store auth sessions and auth attempts in the web/app-managed database as the source of truth.

#### Scenario: Danmaku success survives web restart
- **WHEN** the danmaku worker reports a matching auth event to the internal webhook and web/app marks the auth session successful
- **THEN** the web runtime can read that success after its process restarts, until the session expires or is consumed

#### Scenario: Expired session is rejected
- **WHEN** an auth session is past its expiration time
- **THEN** registration, login continuation, and reset-password continuation MUST reject it and instruct the user to restart auth

### Requirement: Auth success transition is atomic
The system SHALL allow only one valid pending auth session to transition to success for a matched UID/code pair.

#### Scenario: Duplicate matching danmaku
- **WHEN** two matching danmaku events are processed for the same session
- **THEN** exactly one success transition is recorded and later reads return one consistent successful session

### Requirement: Internal event ingestion is authenticated
The system SHALL accept worker and scheduler writes only through authenticated internal APIs.

#### Scenario: Worker reports without secret
- **WHEN** a danmaku worker webhook request omits or sends an invalid internal secret
- **THEN** the web/app backend rejects the request and does not update auth or health state

### Requirement: Worker status is persistent
The system SHALL store runtime role health in the database with timestamps, last error, last delivery error, and last event metadata.

#### Scenario: Worker reports reconnecting
- **WHEN** the danmaku worker loses its WebSocket and starts reconnecting
- **THEN** the worker reports reconnecting through internal API and the web admin status shows `danmaku-worker` as reconnecting with last error time and retry count

#### Scenario: Worker stops updating heartbeat
- **WHEN** a role heartbeat is stale beyond the configured threshold
- **THEN** the admin status marks that role unhealthy and explains that the role should be restarted
```

## openspec/changes/hard-cut-auth-runtime-watcher/specs/native-danmaku-watcher/spec.md

- Source: openspec/changes/hard-cut-auth-runtime-watcher/specs/native-danmaku-watcher/spec.md
- Lines: 1-36
- SHA256: 4010161a15ff5b85ecda9dbd9305d1caf0d55629674bedf56b55b3d189774e4c

```md
## ADDED Requirements

### Requirement: Native Bilibili live connection
The system SHALL connect to Bilibili live danmaku using an in-repo native watcher rather than `blivedm`.

#### Scenario: Watcher authenticates to live WebSocket
- **WHEN** the danmaku worker starts for a configured live room
- **THEN** it fetches danmaku server info, opens a WebSocket, sends the auth payload, and starts heartbeat

### Requirement: Protocol packets are decoded
The system SHALL decode Bilibili live packets including heartbeat replies and compressed message batches.

#### Scenario: Compressed danmaku packet is received
- **WHEN** the WebSocket receives a compressed packet containing danmaku events
- **THEN** the watcher expands it and emits normalized message events for auth matching

### Requirement: Auth events are normalized and reported
The system SHALL normalize raw Bilibili events into stable fields and report candidate auth events to the web/app internal webhook.

#### Scenario: User sends auth code
- **WHEN** a live message event contains sender UID, sender name, and text
- **THEN** the danmaku worker posts the normalized event to the internal webhook and web/app compares it with active auth sessions

### Requirement: Reconnect is observable
The system SHALL reconnect with bounded backoff and report each connection state change through internal API.

#### Scenario: WebSocket disconnects
- **WHEN** the danmaku WebSocket disconnects unexpectedly
- **THEN** the worker reports the disconnect reason, increments reconnect count, and retries without requiring web runtime restart

### Requirement: Webhook delivery is retried
The system SHALL queue candidate auth events locally in the danmaku worker and retry internal webhook delivery with bounded backoff.

#### Scenario: Web internal API is temporarily unavailable
- **WHEN** the danmaku worker detects a candidate auth event while web/app internal API is unavailable
- **THEN** the worker retries delivery and reports delivery failure in its health state without writing directly to the database
```

## openspec/changes/hard-cut-auth-runtime-watcher/specs/passport-qr-login/spec.md

- Source: openspec/changes/hard-cut-auth-runtime-watcher/specs/passport-qr-login/spec.md
- Lines: 1-34
- SHA256: 938b37e8c78cfa461ec1c00bb2034301969f012059924ad7154a803d0a6d9c69

```md
## ADDED Requirements

### Requirement: Browserless QR login
The system SHALL support Bilibili account QR login through HTTP Passport APIs without Playwright or a browser runtime.

#### Scenario: QR task is created
- **WHEN** an admin starts QR login
- **THEN** the system persists a QR login task with a QR URL, qrcode key, expiration time, and `pending` status

#### Scenario: QR task is polled
- **WHEN** an admin polls an active QR login task
- **THEN** the system calls the Passport poll API and updates the task status to waiting, scanned, expired, failed, or succeeded

### Requirement: Cookie integrity validation
The system SHALL validate completed Bilibili Cookies before marking them usable.

#### Scenario: Login succeeds with valid Cookie
- **WHEN** QR polling returns a successful login Cookie
- **THEN** the system validates it with Bilibili account navigation API and records account metadata and integrity status

#### Scenario: Login returns invalid Cookie
- **WHEN** Cookie validation fails
- **THEN** the system stores a failed status with an actionable admin message and MUST NOT replace the currently usable Cookie

### Requirement: Admin-facing QR feedback
The system SHALL show QR login status in language that tells the admin what to do next.

#### Scenario: QR expires
- **WHEN** the QR login task expires before success
- **THEN** the admin status explains that the QR code expired and offers starting a new QR login

#### Scenario: Unknown Passport status
- **WHEN** Bilibili returns an unrecognized QR status code
- **THEN** the admin status records the raw code and explains that login should be retried or investigated
```

## openspec/changes/hard-cut-auth-runtime-watcher/specs/split-runtime-roles/spec.md

- Source: openspec/changes/hard-cut-auth-runtime-watcher/specs/split-runtime-roles/spec.md
- Lines: 1-44
- SHA256: 458bacdcbfbf7892ddb8a4f1edd473e08653e51a8c91b8099f616b13ef6ef033

```md
## ADDED Requirements

### Requirement: Runtime roles are explicit
The system SHALL provide separate entrypoints for `web`, `danmaku-worker`, and `scheduler` roles.

#### Scenario: Web role starts
- **WHEN** the `web` role starts
- **THEN** it serves HTTP, SocketIO, admin APIs, internal APIs, and owns all direct business database writes without owning the danmaku WebSocket loop or scheduled background jobs

#### Scenario: Danmaku worker starts
- **WHEN** the `danmaku-worker` role starts
- **THEN** it owns the live WebSocket watcher and reports auth/status events to web/app through internal API

#### Scenario: Scheduler starts
- **WHEN** the `scheduler` role starts
- **THEN** it owns periodic triggers for guard sync, gift/stat refresh, Cookie maintenance, and expired auth cleanup, and reports job requests/results to web/app through internal API

### Requirement: Internal API boundary is explicit
The system SHALL use `INTERNAL_API_URL` and `INTERNAL_API_SECRET` for role-to-web communication.

#### Scenario: Worker posts an internal event
- **WHEN** `danmaku-worker` or `scheduler` sends an internal request
- **THEN** the request targets `web` internal API, includes the configured secret, and does not require direct database file access from that role

### Requirement: Docker configuration is consistent
The system SHALL use one canonical internal web port across sample settings, Dockerfile exposure, Compose service port, and healthcheck URL.

#### Scenario: Compose config is rendered
- **WHEN** Docker Compose configuration is validated
- **THEN** the web service port mapping and healthcheck target point to the same internal Flask port

### Requirement: Runtime update is deployment-owned
The system SHALL NOT run `git pull` or mutate application code from normal business runtime startup.

#### Scenario: App starts in production
- **WHEN** any runtime role starts
- **THEN** it does not update source code and logs only the current version/config state

### Requirement: Admin health is role-based
The system SHALL expose role-level health for web, danmaku worker, and scheduler.

#### Scenario: Scheduler fails but web is healthy
- **WHEN** the scheduler records a failed job while web continues serving
- **THEN** admin status shows scheduler failure separately and does not imply the web server is down
```


# Comet Design Handoff

- Change: tv-token-cookie-auto-refresh
- Phase: design
- Mode: compact
- Context hash: 351ebec2c5ec6ff6cf585ec1b9125225bc5e279132e4ccbff621f9c8f198d2e6

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/tv-token-cookie-auto-refresh/proposal.md

- Source: openspec/changes/tv-token-cookie-auto-refresh/proposal.md
- Lines: 1-32
- SHA256: 8db129954069c82f4c460b5cecfde81bcc597d542f1a10969456ee916f52de8b

```md
## Why

The current project can validate Bilibili Web Cookies and can ask an admin to scan a QR code, but it does not preserve a refreshable authorization credential. Admins still risk having to manually repair runtime Cookie state when `SESSDATA` approaches expiration.

The reference repository `/Users/nowanti/Work/github/renmu123/biliLive-tools` shows a stronger pattern: use TV QR login to obtain `access_token`, `refresh_token`, and `cookie_info.cookies`, then refresh authorization when the returned `SESSDATA` is close to expiry.

## What Changes

- Add a TV QR authorization flow for the admin Bilibili account, separate from the existing Web Passport QR flow.
- Persist refreshable Bilibili account authorization metadata: access token, refresh token, raw auth payload, cookie expiration, and extracted Web Cookie map.
- Add automatic Cookie maintenance that refreshes TV authorization before `SESSDATA` expires and updates runtime Web Cookies only after validation succeeds.
- Fix the scheduler job execution contract so `cookie-maintenance` requests are actually executed by the web role, not only recorded as requested jobs.
- Preserve the existing runtime boundary: `web` owns credential storage and business DB writes; `danmaku-worker` reads validated runtime Cookie through the internal API and reloads when `cookie_version` changes.
- Surface actionable admin status for valid, expiring, refresh failed, refresh-token invalid, and needs-rescan states.

## Capabilities

### New Capabilities

- `tv-token-auth`: TV QR login and refresh-token authorization for the admin Bilibili account.

### Modified Capabilities

- `passport-qr-login`: Admin Cookie login behavior expands to support refreshable TV authorization while preserving safe Cookie validation.
- `split-runtime-roles`: Scheduler-owned `cookie-maintenance` becomes an executed web-owned job that can refresh authorization and advance runtime Cookie version.

## Impact

- Affected code: Bilibili auth/Cookie services, admin Cookie routes/templates, internal scheduler API, runtime Cookie service, scheduler tests, DB models/migrations, settings example, Docker/runtime docs.
- Affected data: new or extended credential metadata for TV authorization and Cookie expiry. Real tokens and Cookies remain sensitive runtime data and MUST NOT be committed.
- Affected operations: initial admin login flow, periodic Cookie maintenance, danmaku worker Cookie reload, admin status and recovery guidance.
- Reference implementation: `renmu123/biliLive-tools` at `b730b7ec`, especially `TvQrcodeLogin`, `addUser`, `updateAuth`, and `checkAccountLoop`.
```

## openspec/changes/tv-token-cookie-auto-refresh/design.md

- Source: openspec/changes/tv-token-cookie-auto-refresh/design.md
- Lines: 1-89
- SHA256: e7ee16aee73fea9b3d5135302cd1b6ec492b771fc3c795b908196b4889f8e394

[TRUNCATED]

```md
## Context

The current `main` branch's old "Cookie auto refresh" only refreshed `buvid3` through Playwright; it did not renew `SESSDATA`. The hard-cut runtime branch removed Playwright and introduced browserless Web Passport QR login, Cookie metadata, `cookie_version`, `danmaku-worker` reload, and a scheduler role. That branch still lacks a real refreshable Bilibili authorization model and its scheduler job endpoint currently records requests without a complete execution loop in the deployed runtime.

The local reference repo `/Users/nowanti/Work/github/renmu123/biliLive-tools` uses `@renmu/bili-api` `TvQrcodeLogin` to get a TV authorization payload. It stores `cookie_info.cookies`, `access_token`, `refresh_token`, and raw auth data, then refreshes authorization when `SESSDATA` has less than 10 days remaining. This is the right model for reducing manual admin maintenance, but it is not a full self-healing account system: refresh token expiry, risk control, and upstream API changes still require a new scan.

## Goals / Non-Goals

**Goals:**

- Let an admin perform an initial TV QR login and persist refreshable authorization metadata.
- Extract and validate Web Cookie values from TV auth responses before replacing runtime Cookies.
- Refresh authorization automatically before Cookie expiry and advance `cookie_version` on successful Cookie replacement.
- Ensure scheduler-triggered `cookie-maintenance` is actually executed by `web`, while `scheduler` remains outside direct DB ownership.
- Make admin status explain whether the system is valid, expiring, refreshing, failed, or requires a new scan.
- Add tests for success, failure, scheduler execution, version advancement, and worker reload decisions.

**Non-Goals:**

- No account pool or anti-risk-control system.
- No promise that invalid refresh tokens can recover without admin scanning.
- No rewrite of existing Bilibili business APIs to rely only on TV `access_token`.
- No unrelated route/admin modularization.
- No real token, Cookie, or account data in source, docs, tests, or examples.

## Decisions

### 1. TV token is a refresh credential; Web Cookie remains the runtime credential

The system SHALL use TV `access_token` and `refresh_token` only to refresh authorization. Existing Bilibili Web/live calls continue to receive a normal Cookie header built from validated Web Cookie values such as `SESSDATA`, `bili_jct`, `DedeUserID`, and `buvid3`.

**Why:** current APIs already expect Web Cookies, and the reference implementation also extracts `cookie_info.cookies` after TV login/refresh. Treating TV token as a direct replacement would create compatibility risk across Bilibili endpoints.

**Alternative considered:** convert all Bilibili calls to TV-token APIs. Rejected because the current project depends on Web/live endpoints and only needs refreshable Cookie maintenance.

### 2. Store full auth payload plus normalized credential fields

Persist raw TV auth JSON for audit/debug, but expose normalized fields for runtime logic: `access_token`, `refresh_token`, `mid`, `cookie_map`, `sessdata_expires_at`, `last_refresh_at`, `last_validated_at`, `status`, `last_error`, and monotonically increasing `cookie_version`.

**Why:** Bilibili payload shape may drift. Raw payload helps diagnose drift; normalized fields keep application logic stable and testable.

**Alternative considered:** keep everything in `settings.json`. Rejected because refresh state, expiry, validation, and failure history are shared runtime state and belong with existing Cookie metadata.

### 3. Refresh only when it is useful and safe

`cookie-maintenance` SHALL validate current Cookie state and refresh only when the stored `SESSDATA` expiry is inside a configured threshold, defaulting to 10 days. Refresh success must pass Web Cookie validation before replacing runtime Cookie values. Refresh failure must preserve the previous usable Cookie and record an actionable error.

**Why:** unnecessary refresh increases risk. Replacing a working Cookie with an invalid one would break danmaku auth and guard sync.

**Alternative considered:** refresh every scheduler interval. Rejected because it creates needless upstream calls and makes failure noise worse.

### 4. Scheduler triggers; web executes

The `scheduler` role SHALL continue to trigger periodic job requests through internal API. The `web` role SHALL execute `cookie-maintenance` inside the web/app process and record the result. This may be implemented as immediate execution on the internal job request or as a web-owned pending-job runner, but it must not leave jobs permanently in `requested`.

**Why:** only web should directly write business DB/config state. The user-visible effect of a scheduler is execution, not just request logging.

**Alternative considered:** let `scheduler` import app services and write DB/config directly. Rejected because it breaks the runtime responsibility split.

### 5. Verify the TV-to-Web Cookie bridge before treating it as production behavior

Implementation SHALL include a minimal real-chain validation path that takes a TV login/refresh response and verifies the extracted Cookie with `/x/web-interface/nav`, `getDanmuInfo`, and the current guard list endpoint before claiming compatibility.

**Why:** the reference implementation demonstrates the pattern, but this project must prove the specific endpoints it uses accept the resulting Web Cookie.

## Risks / Trade-offs

- TV refresh endpoint or payload shape changes -> keep payload parsing isolated and record raw response/status for admin diagnosis.
- Refresh token expires or Bilibili risk control blocks refresh -> preserve last usable Cookie and tell admin to rescan.
- `SESSDATA` expiry is missing from payload -> validate current Cookie and mark expiry unknown; do not claim automatic refresh coverage until a valid expiry is observed.
- Scheduler request execution could block web if long-running -> keep the first version bounded with timeouts; if it becomes slow, move to a web-owned job runner without changing the external contract.
- Storing refresh tokens raises sensitivity -> keep them in runtime config/database only, never in docs/examples/logs; mask admin output.

## Migration Plan

1. Add additive storage for TV authorization and Cookie expiry metadata.
2. Implement TV QR login and refresh service with mocked tests.
3. Wire admin TV login/status endpoints and safe Cookie replacement.
4. Make `cookie-maintenance` execute through web-owned job handling.
5. Connect successful refresh to `cookie_version` so `danmaku-worker` reloads.
```

Full source: openspec/changes/tv-token-cookie-auto-refresh/design.md

## openspec/changes/tv-token-cookie-auto-refresh/tasks.md

- Source: openspec/changes/tv-token-cookie-auto-refresh/tasks.md
- Lines: 1-40
- SHA256: fffec52164fee7eba469ebdeb02df0ac1e5ce3c4dd8b4b9786c040948697566d

```md
## 1. Protocol Research And State Model

- [ ] 1.1 Map `renmu123/biliLive-tools` TV QR login, refresh, Cookie extraction, and expiry-check code paths into Python implementation notes.
- [ ] 1.2 Add additive storage for TV authorization metadata, raw auth payload, Cookie expiry, validation status, and masked admin display fields.
- [ ] 1.3 Add tests for parsing TV auth payloads, extracting Web Cookies, reading `SESSDATA` expiry, and masking sensitive fields.

## 2. TV QR Login And Refresh Service

- [ ] 2.1 Implement TV QR login begin/poll service without Playwright.
- [ ] 2.2 Implement TV authorization refresh with stored `access_token` and `refresh_token`.
- [ ] 2.3 Validate extracted Web Cookies with `/x/web-interface/nav` before replacing runtime Cookie settings.
- [ ] 2.4 Preserve the last usable Cookie when login or refresh returns invalid Cookie data.
- [ ] 2.5 Add mocked tests for pending, scanned, expired, successful login, successful refresh, invalid Cookie, invalid refresh token, and unknown upstream response.

## 3. Runtime Cookie Maintenance

- [ ] 3.1 Implement `cookie-maintenance` semantics: validate current Cookie, refresh only when expiry is within threshold, and record status.
- [ ] 3.2 Make successful refresh update Web Cookie values and increment `cookie_version`.
- [ ] 3.3 Make failed refresh produce clear admin next actions without overwriting usable Cookie.
- [ ] 3.4 Add tests for not-yet-expiring Cookie, expiring Cookie refresh, refresh failure, missing expiry, and version advancement.

## 4. Scheduler Execution Boundary

- [ ] 4.1 Fix internal scheduler job handling so `cookie-maintenance` is executed by web or a web-owned job runner after scheduler trigger.
- [ ] 4.2 Ensure `scheduler` still does not import business writers or write the database/config directly.
- [ ] 4.3 Add tests proving scheduler-triggered `cookie-maintenance` reaches terminal success/failure instead of staying `requested`.

## 5. Admin UX And Documentation

- [ ] 5.1 Update admin Cookie status to show TV authorization state, Cookie expiry, last validation, last refresh, refresh failure, and next action.
- [ ] 5.2 Update admin login flow copy so admins understand TV QR login enables automatic refresh but cannot recover invalid refresh tokens without rescanning.
- [ ] 5.3 Update `settings.json.example`, Docker/manual docs, and sensitive-data notes for TV tokens and refresh tokens.

## 6. Verification

- [ ] 6.1 Run focused unit tests for TV auth parsing, refresh, Cookie maintenance, scheduler execution, and runtime Cookie versioning.
- [ ] 6.2 Run `python -m compileall .`.
- [ ] 6.3 Run Docker Compose config check.
- [ ] 6.4 Run source search to verify no real tokens/Cookies are committed and sensitive values are masked in admin outputs.
- [ ] 6.5 When credentials are available, run a manual real-chain validation against `/x/web-interface/nav`, `getDanmuInfo`, and the current guard list endpoint.
```

## openspec/changes/tv-token-cookie-auto-refresh/specs/passport-qr-login/spec.md

- Source: openspec/changes/tv-token-cookie-auto-refresh/specs/passport-qr-login/spec.md
- Lines: 1-31
- SHA256: 2b16f51aec986a94427850f34f22d978fcd8b2e6f2658de7bd6b750b3f7cd6bc

```md
## MODIFIED Requirements

### Requirement: Browserless QR login
The system SHALL support browserless Bilibili account QR login without Playwright or a browser runtime, including Web Passport QR login and TV QR authorization when refreshable credentials are required.

#### Scenario: Web QR task is created
- **WHEN** an admin starts Web QR login
- **THEN** the system persists a QR login task with a QR URL, qrcode key, expiration time, and `pending` status

#### Scenario: TV QR task is created
- **WHEN** an admin starts TV QR authorization
- **THEN** the system persists a TV QR login task with the data needed to poll Bilibili and later store refreshable token metadata

#### Scenario: QR task is polled
- **WHEN** an admin polls an active QR login task
- **THEN** the system calls the matching Bilibili poll API and updates the task status to waiting, scanned, expired, failed, or succeeded

### Requirement: Cookie integrity validation
The system SHALL validate completed Bilibili Cookies before marking them usable, whether they came from Web Passport QR login or TV QR authorization refresh.

#### Scenario: Login succeeds with valid Cookie
- **WHEN** QR polling or TV authorization refresh returns a successful login Cookie
- **THEN** the system validates it with Bilibili account navigation API and records account metadata, integrity status, and a monotonically changing Cookie version or update timestamp

#### Scenario: Login returns invalid Cookie
- **WHEN** Cookie validation fails
- **THEN** the system stores a failed status with an actionable admin message and MUST NOT replace the currently usable Cookie

#### Scenario: Login updates Cookie while worker is running
- **WHEN** a valid QR login or TV authorization refresh replaces the usable Cookie
- **THEN** the system exposes the new Cookie version through the internal runtime contract so the danmaku worker can reload without requiring a web process restart
```

## openspec/changes/tv-token-cookie-auto-refresh/specs/split-runtime-roles/spec.md

- Source: openspec/changes/tv-token-cookie-auto-refresh/specs/split-runtime-roles/spec.md
- Lines: 1-31
- SHA256: 86498b7bb643a91a5e869e32c7e1e9a33e77418ac001e0ca38abedc69685645d

```md
## MODIFIED Requirements

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

### Requirement: Scheduler jobs execute through web-owned handlers
The system SHALL ensure scheduler-triggered jobs are executed by the web role or a web-owned runner, not merely recorded as requested tasks.

#### Scenario: Scheduler triggers Cookie maintenance
- **WHEN** the scheduler posts a `cookie-maintenance` job request to the internal API
- **THEN** the web role executes the Cookie maintenance handler, records success or failure, and leaves the job in a terminal status rather than permanently `requested`

#### Scenario: Cookie maintenance refreshes credentials
- **WHEN** the web-owned Cookie maintenance handler refreshes TV authorization successfully
- **THEN** it updates validated runtime Cookie state and increments `cookie_version` so `danmaku-worker` can reload

#### Scenario: Cookie maintenance cannot refresh credentials
- **WHEN** the web-owned Cookie maintenance handler cannot refresh authorization
- **THEN** it records a failed scheduler result with an admin-actionable error and preserves the last usable Cookie
```

## openspec/changes/tv-token-cookie-auto-refresh/specs/tv-token-auth/spec.md

- Source: openspec/changes/tv-token-cookie-auto-refresh/specs/tv-token-auth/spec.md
- Lines: 1-37
- SHA256: a14a7dc4f8342ec124ccc8467612642ba02b1d943ab26ad0a73c0e3c57b36354

```md
## ADDED Requirements

### Requirement: TV QR authorization can be created
The system SHALL allow an admin to start a Bilibili TV QR authorization flow that returns a QR URL and persists a server-side login task.

#### Scenario: Admin starts TV QR login
- **WHEN** an admin starts TV QR authorization
- **THEN** the system creates a login task with a QR URL, task identifier, expiration time, and pending status

### Requirement: TV authorization stores refreshable credentials
The system SHALL persist refreshable TV authorization metadata and extracted Web Cookies only after the returned Cookie validates successfully.

#### Scenario: TV QR login succeeds
- **WHEN** Bilibili returns a successful TV authorization payload containing `access_token`, `refresh_token`, and `cookie_info.cookies`
- **THEN** the system stores normalized credential metadata, stores the raw auth payload, validates the extracted Web Cookie, and advances the runtime Cookie version

#### Scenario: TV QR login returns invalid Web Cookie
- **WHEN** the TV authorization payload cannot produce a Web Cookie that passes validation
- **THEN** the system records a failed login state and MUST NOT replace the last usable Cookie

### Requirement: TV authorization can be refreshed
The system SHALL refresh Bilibili authorization with stored TV `access_token` and `refresh_token` before the extracted `SESSDATA` expires.

#### Scenario: Refresh succeeds
- **WHEN** Cookie maintenance refreshes a valid TV authorization
- **THEN** the system stores the new tokens, raw auth payload, Web Cookie map, expiry metadata, and increments the runtime Cookie version

#### Scenario: Refresh token is invalid
- **WHEN** Bilibili rejects the stored refresh token or returns an unrecoverable authorization error
- **THEN** the system preserves the last usable Cookie, marks the account as requiring a new scan, and reports an actionable admin status

### Requirement: TV token is not treated as a Web Cookie replacement
The system SHALL continue to expose validated Web Cookie values to existing Bilibili Web/live APIs and SHALL NOT require those APIs to use TV `access_token` directly.

#### Scenario: Runtime needs Bilibili authentication
- **WHEN** the danmaku worker or a web-owned Bilibili API call needs credentials
- **THEN** it receives a Web Cookie derived from validated `cookie_info.cookies`, not only a TV access token
```


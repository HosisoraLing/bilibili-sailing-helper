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
6. Run mocked verification, syntax checks, Compose config, and one manual real-chain validation when credentials are available.

Rollback is code-level plus preserving the previous Cookie values. New metadata should be additive so older deployments can ignore it.

## Open Questions

- Whether Python should implement the TV QR/refresh protocol directly or call a small isolated helper. Default decision: Python direct implementation unless the protocol proves too costly to reproduce safely.
- Exact storage location for encrypted refresh tokens. Default decision: extend existing SQLite metadata and keep `settings.json` as the source of the runtime Web Cookie map until a later config-storage cleanup.
- Whether the automatic threshold should be fixed at 10 days or configurable. Default decision: configurable with a 10-day default.

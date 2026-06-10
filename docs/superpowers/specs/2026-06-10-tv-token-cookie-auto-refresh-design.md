---
comet_change: tv-token-cookie-auto-refresh
role: technical-design
canonical_spec: openspec
---

# TV Token Cookie Auto Refresh Technical Design

## Context

`tv-token-cookie-auto-refresh` builds on the runtime split already designed for this project. The web role owns credential persistence and direct business writes. The scheduler role owns periodic triggers. The danmaku worker consumes validated runtime Cookie state and reloads when `cookie_version` changes.

The old `main` behavior only refreshed `buvid3`; it did not renew `SESSDATA`. The reference repository `renmu123/biliLive-tools` demonstrates the stronger model: TV QR login returns `access_token`, `refresh_token`, and `cookie_info.cookies`; a later refresh call produces new tokens and Web Cookie values before `SESSDATA` expires.

## Architecture

The implementation should introduce a focused TV authorization service rather than overloading the existing Web Passport QR service.

```text
admin
  -> web admin TV QR endpoint
  -> TV auth service
  -> Bilibili TV QR login / refresh
  -> web-owned credential store
  -> runtime Cookie payload
  -> danmaku-worker reload on cookie_version change
```

TV `access_token` and `refresh_token` are refresh credentials. Existing Bilibili live/Web requests should continue to use a Cookie header built from validated Web Cookie values extracted from `cookie_info.cookies`.

## Components

### TV Auth Service

Responsibilities:

- Start TV QR login and return a QR URL/task id.
- Poll TV QR login state and normalize statuses.
- Parse successful auth payloads.
- Extract Cookie map and `SESSDATA` expiry from `cookie_info.cookies`.
- Refresh authorization with stored `access_token` and `refresh_token`.
- Mask sensitive values before returning status to admin UI.

The service should isolate Bilibili protocol details so future payload drift does not leak across routes, scheduler, or worker code.

### Credential Storage

Use additive storage on top of existing runtime Cookie metadata. Store:

- `mid`
- `access_token`
- `refresh_token`
- raw auth payload JSON
- extracted Cookie map or complete Cookie header
- `sessdata_expires_at`
- `last_refresh_at`
- `last_validated_at`
- `status`
- `last_error`
- `cookie_version`

Do not put real token values in examples, logs, tests, or docs. Admin responses should show masked state only.

### Cookie Maintenance

`cookie-maintenance` should:

1. Load current TV authorization metadata and runtime Cookie state.
2. Validate current Web Cookie if present.
3. Compare `sessdata_expires_at` with the configured refresh threshold, default 10 days.
4. If not expiring, record a successful no-op maintenance result.
5. If expiring, call TV refresh with stored tokens.
6. Validate extracted Web Cookie with `/x/web-interface/nav`.
7. On success, replace runtime Cookie values and increment `cookie_version`.
8. On failure, preserve the last usable Cookie and record an actionable admin error.

Refresh should be bounded by timeouts. A slow upstream call should not make scheduler health ambiguous.

### Scheduler Execution Boundary

The scheduler role should continue posting internal job requests. The web role must execute or consume those requests. The first implementation can execute the job immediately inside `/internal/scheduler/job` after creating the job record, as long as timeouts are bounded and failures are recorded. If execution becomes slow, the same contract can be backed by a web-owned pending-job runner later.

The scheduler role must not import app business services, access SQLite directly, or write `settings.json`.

### Admin UX

Admin status should distinguish:

- No TV auth configured
- TV auth valid
- Cookie valid and not expiring
- Cookie expiring soon
- Refresh in progress
- Refresh failed but old Cookie preserved
- Refresh token invalid, rescan required
- Worker has not loaded latest Cookie version yet

Every error state should include a next action, not only a technical message.

## Testing

Use mocked protocol tests first:

- TV QR pending/scanned/expired/succeeded/unknown.
- Successful auth payload extraction.
- Missing `SESSDATA`, missing `refresh_token`, malformed `cookie_info`.
- Refresh success updates tokens and Cookie map.
- Refresh failure preserves old Cookie.
- `SESSDATA` expiry threshold logic.
- Scheduler-triggered `cookie-maintenance` reaches success or failure.
- `cookie_version` increments only when runtime Cookie is replaced.
- Admin status masks sensitive fields.

Use integration-style tests without live Bilibili connectivity for internal API boundaries:

- Scheduler does not directly write DB/config.
- Web-owned job handler executes `cookie-maintenance`.
- Danmaku worker reload decision sees newer Cookie version.

When real credentials are available, run a manual real-chain check:

- Extract Cookie from TV login/refresh response.
- Validate with `/x/web-interface/nav`.
- Call `getDanmuInfo`.
- Call the current guard list endpoint.

## Risks

- TV protocol drift: keep parsing isolated, store raw payload, and report unknown states clearly.
- Refresh token invalidation: preserve old Cookie and require rescan.
- Missing expiry metadata: mark expiry unknown and avoid claiming automatic refresh coverage.
- Scheduler blocking: keep first implementation bounded; move to a web-owned runner if needed.
- Sensitive data exposure: mask admin output and avoid logging raw tokens/Cookies.

## Implementation Notes

Prefer Python direct protocol implementation first. Only introduce a Node helper if reproducing the TV login/refresh protocol in Python becomes materially riskier than isolating the existing `@renmu/bili-api` behavior.

Keep the feature as a new capability layered on top of the hard-cut runtime branch. Do not merge it into route modularization work.

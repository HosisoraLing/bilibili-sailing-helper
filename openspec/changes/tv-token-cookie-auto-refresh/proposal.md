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

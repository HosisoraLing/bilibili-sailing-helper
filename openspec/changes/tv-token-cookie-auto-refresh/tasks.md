## 1. Protocol Research And State Model

- [x] 1.1 Map `renmu123/biliLive-tools` TV QR login, refresh, Cookie extraction, and expiry-check code paths into Python implementation notes.
- [x] 1.2 Add additive storage for TV authorization metadata, raw auth payload, Cookie expiry, validation status, and masked admin display fields.
- [x] 1.3 Add tests for parsing TV auth payloads, extracting Web Cookies, reading `SESSDATA` expiry, and masking sensitive fields.

## 2. TV QR Login And Refresh Service

- [x] 2.1 Implement TV QR login begin/poll service without Playwright.
- [x] 2.2 Implement TV authorization refresh with stored `access_token` and `refresh_token`.
- [x] 2.3 Validate extracted Web Cookies with `/x/web-interface/nav` before replacing runtime Cookie settings.
- [x] 2.4 Preserve the last usable Cookie when login or refresh returns invalid Cookie data.
- [x] 2.5 Add mocked tests for pending, scanned, expired, successful login, successful refresh, invalid Cookie, invalid refresh token, and unknown upstream response.

## 3. Runtime Cookie Maintenance

- [x] 3.1 Implement `cookie-maintenance` semantics: validate current Cookie, refresh only when expiry is within threshold, and record status.
- [x] 3.2 Make successful refresh update Web Cookie values and increment `cookie_version`.
- [x] 3.3 Make failed refresh produce clear admin next actions without overwriting usable Cookie.
- [x] 3.4 Add tests for not-yet-expiring Cookie, expiring Cookie refresh, refresh failure, missing expiry, and version advancement.

## 4. Scheduler Execution Boundary

- [x] 4.1 Fix internal scheduler job handling so `cookie-maintenance` is executed by web or a web-owned job runner after scheduler trigger.
- [x] 4.2 Ensure `scheduler` still does not import business writers or write the database/config directly.
- [x] 4.3 Add tests proving scheduler-triggered `cookie-maintenance` reaches terminal success/failure instead of staying `requested`.

## 5. Admin UX And Documentation

- [x] 5.1 Update admin Cookie status to show TV authorization state, Cookie expiry, last validation, last refresh, refresh failure, and next action.
- [x] 5.2 Update admin login flow copy so admins understand TV QR login enables automatic refresh but cannot recover invalid refresh tokens without rescanning.
- [x] 5.3 Update `settings.json.example`, Docker/manual docs, and sensitive-data notes for TV tokens and refresh tokens.

## 6. Verification

- [x] 6.1 Run focused unit tests for TV auth parsing, refresh, Cookie maintenance, scheduler execution, and runtime Cookie versioning.
- [x] 6.2 Run `python -m compileall .`.
- [x] 6.3 Run Docker Compose config check.
- [x] 6.4 Run source search to verify no real tokens/Cookies are committed and sensitive values are masked in admin outputs.
Manual residual: when credentials are available, run a real-chain validation against `/x/web-interface/nav`, `getDanmuInfo`, and the current guard list endpoint.

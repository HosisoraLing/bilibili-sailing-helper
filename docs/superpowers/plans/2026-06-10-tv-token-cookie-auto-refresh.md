---
change: tv-token-cookie-auto-refresh
design-doc: docs/superpowers/specs/2026-06-10-tv-token-cookie-auto-refresh-design.md
base-ref: e360536529050e7551362a20272f525f595274d1
---

# TV Token Cookie Auto Refresh Implementation Plan

## Goal

Add refreshable Bilibili TV authorization so an admin can scan once, then have the system maintain Web Cookie credentials automatically while preserving the split runtime boundary.

## Constraints

- Do not commit real tokens, Cookies, QR payloads, or account identifiers.
- Web remains the only direct writer for credential state, runtime Cookie state, and business DB state.
- Scheduler triggers jobs through internal API; it must not import business writer services.
- Runtime Bilibili API calls continue to consume validated Web Cookies, not raw TV access tokens.
- Failed refresh must preserve the last usable Cookie.

## Phase 1: Research And Contracts

- [ ] 1.1 Re-read `renmu123/biliLive-tools` TV QR login and refresh implementation and capture endpoint/payload assumptions in code comments or tests.
- [ ] 1.2 Add failing tests for TV auth payload parsing: token fields, `cookie_info.cookies`, `SESSDATA` expiry, missing fields, and sensitive masking.
- [ ] 1.3 Add or extend credential metadata models with additive fields for TV auth state, expiry, raw payload, and refresh status.
- [ ] 1.4 Update migrations/init paths for the new credential fields.

## Phase 2: TV Auth Service

- [ ] 2.1 Create a focused TV auth service module with begin, poll, refresh, Cookie extraction, and status normalization functions.
- [ ] 2.2 Implement TV QR login begin/poll against injectable HTTP client interfaces.
- [ ] 2.3 Implement TV refresh against injectable HTTP client interfaces.
- [ ] 2.4 Implement safe persistence: validate extracted Web Cookie before replacing runtime Cookie settings.
- [ ] 2.5 Cover pending, scanned, expired, success, invalid Cookie, invalid refresh token, and unknown upstream response with tests.

## Phase 3: Cookie Maintenance

- [ ] 3.1 Implement Cookie maintenance service: validate current Cookie, compare expiry threshold, and no-op when not expiring.
- [ ] 3.2 On expiring Cookie, refresh TV auth and atomically update Web Cookie state plus `cookie_version`.
- [ ] 3.3 On refresh failure, preserve old Cookie and record admin-actionable status.
- [ ] 3.4 Add tests for not-expiring, expiring refresh, missing expiry, refresh failure, and version advancement.

## Phase 4: Scheduler Execution Boundary

- [ ] 4.1 Update internal scheduler job handling so `cookie-maintenance` reaches a terminal success/failure state.
- [ ] 4.2 Keep scheduler runtime free of business DB/config writes.
- [ ] 4.3 Add tests proving scheduler trigger executes through web-owned handler and does not remain `requested`.

## Phase 5: Admin UX And Docs

- [ ] 5.1 Update admin Cookie status payload to include TV auth state, expiry, last validation, last refresh, failure reason, and next action.
- [ ] 5.2 Update admin QR/login copy for TV authorization and rescan-required states.
- [ ] 5.3 Update docs and examples to describe TV token sensitivity and auto-refresh limits without real values.

## Phase 6: Verification

- [ ] 6.1 Run focused unit tests for TV auth parsing, refresh, maintenance, scheduler execution, and version reload.
- [ ] 6.2 Run `python -m compileall .`.
- [ ] 6.3 Run Docker Compose config validation.
- [ ] 6.4 Search source/docs/tests for accidental sensitive values or unmasked admin output.
- [ ] 6.5 With real credentials available, manually validate extracted TV Cookies against `/x/web-interface/nav`, `getDanmuInfo`, and guard list endpoint.

## Notes

- Prefer Python direct protocol implementation. Introduce a Node helper only if protocol reproduction becomes the larger risk.
- If TV protocol investigation changes endpoint shape or auth requirements materially, update OpenSpec delta specs before implementing beyond the spike.

## Why

After the hard-cut runtime merge, `routes.py` still contains all public, auth, address, admin, Cookie, and internal API route handlers in one 2274-line module. The file already uses `main_bp`, `admin_bp`, and `internal_bp`, but the ownership boundary is still textual rather than structural.

This makes future changes risky: a small admin edit requires loading the full user/auth/internal surface, and route-level regressions are easy to miss because endpoint compatibility is implicit.

## What Changes

- Split `routes.py` into focused route modules or packages while preserving existing URLs, endpoint names, methods, decorators, redirects, template expectations, and response formats.
- Keep business logic in `services/`; route modules should orchestrate request parsing, service calls, redirects, rendering, and JSON responses.
- Preserve the current three top-level Blueprint domains: public/main, admin, and internal.
- Add route inventory and URL generation regression checks before moving handlers.
- Add focused regression checks for critical public/auth/admin/internal endpoints.
- Defer behavior changes, UI changes, and service refactors to separate changes unless a move exposes a proven dead duplicate.

## Non-Goals

- Do not redesign authentication, QR login, danmaku worker, scheduler, or internal API behavior.
- Do not change database schema.
- Do not change public URLs or admin URLs.
- Do not introduce a new web framework.
- Do not rewrite templates except for endpoint-name compatibility fixes if a test proves they are required.

## Capabilities

### New Capabilities

- `route-module-boundaries`: Defines route module ownership, URL compatibility, endpoint compatibility, and regression coverage expectations for splitting `routes.py`.

### Modified Capabilities

- None.

## Impact

- Affected code: `routes.py`, possible new `routes/` package or equivalent route modules, route registration in `app.py`, route regression tests.
- Affected user flows: index, auth/login/register/reset, address submit, admin panel, guard/companion/gift/CSV operations, Cookie QR/admin operations, internal runtime endpoints.
- Dependencies: no new dependency expected.
- Data: no schema changes.

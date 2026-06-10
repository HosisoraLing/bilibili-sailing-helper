## Context

Current `routes.py` is a 2274-line module with three Blueprints:

- `main_bp`: public pages, auth polling, login, auth login, logout, reset password, register, submit.
- `admin_bp`: admin panel, address CRUD, CSV import/export, guard management, guard gifts, companion ranking, Cookie QR/login/runtime status controls.
- `internal_bp`: runtime heartbeat, runtime Cookie, danmaku auth event, scheduler job/result.

The hard-cut runtime change introduced more explicit runtime and service boundaries, but did not split route ownership. The next safe step is structural separation with route compatibility tests.

## Route Boundary Proposal

Use one route package with small modules and a single registration entrypoint. The exact filenames can be adjusted during build, but ownership should stay close to this shape:

- `routes/__init__.py`: exports `register_routes(app)` and registers all Blueprints.
- `routes/public.py`: index, not-guard, opensource, address submit.
- `routes/auth.py`: auth status, login, auth-login, auth page, logout, reset-password, register.
- `routes/admin/dashboard.py`: admin panel and shared admin helpers.
- `routes/admin/addresses.py`: admin address CRUD and address CSV export/import where address-specific.
- `routes/admin/guards.py`: guard and companion ranking management.
- `routes/admin/gifts.py`: guard gift management and gift calculation.
- `routes/admin/cookies.py`: Cookie status, QR login, BUVID refresh, listener/worker restart compatibility endpoint.
- `routes/internal.py`: internal runtime, Cookie, danmaku, and scheduler endpoints.

If a `routes/` package conflicts with the current `routes.py` module, implementation should use an intermediate package name such as `route_handlers/` first, then replace `routes.py` only when tests prove compatibility.

## Compatibility Rules

- Existing URL rules and HTTP methods must remain unchanged unless explicitly approved in a later change.
- Existing endpoint names used by templates and redirects must remain available.
- Existing decorators and admin checks must stay attached to the same protected handlers.
- JSON response keys for auth polling, Cookie status, and internal APIs must remain compatible.
- Public user flows must keep action-oriented error feedback.

## Testing Strategy

Before moving handlers, capture an endpoint inventory from the current app:

- URL rule
- endpoint name
- methods
- blueprint

Then add tests that assert the inventory remains stable after the split. Add focused smoke tests for:

- public index and auth page route registration
- auth status response shape for missing/expired/pending cases where fixtures allow
- admin route protection redirect or forbidden behavior
- Cookie QR route registration and JSON status shape
- internal API secret rejection for protected internal endpoints

## Migration Strategy

1. Add route inventory tests against the current monolithic module.
2. Extract one module family at a time.
3. Keep `register_routes(app)` as the public registration API.
4. Run route inventory tests after each extraction.
5. Remove the old monolithic module only after every handler is owned by a focused module.

## Risks

- Endpoint name drift can break templates without obvious compile errors.
- Import cycles can appear if route modules import app startup objects instead of services.
- Admin decorators may be dropped during moves.
- Internal API endpoints are machine-facing; response drift can break worker/scheduler runtime.

Mitigation: route inventory tests first, no service refactors in the same change, and explicit endpoint compatibility checks.

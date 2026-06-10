# Comet Design Handoff

- Change: modularize-routes-and-admin-v2
- Phase: design
- Mode: compact
- Context hash: bde788b4d830fdb820e773a7cea4318c62e56fa79268c53a6c29d478f81660dc

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/modularize-routes-and-admin-v2/proposal.md

- Source: openspec/changes/modularize-routes-and-admin-v2/proposal.md
- Lines: 1-39
- SHA256: d91a5d93257d7457f052fe6f37c446fe73e9836f767a659927ab5d532b9b763a

```md
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
```

## openspec/changes/modularize-routes-and-admin-v2/design.md

- Source: openspec/changes/modularize-routes-and-admin-v2/design.md
- Lines: 1-67
- SHA256: f3e3ab0802d30ee61988c65ebaaf97dc582e017a161df554b9eaacdae2c97b6b

```md
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
```

## openspec/changes/modularize-routes-and-admin-v2/tasks.md

- Source: openspec/changes/modularize-routes-and-admin-v2/tasks.md
- Lines: 1-15
- SHA256: 2606c22bc7240a9bb4c1d1958023626a6b469b088906a605ee8a5c0d7edcbc9d

```md
## Tasks

- [x] Inventory current route rules, endpoint names, methods, Blueprints, redirects, template `url_for` usage, and decorators.
- [x] Add route inventory regression tests before moving code.
- [x] Decide final module/package name that avoids import conflict with the existing `routes.py` module.
- [x] Extract public non-auth routes while preserving URLs and endpoint names.
- [x] Extract auth/login/register/reset routes while preserving auth polling response shape.
- [x] Extract admin dashboard/address/CSV routes while preserving admin protection.
- [x] Extract guard, companion, ranking, gift, and gift calculation admin routes.
- [x] Extract Cookie/QR/runtime-control admin routes.
- [x] Extract internal runtime, Cookie, danmaku, and scheduler routes.
- [x] Keep `register_routes(app)` as the stable app-facing registration API.
- [x] Remove or shrink the legacy monolithic `routes.py` only after all compatibility tests pass.
- [x] Run `python3 -m compileall app.py routes.py db services runtime tests get_cookies.py`.
- [x] Run route regression tests and relevant auth/admin/internal endpoint tests.
```

## openspec/changes/modularize-routes-and-admin-v2/specs/route-module-boundaries/spec.md

- Source: openspec/changes/modularize-routes-and-admin-v2/specs/route-module-boundaries/spec.md
- Lines: 1-57
- SHA256: 40a4bd1107216fd825ce31d957bbcccb512dfac5e17efa46e6051c1aaeebc71b

```md
# route-module-boundaries Specification

## Purpose

Define how route handlers are split into focused modules without changing user-visible URLs, endpoint names, admin protections, or internal API contracts.

## ADDED Requirements

### Requirement: Route registration remains compatible

The system SHALL preserve existing URL rules, HTTP methods, endpoint names, and Blueprint prefixes while route handlers are moved out of the monolithic route module.

#### Scenario: Templates generate existing URLs

- **WHEN** templates call `url_for()` for existing public, auth, or admin endpoints
- **THEN** URL generation succeeds without changing template endpoint names unless an explicit compatibility shim is provided

#### Scenario: Route inventory is compared after modularization

- **WHEN** the app registers routes after modularization
- **THEN** the route inventory matches the pre-modularization inventory for URL rules, endpoint names, methods, and Blueprint prefixes

### Requirement: Route modules do not absorb business logic

Route modules SHALL delegate business decisions and data mutations to service modules instead of moving service logic into route handlers.

#### Scenario: Admin guard route is moved

- **WHEN** an admin guard route is moved into a focused module
- **THEN** guard fetching, mutation, cache invalidation, and CSV generation remain in existing services or dedicated helpers rather than being duplicated in the route module

### Requirement: Admin protection is preserved

Admin route modules SHALL preserve the same admin checks and failure behavior as the monolithic route module.

#### Scenario: Non-admin accesses an admin route

- **WHEN** a non-admin request reaches an admin route after modularization
- **THEN** the response behavior remains compatible with the pre-modularization behavior

### Requirement: Internal API contracts remain stable

Internal route modules SHALL preserve request authentication, response status codes, and JSON response shapes for runtime worker and scheduler endpoints.

#### Scenario: Worker omits internal secret

- **WHEN** `danmaku-worker` or `scheduler` calls an internal endpoint without a valid secret
- **THEN** the endpoint still returns the same unauthorized response and performs no state mutation

### Requirement: Public auth flow remains user-actionable

Public auth routes SHALL preserve the current action-oriented states for waiting, success, expired, listener unavailable, delivery delayed, and retrying.

#### Scenario: Auth status is pending

- **WHEN** a user polls auth status before a matching danmaku event is processed
- **THEN** the response still tells the user the next action rather than returning only a technical state
```


---
comet_change: modularize-routes-and-admin-v2
role: technical-design
canonical_spec: openspec
---

# Modularize Routes And Admin V2 Design

## Confirmed Approach

Split the monolithic `routes.py` into a focused `route_handlers/` package while keeping `routes.py` as the stable application-facing entrypoint. This avoids a Python import conflict between an existing `routes.py` module and a new `routes/` package.

The public registration contract stays unchanged:

- `app.py` imports `register_routes` from `routes`.
- `register_routes(app)` registers the same three Blueprint domains.
- Endpoint names, URL rules, methods, decorators, redirects, and response shapes remain compatible.

## Module Boundaries

- `route_handlers/common.py`: shared Blueprint instances and route dependencies.
- `route_handlers/public.py`: public pages and address submit.
- `route_handlers/auth.py`: auth status, login, auth-login, auth page, logout, reset password, and register.
- `route_handlers/admin/dashboard.py`: admin dashboard.
- `route_handlers/admin/addresses.py`: admin address CRUD and address CSV import/export.
- `route_handlers/admin/guards.py`: guard management.
- `route_handlers/admin/gifts.py`: guard gift management and gift calculation.
- `route_handlers/admin/companion.py`: companion ranking and companion member management.
- `route_handlers/admin/cookies.py`: Cookie status, QR login, BUVID refresh, and listener control.
- `route_handlers/internal.py`: internal runtime, Cookie, danmaku, and scheduler endpoints.

## Compatibility Strategy

`routes.py` remains a small compatibility wrapper. It imports the Blueprint instances from `route_handlers`, registers them in the same order, and keeps `run_pending_scheduler_job(job)` as a wrapper so tests or callers that patch scheduler dependencies through `routes` continue to work.

Route modules are intentionally thin. This change moves handler ownership but does not redesign auth, QR login, scheduler, database schema, templates, or service behavior.

## Testing Strategy

Add a route inventory regression test that captures:

- endpoint name
- URL rule
- HTTP methods
- Blueprint domain

Add focused checks for URL generation, admin route protection, Cookie route protection, and internal secret rejection. Run the existing auth, QR login, internal API, and runtime Cookie tests to catch response-shape drift around the moved handlers.

## Risks And Mitigations

- Endpoint drift can break templates: covered by route inventory and URL generation tests.
- Decorator drift can expose admin routes: covered by admin protection tests.
- Internal API drift can break runtime roles: covered by internal API tests.
- Import cycles can occur if modules import startup objects: mitigated by shared route dependencies in `route_handlers/common.py` and lazy app import only for `fetch_and_save_guards`.

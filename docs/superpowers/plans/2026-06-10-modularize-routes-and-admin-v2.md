---
change: modularize-routes-and-admin-v2
design-doc: docs/superpowers/specs/2026-06-10-modularize-routes-and-admin-v2-design.md
base-ref: d5cf50ae5f0fb9b376f0cc70233702d582aedf3a
---

# Modularize Routes And Admin V2 Implementation Plan

## Goal

Split the 2274-line route module into focused route modules without changing user-visible or machine-facing behavior.

## Tasks

- [x] Capture route inventory and URL generation expectations.
- [x] Add regression tests for route inventory, URL generation, admin protection, Cookie route protection, and internal secret rejection.
- [x] Create `route_handlers/` package with shared Blueprint instances and dependencies.
- [x] Move public and auth handlers into focused modules.
- [x] Move admin dashboard, address, guard, gift, companion, and Cookie handlers into focused admin modules.
- [x] Move internal runtime, Cookie, danmaku, and scheduler handlers into `route_handlers/internal.py`.
- [x] Shrink `routes.py` to the stable registration and scheduler compatibility entrypoint.
- [x] Update Docker packaging so `route_handlers/` is included in the image.
- [x] Run OpenSpec validation, compile checks, and focused route/auth/admin/internal tests.

## Verification

- `openspec validate modularize-routes-and-admin-v2`
- `.venv/bin/python -m compileall app.py routes.py db services runtime tests get_cookies.py route_handlers`
- `.venv/bin/python -m pytest tests/test_route_inventory.py tests/test_internal_api.py tests/test_auth_state.py tests/test_qr_login.py tests/test_browserless_qr_contract.py tests/test_cookie_runtime_contract.py`

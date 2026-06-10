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

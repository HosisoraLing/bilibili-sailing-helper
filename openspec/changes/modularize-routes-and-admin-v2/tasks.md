## Tasks

- [ ] Inventory current route rules, endpoint names, methods, Blueprints, redirects, template `url_for` usage, and decorators.
- [ ] Add route inventory regression tests before moving code.
- [ ] Decide final module/package name that avoids import conflict with the existing `routes.py` module.
- [ ] Extract public non-auth routes while preserving URLs and endpoint names.
- [ ] Extract auth/login/register/reset routes while preserving auth polling response shape.
- [ ] Extract admin dashboard/address/CSV routes while preserving admin protection.
- [ ] Extract guard, companion, ranking, gift, and gift calculation admin routes.
- [ ] Extract Cookie/QR/runtime-control admin routes.
- [ ] Extract internal runtime, Cookie, danmaku, and scheduler routes.
- [ ] Keep `register_routes(app)` as the stable app-facing registration API.
- [ ] Remove or shrink the legacy monolithic `routes.py` only after all compatibility tests pass.
- [ ] Run `python3 -m compileall app.py routes.py db services runtime tests get_cookies.py`.
- [ ] Run route regression tests and relevant auth/admin/internal endpoint tests.

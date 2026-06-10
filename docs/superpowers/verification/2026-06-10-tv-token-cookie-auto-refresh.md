# TV Token Cookie Auto Refresh Verification

Date: 2026-06-10

## Result

Automated verification passed for the TV token Cookie auto-refresh change.

## Commands

```bash
INTERNAL_API_SECRET=test-secret docker compose config >/tmp/bsh-tv-compose.yml
openspec validate tv-token-cookie-auto-refresh
.venv/bin/python -m compileall app.py routes.py db services runtime tests get_cookies.py route_handlers
.venv/bin/python -m pytest tests/test_tv_auth_service.py tests/test_cookie_maintenance.py tests/test_route_inventory.py tests/test_internal_api.py tests/test_qr_login.py tests/test_cookie_runtime_contract.py tests/test_runtime_config.py tests/test_auth_state.py tests/test_browserless_qr_contract.py
# Search source, docs, and tests for accidental real Cookie/token values.
# The exact pattern intentionally lives in shell history, not in this report,
# so this verification file does not self-match future sensitive-value scans.
```

## Evidence

- OpenSpec validation: `Change 'tv-token-cookie-auto-refresh' is valid`.
- Python compile check: passed for `app.py`, `routes.py`, `db`, `services`, `runtime`, `tests`, `get_cookies.py`, and `route_handlers`.
- Focused pytest suite: `90 passed`.
- Live TV QR begin protocol smoke check: Bilibili returned JSON `code: 0` for signed TV form request, and the local Docker route returned a 530x530 PNG QR image.
- Runtime Cookie smoke check: TV authorization Cookies without `buvid3` are accepted for `danmaku-worker` when `SESSDATA` is present.
- Docker Compose config: generated successfully at `/tmp/bsh-tv-compose.yml`.
- Sensitive-value search: only test fake values and expected protocol/documentation references were found; no real credentials were detected.

## Manual Residual

Real Bilibili account validation was not run in this workspace. Before calling the feature production-proven, an admin should scan through the TV authorization flow and validate the extracted Web Cookies against `/x/web-interface/nav`, `getDanmuInfo`, and the current guard list endpoint.

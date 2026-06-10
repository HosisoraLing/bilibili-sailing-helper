EXPECTED_ROUTE_INVENTORY = {
    "admin.admin_add_address": {
        "rule": "/admin/add-address",
        "methods": ["GET", "POST"],
        "blueprint": "admin",
    },
    "admin.admin_calculate_gifts": {
        "rule": "/admin/calculate-gifts",
        "methods": ["POST"],
        "blueprint": "admin",
    },
    "admin.admin_companion_add": {
        "rule": "/admin/companion/add",
        "methods": ["POST"],
        "blueprint": "admin",
    },
    "admin.admin_companion_delete": {
        "rule": "/admin/companion/delete",
        "methods": ["POST"],
        "blueprint": "admin",
    },
    "admin.admin_companion_edit": {
        "rule": "/admin/companion/edit",
        "methods": ["POST"],
        "blueprint": "admin",
    },
    "admin.admin_companion_get": {
        "rule": "/admin/companion/<uid>",
        "methods": ["GET"],
        "blueprint": "admin",
    },
    "admin.admin_companion_ranking": {
        "rule": "/admin/companion-ranking",
        "methods": ["GET"],
        "blueprint": "admin",
    },
    "admin.admin_cookie_qrcode": {
        "rule": "/admin/cookie/qrcode/<task_id>",
        "methods": ["GET"],
        "blueprint": "admin",
    },
    "admin.admin_cookie_status": {
        "rule": "/admin/cookie/status",
        "methods": ["GET"],
        "blueprint": "admin",
    },
    "admin.admin_delete_address": {
        "rule": "/admin/delete-address/<int:address_id>",
        "methods": ["POST"],
        "blueprint": "admin",
    },
    "admin.admin_edit_address": {
        "rule": "/admin/edit-address/<int:address_id>",
        "methods": ["GET", "POST"],
        "blueprint": "admin",
    },
    "admin.admin_export_companion_ranking": {
        "rule": "/admin/export/companion-ranking",
        "methods": ["GET"],
        "blueprint": "admin",
    },
    "admin.admin_export_csv": {
        "rule": "/admin/export/csv",
        "methods": ["GET"],
        "blueprint": "admin",
    },
    "admin.admin_export_guard_gifts": {
        "rule": "/admin/export/guard-gifts",
        "methods": ["GET"],
        "blueprint": "admin",
    },
    "admin.admin_export_guards": {
        "rule": "/admin/export/guards",
        "methods": ["GET"],
        "blueprint": "admin",
    },
    "admin.admin_guard_add": {
        "rule": "/admin/guards/add",
        "methods": ["POST"],
        "blueprint": "admin",
    },
    "admin.admin_guard_delete": {
        "rule": "/admin/guards/delete",
        "methods": ["POST"],
        "blueprint": "admin",
    },
    "admin.admin_guard_edit": {
        "rule": "/admin/guards/edit",
        "methods": ["POST"],
        "blueprint": "admin",
    },
    "admin.admin_guard_get": {
        "rule": "/admin/guards/<uid>",
        "methods": ["GET"],
        "blueprint": "admin",
    },
    "admin.admin_guard_gift_add": {
        "rule": "/admin/guard-gifts/add",
        "methods": ["POST"],
        "blueprint": "admin",
    },
    "admin.admin_guard_gift_delete": {
        "rule": "/admin/guard-gifts/delete",
        "methods": ["POST"],
        "blueprint": "admin",
    },
    "admin.admin_guard_gift_edit": {
        "rule": "/admin/guard-gifts/edit",
        "methods": ["POST"],
        "blueprint": "admin",
    },
    "admin.admin_guard_gift_get": {
        "rule": "/admin/guard-gifts/<uid>/<month>",
        "methods": ["GET"],
        "blueprint": "admin",
    },
    "admin.admin_guard_gift_receive": {
        "rule": "/admin/guard-gifts/receive",
        "methods": ["POST"],
        "blueprint": "admin",
    },
    "admin.admin_guard_gift_unreceive": {
        "rule": "/admin/guard-gifts/unreceive",
        "methods": ["POST"],
        "blueprint": "admin",
    },
    "admin.admin_guard_gifts": {
        "rule": "/admin/guard-gifts",
        "methods": ["GET"],
        "blueprint": "admin",
    },
    "admin.admin_guards": {
        "rule": "/admin/guards",
        "methods": ["GET"],
        "blueprint": "admin",
    },
    "admin.admin_import_csv": {
        "rule": "/admin/import/csv",
        "methods": ["POST"],
        "blueprint": "admin",
    },
    "admin.admin_panel": {
        "rule": "/admin/panel",
        "methods": ["GET"],
        "blueprint": "admin",
    },
    "admin.admin_poll_qr_login": {
        "rule": "/admin/cookie/qr-login/<task_id>",
        "methods": ["GET"],
        "blueprint": "admin",
    },
    "admin.admin_refresh_buvid3": {
        "rule": "/admin/cookie/refresh-buvid3",
        "methods": ["POST"],
        "blueprint": "admin",
    },
    "admin.admin_restart_listener": {
        "rule": "/admin/cookie/restart-listener",
        "methods": ["POST"],
        "blueprint": "admin",
    },
    "admin.admin_start_qr_login": {
        "rule": "/admin/cookie/start-qr-login",
        "methods": ["POST"],
        "blueprint": "admin",
    },
    "admin.admin_start_tv_qr_login": {
        "rule": "/admin/cookie/start-tv-qr-login",
        "methods": ["POST"],
        "blueprint": "admin",
    },
    "admin.admin_poll_tv_qr_login": {
        "rule": "/admin/cookie/tv-qr-login/<task_id>",
        "methods": ["GET"],
        "blueprint": "admin",
    },
    "internal.internal_danmaku_auth_event": {
        "rule": "/internal/danmaku/auth-event",
        "methods": ["POST"],
        "blueprint": "internal",
    },
    "internal.internal_runtime_cookie": {
        "rule": "/internal/runtime/cookie",
        "methods": ["GET"],
        "blueprint": "internal",
    },
    "internal.internal_runtime_heartbeat": {
        "rule": "/internal/runtime/heartbeat",
        "methods": ["POST"],
        "blueprint": "internal",
    },
    "internal.internal_scheduler_job": {
        "rule": "/internal/scheduler/job",
        "methods": ["POST"],
        "blueprint": "internal",
    },
    "internal.internal_scheduler_result": {
        "rule": "/internal/scheduler/result",
        "methods": ["POST"],
        "blueprint": "internal",
    },
    "main.auth": {"rule": "/auth", "methods": ["GET"], "blueprint": "main"},
    "main.auth_login": {
        "rule": "/auth-login",
        "methods": ["GET"],
        "blueprint": "main",
    },
    "main.auth_status": {
        "rule": "/auth/status",
        "methods": ["GET"],
        "blueprint": "main",
    },
    "main.index": {"rule": "/", "methods": ["GET"], "blueprint": "main"},
    "main.login": {
        "rule": "/login",
        "methods": ["GET", "POST"],
        "blueprint": "main",
    },
    "main.logout": {"rule": "/logout", "methods": ["GET"], "blueprint": "main"},
    "main.not_guard": {
        "rule": "/not-guard",
        "methods": ["GET"],
        "blueprint": "main",
    },
    "main.opensource": {
        "rule": "/opensource",
        "methods": ["GET"],
        "blueprint": "main",
    },
    "main.register": {
        "rule": "/register",
        "methods": ["GET", "POST"],
        "blueprint": "main",
    },
    "main.reset_password": {
        "rule": "/reset-password",
        "methods": ["GET", "POST"],
        "blueprint": "main",
    },
    "main.submit": {"rule": "/submit", "methods": ["POST"], "blueprint": "main"},
}


def _route_inventory(app):
    inventory = {}
    ignored_methods = {"HEAD", "OPTIONS"}
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        inventory[rule.endpoint] = {
            "rule": rule.rule,
            "methods": sorted(set(rule.methods) - ignored_methods),
            "blueprint": rule.endpoint.rsplit(".", 1)[0] if "." in rule.endpoint else None,
        }
    return inventory


def test_route_inventory_is_stable(app):
    assert _route_inventory(app) == EXPECTED_ROUTE_INVENTORY


def test_public_and_auth_url_generation_is_stable(app):
    with app.test_request_context():
        from flask import url_for

        assert url_for("main.index") == "/"
        assert url_for("main.auth", uid="1001") == "/auth?uid=1001"
        assert url_for("main.login", uid="1001") == "/login?uid=1001"
        assert url_for("main.register", uid="1001") == "/register?uid=1001"
        assert url_for("main.reset_password", uid="1001") == "/reset-password?uid=1001"


def test_admin_url_generation_is_stable(app):
    with app.test_request_context():
        from flask import url_for

        assert url_for("admin.admin_panel") == "/admin/panel"
        assert url_for("admin.admin_edit_address", address_id=12) == "/admin/edit-address/12"
        assert url_for("admin.admin_guard_get", uid="1001") == "/admin/guards/1001"
        assert url_for("admin.admin_cookie_status") == "/admin/cookie/status"
        assert (
            url_for("admin.admin_poll_qr_login", task_id="task-1")
            == "/admin/cookie/qr-login/task-1"
        )
        assert (
            url_for("admin.admin_poll_tv_qr_login", task_id="task-1")
            == "/admin/cookie/tv-qr-login/task-1"
        )


def test_admin_routes_remain_protected(client):
    response = client.get("/admin/panel")
    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_cookie_status_route_remains_protected(client):
    response = client.get("/admin/cookie/status")
    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_internal_routes_reject_missing_secret(client):
    response = client.post("/internal/runtime/heartbeat", json={"role": "web"})
    assert response.status_code == 401
    assert response.get_json() == {"error": "invalid internal secret"}

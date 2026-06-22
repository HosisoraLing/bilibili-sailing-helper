"""Stable route registration entrypoint."""
from route_handlers import admin_bp, internal_bp, main_bp
from route_handlers import internal as _internal_routes
from route_handlers.common import (
    CookieMaintenanceService,
    CookieService,
    GuardGiftService,
    cleanup_expired_sessions,
)
from route_handlers.common import fetch_and_save_guards


def register_routes(app):
    """Register all route Blueprints."""
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(internal_bp)


def run_pending_scheduler_job(job):
    """Compatibility wrapper for callers that patch scheduler dependencies here."""
    _internal_routes.fetch_and_save_guards = fetch_and_save_guards
    _internal_routes.GuardGiftService = GuardGiftService
    _internal_routes.CookieService = CookieService
    _internal_routes.CookieMaintenanceService = CookieMaintenanceService
    _internal_routes.cleanup_expired_sessions = cleanup_expired_sessions
    return _internal_routes.run_pending_scheduler_job(job)

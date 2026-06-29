from app import (
    Config,
    create_app,
    db,
    ensure_region_json,
    fetch_and_save_guards,
    register_admins,
    run_migrations,
    run_web_server,
    start_runtime_services,
)


def initialize_empty_database_only():
    """Create schema only for a brand-new empty database."""
    from sqlalchemy import inspect

    inspector = inspect(db.engine)
    if not inspector.get_table_names():
        db.create_all()


def main():
    ensure_region_json()
    app_instance, socketio = create_app()

    with app_instance.app_context():
        initialize_empty_database_only()
        run_migrations()
        fetch_and_save_guards()
        register_admins()

    start_runtime_services(app_instance, role="web")

    from route_handlers.admin.logs import start_tail_thread
    start_tail_thread(app_instance, socketio)

    run_web_server(app_instance, socketio, Config)


if __name__ == "__main__":
    main()

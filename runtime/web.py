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


def main():
    ensure_region_json()
    app_instance, socketio = create_app()

    with app_instance.app_context():
        db.create_all()
        run_migrations()
        fetch_and_save_guards()
        register_admins()

    start_runtime_services(app_instance, role="web")
    run_web_server(app_instance, socketio, Config)


if __name__ == "__main__":
    main()

from db.models import Address, Guard, User, db, get_beijing_now


def test_form_prefill_values_are_json_encoded(client, app):
    with app.app_context():
        user = User(uid="1001", nickname="tester")
        user.set_password("StrongPass!123")
        db.session.add(user)
        db.session.add(
            Guard(
                uid="1001",
                nickname="tester",
                last_guard_date=get_beijing_now().date(),
                in_guard=True,
            )
        )
        db.session.add(
            Address(
                uid="1001",
                nickname="tester",
                province="x'; alert(1);//",
                city='city "quoted"',
                area="district </script>",
                address="street",
                receiver="receiver",
                phone="13800138000",
            )
        )
        db.session.commit()
        user_id = user.id

    with client.session_transaction() as flask_session:
        flask_session["_user_id"] = str(user_id)
        flask_session["_fresh"] = True

    response = client.get("/?uid=1001")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'const prefillProvince = "x\\u0027; alert(1);//";' in html
    assert 'const prefillCity = "city \\"quoted\\"";' in html
    assert 'const prefillDistrict = "district \\u003c/script\\u003e";' in html
    assert "const prefillProvince = '" not in html


def test_join_auth_rejects_invalid_uid_before_auth_mode(monkeypatch):
    from app import create_app
    from services import danmaku_listener

    app_instance, socketio = create_app()
    app_instance.config.update(TESTING=True)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("invalid UID must be rejected before auth mode is set")

    monkeypatch.setattr(danmaku_listener, "set_auth_mode", fail_if_called)

    socket_client = socketio.test_client(app_instance)
    socket_client.emit("join_auth", {"uid": "../1001"})

    assert socket_client.get_received() == [
        {
            "name": "error",
            "args": [{"status": "error", "message": "缺少 UID 参数"}],
            "namespace": "/",
        }
    ]


def test_generate_auth_code_uses_secrets_choice(monkeypatch, app):
    import random

    from services.auth_service import generate_auth_code

    def fail_random_choice(chars):
        raise AssertionError("generate_auth_code must not use random.choice")

    monkeypatch.setattr(random, "choice", fail_random_choice)

    with app.app_context():
        code = generate_auth_code("1001")

    assert len(code) == 8
    assert code.isalnum()

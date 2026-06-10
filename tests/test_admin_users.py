from datetime import date, timedelta

from db.models import (
    Address,
    AuthSession,
    Guard,
    GuardGiftRecord,
    User,
    db,
    get_beijing_now,
)


def login_admin(client, app, uid="admin-100", nickname="admin"):
    with app.app_context():
        admin = User(uid=uid, nickname=nickname)
        admin.add_role("admin")
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id

    with client.session_transaction() as flask_session:
        flask_session["_user_id"] = str(admin_id)

    return admin_id


def admin_tokens(client):
    response = client.get("/admin/panel")
    html = response.get_data(as_text=True)
    import re

    csrf = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    secure = re.search(r'name="secure_token" value="([^"]+)"', html).group(1)
    return csrf, secure


def test_user_roles_handles_missing_roles(app):
    with app.app_context():
        user = User(uid="missing-roles", nickname="missing", roles=None)
        db.session.add(user)
        db.session.commit()

        assert user.get_roles() == []


def test_admin_users_page_renders_user_list(client, app):
    login_admin(client, app)
    with app.app_context():
        db.session.add(User(uid="2001", nickname="tester"))
        db.session.commit()

    response = client.get("/admin/users")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "用户管理" in html
    assert "tester" in html


def test_admin_users_page_escapes_user_data_in_action_buttons(client, app):
    login_admin(client, app)
    with app.app_context():
        db.session.add(User(uid="2001", nickname='quote " and apostrophe \' user'))
        db.session.commit()

    response = client.get("/admin/users")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "onclick=\"openEditModal('" not in html
    assert 'data-uid="2001"' in html
    assert "quote &#34; and apostrophe &#39; user" in html


def test_admin_panel_links_to_user_management(client, app):
    login_admin(client, app)

    response = client.get("/admin/panel")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'href="/admin/users"' in html
    assert "用户管理" in html


def test_admin_user_add_edit_and_admin_role(client, app):
    login_admin(client, app)
    csrf, _secure = admin_tokens(client)

    add_response = client.post(
        "/admin/users/add",
        data={"csrf_token": csrf, "uid": "2002", "nickname": "new-user"},
    )
    assert add_response.status_code == 200
    assert add_response.get_json()["success"] is True

    edit_response = client.post(
        "/admin/users/edit",
        data={"csrf_token": csrf, "uid": "2002", "nickname": "renamed"},
    )
    assert edit_response.status_code == 200
    assert edit_response.get_json()["success"] is True

    set_response = client.post(
        "/admin/users/set-admin",
        data={"csrf_token": csrf, "uid": "2002"},
    )
    assert set_response.status_code == 200
    assert set_response.get_json()["success"] is True

    unset_response = client.post(
        "/admin/users/unset-admin",
        data={"csrf_token": csrf, "uid": "2002"},
    )
    assert unset_response.status_code == 200
    assert unset_response.get_json()["success"] is True

    with app.app_context():
        user = User.query.filter_by(uid="2002").one()
        assert user.nickname == "renamed"
        assert user.is_admin() is False


def test_admin_user_delete_removes_related_records(client, app):
    login_admin(client, app)
    csrf, secure = admin_tokens(client)
    with app.app_context():
        user = User(uid="2003", nickname="delete-me")
        db.session.add(user)
        db.session.add(Address(uid="2003", nickname="delete-me", receiver="r"))
        db.session.add(
            Guard(
                uid="2003",
                nickname="delete-me",
                last_guard_date=date.today(),
                in_guard=True,
            )
        )
        db.session.add(
            GuardGiftRecord(
                uid="2003",
                nickname="delete-me",
                month="2026-06",
                guard_level="guard",
                accompany_days=31,
            )
        )
        db.session.add(
            AuthSession(
                uid="2003",
                code="1234",
                status="pending",
                expires_at=get_beijing_now() + timedelta(minutes=5),
            )
        )
        db.session.commit()

    response = client.post(
        "/admin/users/delete",
        data={"csrf_token": csrf, "secure_token": secure, "uid": "2003"},
    )

    assert response.status_code == 200
    assert response.get_json()["success"] is True
    with app.app_context():
        assert User.query.filter_by(uid="2003").first() is None
        assert Address.query.filter_by(uid="2003").first() is None
        assert Guard.query.filter_by(uid="2003").first() is None
        assert GuardGiftRecord.query.filter_by(uid="2003").first() is None
        assert AuthSession.query.filter_by(uid="2003").first() is None


def test_anchor_user_cannot_be_deleted_or_unset_admin(client, app):
    login_admin(client, app)
    csrf, secure = admin_tokens(client)
    with app.app_context():
        anchor = User(uid="2", nickname="anchor")
        anchor.add_role("admin")
        db.session.add(anchor)
        db.session.commit()

    delete_response = client.post(
        "/admin/users/delete",
        data={"csrf_token": csrf, "secure_token": secure, "uid": "2"},
    )
    unset_response = client.post(
        "/admin/users/unset-admin",
        data={"csrf_token": csrf, "uid": "2"},
    )

    assert delete_response.status_code == 403
    assert "主播" in delete_response.get_json()["error"]
    assert unset_response.status_code == 403
    assert "主播" in unset_response.get_json()["error"]

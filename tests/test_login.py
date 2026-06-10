from db.models import Guard, User, db, get_beijing_now


def test_existing_password_login_does_not_revalidate_password_strength(client, app):
    with app.app_context():
        user = User(uid="1001", nickname="legacy-user")
        user.set_password("LegacyAdmin!23456")
        db.session.add(user)
        db.session.add(
            Guard(
                uid="1001",
                nickname="legacy-user",
                last_guard_date=get_beijing_now().date(),
                in_guard=True,
            )
        )
        db.session.commit()

    page = client.get("/login?uid=1001")
    html = page.get_data(as_text=True)
    import re

    csrf = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    response = client.post(
        "/login?uid=1001",
        data={"csrf_token": csrf, "password": "LegacyAdmin!23456"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/?uid=1001")

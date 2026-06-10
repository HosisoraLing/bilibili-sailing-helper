from db.models import GuardGiftRecord, User, db, get_beijing_now


def test_guard_gift_service_lists_available_months_desc(app):
    from services.guard_gift_service import GuardGiftService

    with app.app_context():
        db.session.add_all([
            GuardGiftRecord(
                uid="1001",
                nickname="tester-1",
                month="2026-04",
                guard_level="guard",
                accompany_days=31,
                received=False,
            ),
            GuardGiftRecord(
                uid="1002",
                nickname="tester-2",
                month="2026-06",
                guard_level="captain",
                accompany_days=62,
                received=True,
                received_at=get_beijing_now(),
            ),
            GuardGiftRecord(
                uid="1003",
                nickname="tester-3",
                month="2026-06",
                guard_level="admiral",
                accompany_days=93,
                received=False,
            ),
        ])
        db.session.commit()

        assert GuardGiftService.get_available_months() == ["2026-06", "2026-04"]


def test_admin_guard_gifts_page_renders_available_months(client, app):
    with app.app_context():
        admin = User(uid="admin-gift", nickname="admin")
        admin.add_role("admin")
        db.session.add(admin)
        db.session.add(
            GuardGiftRecord(
                uid="gift-uid",
                nickname="gift-user",
                month="2026-06",
                guard_level="guard",
                accompany_days=31,
                received=False,
            )
        )
        db.session.commit()
        admin_id = admin.id

    with client.session_transaction() as flask_session:
        flask_session["_user_id"] = str(admin_id)

    response = client.get("/admin/guard-gifts?month=2026-06")

    assert response.status_code == 200
    assert "2026-06" in response.get_data(as_text=True)


def test_admin_guard_gifts_page_shows_current_month_when_no_records(
    client,
    app,
    monkeypatch,
):
    from services import guard_gift_service

    monkeypatch.setattr(
        guard_gift_service.GuardGiftService,
        "get_current_month",
        staticmethod(lambda: "2026-06"),
    )

    with app.app_context():
        admin = User(uid="admin-empty-gift", nickname="admin")
        admin.add_role("admin")
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id

    with client.session_transaction() as flask_session:
        flask_session["_user_id"] = str(admin_id)

    response = client.get("/admin/guard-gifts")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '<option value="2026-06" selected>2026-06</option>' in html

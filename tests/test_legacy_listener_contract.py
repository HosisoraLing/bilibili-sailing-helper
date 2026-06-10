from pathlib import Path


def test_legacy_listener_preserves_atomic_code_contract():
    listener_source = Path("services/danmaku_listener.py").read_text(encoding="utf-8")
    internal_api_source = Path("services/internal_api_service.py").read_text(encoding="utf-8")

    assert "mark_auth_success" not in listener_source
    assert "mark_auth_success(session, expected_code=content)" in internal_api_source

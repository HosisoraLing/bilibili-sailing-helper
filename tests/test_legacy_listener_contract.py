from pathlib import Path


def test_legacy_listener_preserves_atomic_code_contract():
    listener_source = Path("services/danmaku_listener.py").read_text(encoding="utf-8")

    assert "mark_auth_success(session, expected_code=input_code)" in listener_source

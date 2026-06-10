from pathlib import Path


def test_runtime_files_do_not_reference_playwright_or_browser_installs():
    checked_paths = [
        Path("requirements.txt"),
        Path("Dockerfile"),
        Path("services/cookie_service.py"),
        Path("services/bilibili_qr_service.py"),
        Path("routes.py"),
        Path("get_cookies.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in checked_paths)

    assert "playwright" not in combined.lower()
    assert "chromium" not in combined.lower()
    assert "xvfb" not in combined.lower()


def test_admin_qr_image_is_served_locally():
    admin_source = Path("templates/admin_panel.html").read_text(encoding="utf-8")

    assert "api.qrserver" not in admin_source
    assert "/admin/cookie/qrcode/" in admin_source

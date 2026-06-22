#!/usr/bin/env python3
"""
手动导入 B 站 Cookie 的兼容工具。

扫码登录已迁移到管理员页面的 Passport QR API，不再依赖浏览器自动化。
"""
from services.bilibili_qr_service import validate_cookie_header
from services.cookie_service import CookieService


def main():
    print("=" * 50)
    print("B站 Cookie 导入工具")
    print("=" * 50)
    print("扫码登录请打开管理员页面，点击“扫码登录”。")
    print("这里仅用于手动粘贴完整 Cookie Header。\n")

    cookie_header = input("请粘贴 Cookie Header: ").strip()
    validation = validate_cookie_header(cookie_header)
    if not validation["valid"]:
        print(f"验证失败: {validation['message']}")
        return

    settings = CookieService.load_settings()
    bilibili = settings.setdefault("bilibili", {})
    cookie_map = validation["cookie_map"]
    for key in ("SESSDATA", "bili_jct", "buvid3"):
        if cookie_map.get(key):
            bilibili[key] = cookie_map[key]

    if CookieService.save_settings(settings):
        print(f"导入成功: {validation.get('username') or 'B站用户'}")
    else:
        print("导入成功但保存 settings.json 失败")


if __name__ == "__main__":
    main()

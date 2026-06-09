#!/usr/bin/env python3
"""
自动获取 B站 cookie
- buvid3: 自动获取（无需登录）
- SESSDATA: 需要用户手动输入或扫码登录
- bili_jct: 可选（弹幕监听不需要）
"""
import json
import sys
import time

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("请先安装 playwright: pip install playwright && playwright install chromium")
    sys.exit(1)


SETTINGS_PATH = 'settings.json'


def load_settings():
    try:
        with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"错误: 找不到 {SETTINGS_PATH}")
        sys.exit(1)


def save_settings(settings):
    with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=4, ensure_ascii=False)
    print(f"✅ 已保存到 {SETTINGS_PATH}")


def get_buvid3():
    """自动获取 buvid3（无需登录）"""
    print("🔄 自动获取 buvid3...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto('https://www.bilibili.com')
        page.wait_for_timeout(2000)
        
        cookies = {c['name']: c['value'] for c in context.cookies()}
        browser.close()
        
        if 'buvid3' in cookies:
            print(f"  ✅ buvid3: {cookies['buvid3'][:40]}...")
            return cookies['buvid3']
        else:
            print("  ❌ 无法获取 buvid3")
            return None


def get_sessdata_by_qr():
    """通过二维码获取 SESSDATA"""
    import os
    import subprocess
    
    QR_IMAGE_PATH = '/tmp/bilibili_qr.png'
    
    # 启动虚拟显示器
    subprocess.Popen(['Xvfb', ':99', '-screen', '0', '1280x720x24', '-nolisten', 'tcp'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    os.environ['DISPLAY'] = ':99'
    
    print("🚀 启动浏览器...")
    print("📋 将生成二维码图片，请用 B站 APP 扫码登录\n")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        
        # 打开 B站 登录页面
        page.goto('https://passport.bilibili.com/login')
        time.sleep(3)
        
        # 截取整个页面（包含二维码）
        page.screenshot(path=QR_IMAGE_PATH)
        print(f"📸 二维码已保存到: {QR_IMAGE_PATH}")
        print("请使用 B站 APP 扫描二维码登录\n")
        
        # 等待用户登录
        print("等待登录中...", end="", flush=True)
        max_wait = 300
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            cookies = {c['name']: c['value'] for c in context.cookies()}
            
            if 'SESSDATA' in cookies and cookies['SESSDATA'] and len(cookies['SESSDATA']) > 10:
                print("\n✅ 登录成功！")
                sessdata = cookies['SESSDATA']
                bili_jct = cookies.get('bili_jct', '')
                browser.close()
                return sessdata, bili_jct
            
            time.sleep(2)
            print(".", end="", flush=True)
        
        print("\n❌ 等待超时")
        browser.close()
        return None, None


def main():
    settings = load_settings()
    
    print("=" * 50)
    print("B站 Cookie 自动获取工具")
    print("=" * 50 + "\n")
    
    # 1. 自动获取 buvid3
    buvid3 = get_buvid3()
    if buvid3:
        settings['bilibili']['buvid3'] = buvid3
    
    # 2. 获取 SESSDATA
    print("\n" + "-" * 50)
    print("获取 SESSDATA:")
    print("  1. 扫码登录（推荐）")
    print("  2. 手动输入")
    print("-" * 50)
    
    choice = input("\n请选择 (1/2): ").strip()
    
    if choice == '1':
        sessdata, bili_jct = get_sessdata_by_qr()
        if sessdata:
            settings['bilibili']['SESSDATA'] = sessdata
            if bili_jct:
                settings['bilibili']['bili_jct'] = bili_jct
        else:
            print("❌ 扫码登录失败")
            return
    elif choice == '2':
        print("\n请从浏览器获取 SESSDATA:")
        print("  1. 登录 B站")
        print("  2. 按 F12 打开开发者工具")
        print("  3. 进入 Application > Cookies > bilibili.com")
        print("  4. 复制 SESSDATA 的值\n")
        
        sessdata = input("请输入 SESSDATA: ").strip()
        if sessdata:
            settings['bilibili']['SESSDATA'] = sessdata
        else:
            print("❌ SESSDATA 不能为空")
            return
    else:
        print("❌ 无效选择")
        return
    
    # 保存设置
    save_settings(settings)
    
    # 验证
    print("\n" + "=" * 50)
    print("验证 Cookie...")
    print("=" * 50)
    
    import requests
    cookies = {'SESSDATA': settings['bilibili']['SESSDATA']}
    headers = {'User-Agent': 'Mozilla/5.0'}
    r = requests.get('https://api.bilibili.com/x/web-interface/nav', cookies=cookies, headers=headers)
    data = r.json()
    
    if data['code'] == 0 and data['data']['isLogin']:
        print(f"✅ 登录状态正常: {data['data']['uname']} (UID: {data['data']['mid']})")
        print("\n🎉 Cookie 获取成功！现在可以运行 app.py 了")
    else:
        print(f"❌ 登录验证失败: {data['message']}")


if __name__ == '__main__':
    main()

"""
Cookie服务模块
自动获取B站Cookie
"""
import json
import time
import threading
from typing import Optional, Tuple
from utils.log_utils import get_logger

logger = get_logger(__name__)

SETTINGS_PATH = 'settings.json'


class CookieService:
    """Cookie服务类"""
    
    @staticmethod
    def load_settings() -> dict:
        """加载配置文件"""
        try:
            with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"配置文件不存在: {SETTINGS_PATH}")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"配置文件格式错误: {e}")
            return {}
    
    @staticmethod
    def save_settings(settings: dict) -> bool:
        """保存配置文件"""
        try:
            with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4, ensure_ascii=False)
            logger.info("配置文件已保存")
            return True
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            return False
    
    @staticmethod
    def get_buvid3() -> Optional[str]:
        """
        自动获取 buvid3（无需登录）
        
        Returns:
            str: buvid3值，失败返回None
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("playwright未安装，请运行: pip install playwright && playwright install chromium")
            return None
        
        logger.info("开始获取buvid3...")
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()
                page.goto('https://www.bilibili.com')
                page.wait_for_timeout(2000)
                
                cookies = {c['name']: c['value'] for c in context.cookies()}
                browser.close()
                
                if 'buvid3' in cookies:
                    logger.info(f"获取buvid3成功: {cookies['buvid3'][:40]}...")
                    return cookies['buvid3']
                else:
                    logger.warning("无法获取buvid3")
                    return None
        except Exception as e:
            logger.error(f"获取buvid3失败: {e}", exc_info=True)
            return None
    
    @staticmethod
    def get_sessdata_by_qr() -> Tuple[Optional[str], Optional[str]]:
        """
        通过二维码获取 SESSDATA
        
        Returns:
            Tuple[str, str]: (SESSDATA, bili_jct)，失败返回(None, None)
        """
        import os
        import subprocess
        
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("playwright未安装")
            return None, None
        
        QR_IMAGE_PATH = '/tmp/bilibili_qr.png'
        
        # 启动虚拟显示器
        try:
            subprocess.Popen(
                ['Xvfb', ':99', '-screen', '0', '1280x720x24', '-nolisten', 'tcp'],
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL
            )
            time.sleep(1)
            os.environ['DISPLAY'] = ':99'
        except FileNotFoundError:
            logger.warning("Xvfb未安装，尝试使用headless模式")
        
        logger.info("启动浏览器获取二维码...")
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()
                
                # 打开B站登录页面
                page.goto('https://passport.bilibili.com/login')
                
                # 等待二维码加载
                try:
                    page.wait_for_selector('img[src*="qr"], canvas, .login-scan-box', timeout=15000)
                    time.sleep(2)
                except Exception as e:
                    logger.warning(f"等待二维码元素超时: {e}")
                    page.screenshot(path=QR_IMAGE_PATH)
                    logger.info(f"已截取整个页面到: {QR_IMAGE_PATH}")
                
                # 尝试截取二维码元素
                try:
                    # 尝试多种选择器
                    qr_element = None
                    for selector in ['img[src*="qr"]', 'canvas', '.login-scan-box img']:
                        qr_element = page.query_selector(selector)
                        if qr_element:
                            break
                    
                    if qr_element:
                        qr_element.screenshot(path=QR_IMAGE_PATH)
                        logger.info(f"二维码已保存到: {QR_IMAGE_PATH}")
                    else:
                        # 截取页面中心区域
                        page.screenshot(path=QR_IMAGE_PATH, clip={'x': 250, 'y': 200, 'width': 300, 'height': 300})
                        logger.info(f"已截取页面区域到: {QR_IMAGE_PATH}")
                except Exception as e:
                    logger.warning(f"截取二维码失败: {e}")
                    page.screenshot(path=QR_IMAGE_PATH)
                
                # 等待用户登录
                max_wait = 300
                start_time = time.time()
                
                while time.time() - start_time < max_wait:
                    cookies = {c['name']: c['value'] for c in context.cookies()}
                    
                    if 'SESSDATA' in cookies and cookies['SESSDATA'] and len(cookies['SESSDATA']) > 10:
                        logger.info("登录成功！")
                        sessdata = cookies['SESSDATA']
                        bili_jct = cookies.get('bili_jct', '')
                        browser.close()
                        return sessdata, bili_jct
                    
                    time.sleep(2)
                
                logger.warning("等待登录超时")
                browser.close()
                return None, None
                
        except Exception as e:
            logger.error(f"获取SESSDATA失败: {e}", exc_info=True)
            return None, None
    
    @staticmethod
    def auto_update_buvid3() -> bool:
        """
        自动更新buvid3
        
        Returns:
            bool: 是否成功更新
        """
        settings = CookieService.load_settings()
        if not settings:
            return False
        
        buvid3 = CookieService.get_buvid3()
        if buvid3:
            settings.setdefault('bilibili', {})['buvid3'] = buvid3
            return CookieService.save_settings(settings)
        return False
    
    @staticmethod
    def validate_cookie(sessdata: str) -> Tuple[bool, Optional[str]]:
        """
        验证Cookie是否有效
        
        Args:
            sessdata: SESSDATA值
            
        Returns:
            Tuple[bool, str]: (是否有效, 用户名或错误信息)
        """
        import requests
        
        cookies = {'SESSDATA': sessdata}
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        try:
            r = requests.get(
                'https://api.bilibili.com/x/web-interface/nav',
                cookies=cookies,
                headers=headers,
                timeout=10
            )
            data = r.json()
            
            if data['code'] == 0 and data['data']['isLogin']:
                return True, data['data']['uname']
            else:
                return False, data.get('message', '未知错误')
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def start_auto_refresh_scheduler(app):
        """
        启动Cookie自动刷新定时任务
        - 每天凌晨4点自动刷新buvid3
        """
        import threading
        import time
        from datetime import datetime
        
        last_refresh_date = None
        
        def scheduler():
            nonlocal last_refresh_date
            
            while True:
                try:
                    now = datetime.now()
                    today_str = now.strftime('%Y-%m-%d')
                    
                    # 每天凌晨4点刷新
                    if now.hour == 4 and now.minute == 0 and last_refresh_date != today_str:
                        logger.info("开始自动刷新buvid3...")
                        
                        with app.app_context():
                            success = CookieService.auto_update_buvid3()
                            if success:
                                logger.info("buvid3自动刷新成功")
                            else:
                                logger.warning("buvid3自动刷新失败")
                        
                        last_refresh_date = today_str
                    
                except Exception as e:
                    logger.error(f"Cookie自动刷新任务出错: {e}", exc_info=True)
                
                # 每分钟检查一次
                time.sleep(60)
        
        thread = threading.Thread(target=scheduler, daemon=True)
        thread.start()
        logger.info("Cookie自动刷新任务已启动（每天凌晨4点）")

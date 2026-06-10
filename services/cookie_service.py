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
    def get_sessdata_by_qr(qr_ready_event=None) -> Tuple[Optional[str], Optional[str]]:
        """
        通过二维码获取 SESSDATA
        
        Args:
            qr_ready_event: 可选的threading.Event，二维码生成完成时会set()
        
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
                
                # 等待页面完全加载
                page.wait_for_load_state('networkidle')
                time.sleep(3)
                
                # 尝试提取二维码图片
                try:
                    import base64
                    
                    # 多次尝试获取有效的二维码
                    for attempt in range(3):
                        # 查找base64编码的图片
                        images = page.query_selector_all('img[src^="data:image"]')
                        
                        for img in images:
                            src = img.get_attribute('src') or ''
                            if src.startswith('data:image') and len(src) > 1000:  # 过滤小图标
                                # 提取base64数据
                                header, data = src.split(',', 1)
                                img_bytes = base64.b64decode(data)
                                
                                # 检查是否是有效的二维码（至少100x100像素）
                                if len(img_bytes) > 1000:
                                    # 保存图片
                                    with open(QR_IMAGE_PATH, 'wb') as f:
                                        f.write(img_bytes)
                                    
                                    logger.info(f"二维码已保存到: {QR_IMAGE_PATH} (尝试 {attempt + 1})")
                                    # 通知二维码已就绪
                                    if qr_ready_event:
                                        qr_ready_event.set()
                                    break
                        else:
                            # 没有找到合适的图片，等待后重试
                            time.sleep(2)
                            page.reload()
                            page.wait_for_load_state('networkidle')
                            time.sleep(3)
                            continue
                        break
                    
                    # 如果base64方式失败，尝试截取canvas
                    if not os.path.exists(QR_IMAGE_PATH):
                        canvas = page.query_selector('canvas')
                        if canvas:
                            canvas.screenshot(path=QR_IMAGE_PATH)
                            logger.info(f"canvas二维码已保存到: {QR_IMAGE_PATH}")
                            if qr_ready_event:
                                qr_ready_event.set()
                        else:
                            # 最后尝试截取整个页面
                            page.screenshot(path=QR_IMAGE_PATH)
                            logger.info(f"已截取整个页面到: {QR_IMAGE_PATH}")
                            if qr_ready_event:
                                qr_ready_event.set()
                except Exception as e:
                    logger.warning(f"提取二维码失败: {e}")
                    # 即使失败也通知，避免前端一直等待
                    if qr_ready_event:
                        qr_ready_event.set()
                    page.screenshot(path=QR_IMAGE_PATH)
                
                # 等待用户扫码登录（通过URL变化检测）
                max_wait = 300
                start_time = time.time()
                
                logger.info("二维码已就绪，等待用户扫码...")
                
                while time.time() - start_time < max_wait:
                    try:
                        # 检查URL是否变化（登录成功后会跳转）
                        current_url = page.url
                        if 'passport.bilibili.com/login' not in current_url:
                            logger.info(f"检测到页面跳转: {current_url}")
                            # 登录成功，访问主站获取cookies
                            page.goto('https://www.bilibili.com')
                            page.wait_for_load_state('networkidle')
                            time.sleep(2)
                        
                        cookies = {c['name']: c['value'] for c in context.cookies()}
                        
                        if 'SESSDATA' in cookies and cookies['SESSDATA'] and len(cookies['SESSDATA']) > 10:
                            logger.info(f"登录成功！获取到SESSDATA")
                            sessdata = cookies['SESSDATA']
                            bili_jct = cookies.get('bili_jct', '')
                            browser.close()
                            return sessdata, bili_jct
                        
                        # 尝试检测页面上的登录成功提示
                        success_elem = page.query_selector('.login-success, .logged-in, [class*="success"]')
                        if success_elem:
                            logger.info("检测到登录成功提示，刷新页面获取cookies")
                            page.goto('https://www.bilibili.com')
                            page.wait_for_load_state('networkidle')
                            time.sleep(2)
                            cookies = {c['name']: c['value'] for c in context.cookies()}
                            if 'SESSDATA' in cookies and cookies['SESSDATA'] and len(cookies['SESSDATA']) > 10:
                                logger.info(f"登录成功！获取到SESSDATA")
                                sessdata = cookies['SESSDATA']
                                bili_jct = cookies.get('bili_jct', '')
                                browser.close()
                                return sessdata, bili_jct
                    except Exception as e:
                        logger.warning(f"检测登录状态时出错: {e}")
                    
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

import json
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
        从现有配置读取 buvid3。

        Browserless QR 登录成功时会保存 B 站返回的 buvid3；不再通过浏览器自动生成。
        
        Returns:
            str: buvid3值，失败返回None
        """
        settings = CookieService.load_settings()
        return settings.get('bilibili', {}).get('buvid3') or None
    
    @staticmethod
    def get_sessdata_by_qr(qr_ready_event=None) -> Tuple[Optional[str], Optional[str]]:
        """
        旧同步接口已被 browserless Passport QR API 替代。
        
        Args:
            qr_ready_event: 可选的threading.Event，二维码生成完成时会set()
        
        Returns:
            Tuple[str, str]: (SESSDATA, bili_jct)，失败返回(None, None)
        """
        if qr_ready_event:
            qr_ready_event.set()
        logger.warning("get_sessdata_by_qr 已废弃，请使用 services.bilibili_qr_service")
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
        
        buvid3 = settings.get('bilibili', {}).get('buvid3')
        if buvid3:
            logger.info("buvid3 已存在，无需浏览器刷新")
            return True
        logger.warning("当前 Cookie 缺少 buvid3，请通过扫码登录重新获取完整 Cookie")
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

import os
import json

# ================= 基础路径 =================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

SETTINGS_PATH = os.path.join(BASE_DIR, 'settings.json')

# 安全地加载配置文件
try:
    with open(SETTINGS_PATH, encoding='utf-8') as f:
        settings = json.load(f)
except FileNotFoundError:
    raise RuntimeError(f'配置文件不存在: {SETTINGS_PATH}')
except json.JSONDecodeError as e:
    raise RuntimeError(f'配置文件格式错误: {e}')
except PermissionError:
    raise RuntimeError(f'无权限读取配置文件: {SETTINGS_PATH}')
except Exception as e:
    raise RuntimeError(f'读取配置文件失败: {e}')

# 验证配置文件基本结构
if not isinstance(settings, dict):
    raise RuntimeError('配置文件必须是 JSON 对象')


# ================= 主播配置 =================

anchor_cfg = settings.get('anchor', {})

ANCHOR_NICKNAME = anchor_cfg.get('nickname', '主播')
ROOM_ID = anchor_cfg.get('room_id')
RUID = anchor_cfg.get('ruid')

if not ROOM_ID:
    raise RuntimeError('setting.json 中未配置 anchor.room_id')

if not RUID:
    raise RuntimeError('setting.json 中未配置 anchor.ruid')

ROOM_ID_INT = int(ROOM_ID)
ROOM_ID_STR = str(ROOM_ID)
RUID_INT = int(RUID)

ANCHOR_LIVE_URL = f"https://live.bilibili.com/{ROOM_ID_STR}"


# ================= B站登录凭证 =================

bili_cfg = settings.get('bilibili', {})
SESSDATA = bili_cfg.get('SESSDATA', '')
BILI_JCT = bili_cfg.get('bili_jct', '')
BUVID3 = bili_cfg.get('buvid3', '')


# ================= Admin 配置 =================

admin_cfg = settings.get('admin', {})
ADMIN_UIDS = admin_cfg.get('uids', [])


# ================= 业务文件路径 =================

REGION_JSON_PATH = os.path.join(STATIC_DIR, 'china-regions.json')


# ================= 外部接口 =================

GUARD_URL = 'https://api.live.bilibili.com/xlive/app-room/v2/guardTab/topListNew'
ALI_REGION_URL = 'https://raw.githubusercontent.com/airyland/china-area-data/master/data.json'


# ================= Flask / SQLAlchemy =================

def _build_sqlite_uri(uri: str) -> str:
    if uri.startswith('sqlite:///'):
        rel_path = uri.replace('sqlite:///', '', 1)
        abs_path = os.path.normpath(os.path.join(BASE_DIR, rel_path))
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        return f"sqlite:///{abs_path}"
    return uri


class Config:
    SQLALCHEMY_DATABASE_URI = _build_sqlite_uri(
        settings.get('database', {}).get('url')
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SECRET_KEY = settings.get('flask', {}).get('secret_key', 'dev-secret')
    DEBUG = settings.get('flask', {}).get('debug', False)
    HOST = settings.get('flask', {}).get('host', '127.0.0.1')
    PORT = settings.get('flask', {}).get('port', 5000)

    # HTTPS 配置（可选，默认关闭）
    ssl_cfg = settings.get('ssl', {})
    SSL_ENABLED = ssl_cfg.get('enabled', False)
    SSL_CERT_FILE = ssl_cfg.get('cert_file', '')
    SSL_KEY_FILE = ssl_cfg.get('key_file', '')
    SSL_PORT = ssl_cfg.get('port', 7112)

    ANCHOR_NICKNAME = ANCHOR_NICKNAME
    ANCHOR_LIVE_URL = ANCHOR_LIVE_URL
    ROOM_ID = ROOM_ID_INT

    SESSDATA = SESSDATA
    BILI_JCT = BILI_JCT
    BUVID3 = BUVID3

    ADMIN_UIDS = ADMIN_UIDS
    RUID = RUID_INT

    # CORS 配置（WebSocket 允许的来源）
    CORS_ALLOWED_ORIGINS = settings.get('flask', {}).get('cors_allowed_origins', '*')

    # 反向代理配置
    SERVER_NAME = settings.get('flask', {}).get('server_name', '')
    PREFERRED_URL_SCHEME = settings.get('flask', {}).get('preferred_url_scheme', 'http')

    # Session Cookie 安全标志
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = settings.get('flask', {}).get('session_cookie_secure', False)

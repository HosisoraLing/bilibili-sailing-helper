"""
Flask 应用主模块
包含应用工厂函数和初始化逻辑
"""
from flask import Flask, session
from flask_login import LoginManager, current_user
from flask_socketio import SocketIO, emit, join_room
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config
from db.models import db, User, Guard
from services.region_service import ensure_region_json
from services.security import SecurityManager
from routes import register_routes
from utils.log_utils import get_logger

logger = get_logger(__name__)


# =========================
# WebSocket Events
# =========================

def register_socketio_events(socketio):
    """注册 SocketIO 事件"""

    @socketio.on('join_auth')
    def handle_join_auth(data):
        """
        处理加入认证房间请求
        允许未登录用户加入房间进行鉴权
        """
        from services.user_service import UserService
        from services.danmaku_listener import set_auth_mode
        import re

        uid = data.get('uid')
        if not uid or not re.match(r'^\d{1,20}$', str(uid)):
            emit('error', {'status': 'error', 'message': '缺少 UID 参数'})
            return

        # 获取鉴权模式
        login_mode = data.get('login_mode', False)
        reset_mode = data.get('reset_mode', False)

        # 存储鉴权模式（用于后续跳转决策）
        set_auth_mode(uid, login_mode, reset_mode)

        # 验证用户访问权限（是否是陪伴榜用户或管理员）
        # 注意：这里不检查登录状态，因为鉴权页面的用户可能还未登录
        is_valid, error_msg = UserService.validate_user_access(uid)
        if not is_valid:
            emit('error', {
                'status': 'redirect',
                'message': error_msg,
                'redirect': f'/not-guard?uid={uid}'
            })
            return

        # 验证通过，加入房间
        room = f'auth_{uid}'
        join_room(room)
        emit('joined', {'status': 'ok', 'room': room})

    @socketio.on('disconnect')
    def handle_disconnect():
        pass


# =========================
# Flask App Factory
# =========================

def create_app():
    """创建 Flask 应用实例"""
    app = Flask(__name__)
    app.config.from_object(Config)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # ===== 初始化数据库 =====
    db.init_app(app)

    # ===== Flask-SocketIO =====
    socketio = SocketIO(app, cors_allowed_origins=Config.CORS_ALLOWED_ORIGINS)

    # ===== Flask-Login =====
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'main.index'
    login_manager.login_message = '登录已过期，请重新登录'
    login_manager.login_message_category = 'error'

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        """处理未登录/session过期的访问"""
        from flask import flash, redirect, url_for, request
        flash('登录已过期，请重新登录', 'error')
        # 尝试获取 uid 参数用于重定向到对应的登录页
        uid = request.args.get('uid') or request.form.get('uid')
        if uid:
            return redirect(url_for('main.login', uid=uid))
        return redirect(url_for('main.index'))

    # ===== 注入配置到模板 =====
    @app.context_processor
    def inject_config():
        return {
            'config': Config,
            'csrf_token': SecurityManager.generate_csrf_token,
            'secure_token': lambda: SecurityManager.encrypt_token(
                f'{{"uid": "{current_user.uid if current_user.is_authenticated else ""}"}}',
                app.config['SECRET_KEY']
            ) if current_user.is_authenticated else ''
        }

    # ===== 注册路由 =====
    register_routes(app)

    # ===== 注册 SocketIO 事件 =====
    register_socketio_events(socketio)

    return app, socketio


# =========================
# 数据库迁移工具
# =========================
def run_migrations():
    """
    自动迁移数据库 schema，处理列变更等
    """
    from sqlalchemy import inspect, text

    def rebuild_cookie_metadata_without_legacy_tv_columns():
        inspector = inspect(db.engine)
        if 'cookie_metadata' not in inspector.get_table_names():
            return

        existing_columns = [col["name"] for col in inspector.get_columns('cookie_metadata')]
        legacy_tv_columns = ('tv_access_token', 'tv_refresh_token', 'tv_auth_payload_json')
        dropped_columns = [name for name in legacy_tv_columns if name in existing_columns]
        if not dropped_columns:
            return

        target_columns = [
            'id',
            'role',
            'status',
            'source',
            'masked_uid',
            'payload_json',
            'cookie_version',
            'reload_requested_version',
            'reload_requested_at',
            'web_refresh_token',
            'cookie_header',
            'sessdata_expires_at',
            'last_refresh_at',
            'last_validated_at',
            'last_error',
            'created_at',
            'updated_at',
        ]
        retained_columns = [name for name in target_columns if name in existing_columns]
        column_sql = ", ".join(f'"{name}"' for name in retained_columns)
        logger.info(
            "Migrating: Dropping legacy TV auth columns from cookie_metadata: %s",
            ", ".join(dropped_columns),
        )
        with db.engine.connect() as conn:
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(text('DROP TABLE IF EXISTS "cookie_metadata_new"'))
            conn.execute(text("""
                CREATE TABLE "cookie_metadata_new" (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role VARCHAR(32) NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'unknown',
                    source VARCHAR(32),
                    masked_uid VARCHAR(32),
                    payload_json TEXT,
                    cookie_version INTEGER NOT NULL DEFAULT 0,
                    reload_requested_version INTEGER NOT NULL DEFAULT 0,
                    reload_requested_at DATETIME,
                    web_refresh_token TEXT DEFAULT '',
                    cookie_header TEXT DEFAULT '',
                    sessdata_expires_at DATETIME,
                    last_refresh_at DATETIME,
                    last_validated_at DATETIME,
                    last_error VARCHAR(512),
                    created_at DATETIME,
                    updated_at DATETIME
                )
            """))
            conn.execute(text(
                f'INSERT INTO "cookie_metadata_new" ({column_sql}) '
                f'SELECT {column_sql} FROM "cookie_metadata"'
            ))
            conn.execute(text('DROP TABLE "cookie_metadata"'))
            conn.execute(text('ALTER TABLE "cookie_metadata_new" RENAME TO "cookie_metadata"'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_cookie_metadata_role ON cookie_metadata(role)'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_cookie_metadata_status ON cookie_metadata(status)'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_cookie_metadata_masked_uid ON cookie_metadata(masked_uid)'))
            conn.commit()
        logger.info("Migration completed: legacy TV auth columns dropped from cookie_metadata")

    inspector = inspect(db.engine)

    # Check users table
    if 'users' in inspector.get_table_names():
        columns = {col['name']: col for col in inspector.get_columns('users')}
        password_hash_col = columns.get('password_hash')

        if password_hash_col and not password_hash_col['nullable']:
            logger.info("Migrating: Altering users.password_hash to be nullable...")
            with db.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS users_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        uid VARCHAR(32) UNIQUE NOT NULL,
                        nickname VARCHAR(64) NOT NULL,
                        password_hash VARCHAR(256),
                        is_admin BOOLEAN DEFAULT 0,
                        created_at DATETIME
                    )
                """))
                conn.execute(text("""
                    INSERT INTO users_new (id, uid, nickname, password_hash, is_admin, created_at)
                    SELECT id, uid, nickname, password_hash, is_admin, created_at FROM users
                """))
                conn.execute(text("DROP TABLE users"))
                conn.execute(text("ALTER TABLE users_new RENAME TO users"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_uid ON users(uid)"))
                conn.commit()
                logger.info("Migration completed: users.password_hash is now nullable")

    # Check guards table for guard_level column
    if 'guards' in inspector.get_table_names():
        columns = {col['name']: col for col in inspector.get_columns('guards')}
        if 'guard_level' not in columns:
            logger.info("Migrating: Adding guard_level to guards table...")
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE guards ADD COLUMN guard_level VARCHAR(16) DEFAULT 'guard'"))
                conn.commit()
                logger.info("Migration completed: guards.guard_level added")

        # Check for accompany_days column
        if 'accompany_days' not in columns:
            logger.info("Migrating: Adding accompany_days to guards table...")
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE guards ADD COLUMN accompany_days INTEGER DEFAULT 0"))
                conn.commit()
                logger.info("Migration completed: guards.accompany_days added")

        # Check for in_guard column
        if 'in_guard' not in columns:
            logger.info("Migrating: Adding in_guard to guards table...")
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE guards ADD COLUMN in_guard BOOLEAN DEFAULT 1"))
                conn.commit()
                logger.info("Migration completed: guards.in_guard added")

    # Check addresses table for guard_level column
    if 'addresses' in inspector.get_table_names():
        columns = {col['name']: col for col in inspector.get_columns('addresses')}
        if 'guard_level' not in columns:
            logger.info("Migrating: Adding guard_level to addresses table...")
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE addresses ADD COLUMN guard_level VARCHAR(16) DEFAULT 'guard'"))
                conn.commit()
                logger.info("Migration completed: addresses.guard_level added")

    # Check users table for roles column
    if 'users' in inspector.get_table_names():
        columns = {col['name']: col for col in inspector.get_columns('users')}
        if 'roles' not in columns:
            logger.info("Migrating: Adding roles to users table...")
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN roles VARCHAR(256) DEFAULT '[]'"))
                conn.commit()
                logger.info("Migration completed: users.roles added")

    # Check for guard_gift_records table
    if 'guard_gift_records' not in inspector.get_table_names():
        logger.info("Migrating: Creating guard_gift_records table...")
        with db.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS guard_gift_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid VARCHAR(32) NOT NULL,
                    nickname VARCHAR(64) NOT NULL,
                    month VARCHAR(7) NOT NULL,
                    guard_level VARCHAR(16) DEFAULT 'guard',
                    accompany_days INTEGER DEFAULT 0,
                    received BOOLEAN DEFAULT 0,
                    received_at DATETIME,
                    created_at DATETIME,
                    updated_at DATETIME,
                    UNIQUE(uid, month)
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_guard_gift_records_uid ON guard_gift_records(uid)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_guard_gift_records_month ON guard_gift_records(month)"))
            conn.commit()
            logger.info("Migration completed: guard_gift_records table created")

    # Check auth_sessions table for durable auth state columns
    if 'auth_sessions' in inspector.get_table_names():
        columns = {col['name']: col for col in inspector.get_columns('auth_sessions')}
        auth_session_columns = {
            'code': 'VARCHAR(32)',
            'succeeded_at': 'DATETIME',
            'consumed_at': 'DATETIME',
            'last_attempt_at': 'DATETIME',
        }
        missing_columns = [
            (name, ddl)
            for name, ddl in auth_session_columns.items()
            if name not in columns
        ]
        if missing_columns:
            logger.info("Migrating: Adding durable auth state columns...")
            with db.engine.connect() as conn:
                for name, ddl in missing_columns:
                    conn.execute(text(f"ALTER TABLE auth_sessions ADD COLUMN {name} {ddl}"))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_auth_sessions_code "
                    "ON auth_sessions(code)"
                ))
                conn.commit()
                logger.info("Migration completed: auth_sessions durable state columns added")

    # Check runtime_statuses table for delivery visibility columns
    if 'runtime_statuses' in inspector.get_table_names():
        columns = {col['name']: col for col in inspector.get_columns('runtime_statuses')}
        runtime_status_columns = {
            'delivery_error': 'VARCHAR(512)',
            'retry_count': 'INTEGER DEFAULT 0',
            'cookie_version': 'INTEGER DEFAULT 0',
        }
        missing_columns = [
            (name, ddl)
            for name, ddl in runtime_status_columns.items()
            if name not in columns
        ]
        if missing_columns:
            logger.info("Migrating: Adding runtime status delivery columns...")
            with db.engine.connect() as conn:
                for name, ddl in missing_columns:
                    conn.execute(text(f"ALTER TABLE runtime_statuses ADD COLUMN {name} {ddl}"))
                conn.commit()
                logger.info("Migration completed: runtime_statuses delivery columns added")

    # Check cookie_metadata table for runtime Cookie version column
    if 'cookie_metadata' in inspector.get_table_names():
        columns = {col['name']: col for col in inspector.get_columns('cookie_metadata')}
        rebuild_cookie_metadata_without_legacy_tv_columns()
        inspector = inspect(db.engine)
        columns = {col['name']: col for col in inspector.get_columns('cookie_metadata')}
        cookie_metadata_columns = {
            'cookie_version': 'INTEGER DEFAULT 0',
            'reload_requested_version': 'INTEGER DEFAULT 0',
            'reload_requested_at': 'DATETIME',
            'web_refresh_token': 'TEXT DEFAULT ""',
            'cookie_header': 'TEXT DEFAULT ""',
            'sessdata_expires_at': 'DATETIME',
            'last_refresh_at': 'DATETIME',
        }
        missing_columns = [
            (name, ddl)
            for name, ddl in cookie_metadata_columns.items()
            if name not in columns
        ]
        if missing_columns:
            logger.info("Migrating: Adding Cookie metadata columns...")
            with db.engine.connect() as conn:
                for name, ddl in missing_columns:
                    conn.execute(text(f"ALTER TABLE cookie_metadata ADD COLUMN {name} {ddl}"))
                conn.commit()
                logger.info("Migration completed: Cookie metadata columns added")
        if 'cookie_header' in columns or any(name == 'cookie_header' for name, _ in missing_columns):
            with db.engine.connect() as conn:
                conn.execute(text("""
                    UPDATE cookie_metadata
                    SET source = 'migration'
                    WHERE source = 'tv_auth'
                """))
                result = conn.execute(text("""
                    UPDATE cookie_metadata
                    SET status = 'rescan_required',
                        source = CASE
                            WHEN source IS NULL OR source = '' THEN 'migration'
                            ELSE source
                        END,
                        last_error = '当前 DB 缺少 Web Cookie，请重新扫码授权 B 站账号'
                    WHERE status = 'valid'
                      AND (cookie_header IS NULL OR cookie_header = '')
                """))
                conn.commit()
                if result.rowcount:
                    logger.info(
                        "Migration completed: marked %s Cookie metadata row(s) for Web QR rescan",
                        result.rowcount,
                    )


# =========================
# 主入口
# =========================

def fetch_and_save_guards():
    """
    爬取舰长/陪伴榜用户数据并保存到数据库
    自动更新优先于手动输入，会覆盖手动修改的数据
    """
    from services.guard_service import fetch_guards
    from db.models import get_beijing_now
    from datetime import date

    logger.info("开始爬取舰长数据...")
    guards_data = fetch_guards()

    if not guards_data:
        logger.warning("未获取到舰长数据")
        return

    updated_count = 0
    created_count = 0
    removed_count = 0

    # 获取当前数据库中的所有舰长
    existing_guards = Guard.query.all()
    existing_uids = set(guard.uid for guard in existing_guards)

    # 获取爬取到的舰长UID
    fetched_uids = set(guards_data.keys())

    # 找出需要标记不在舰的舰长（在数据库中但不在爬取结果中）
    # 注意：只标记 in_guard=True 的舰长，避免影响手动添加的特殊记录
    uids_to_remove = existing_uids - fetched_uids

    for uid in uids_to_remove:
        guard = Guard.query.filter_by(uid=uid).first()
        if guard and guard.in_guard:
            guard.in_guard = False
            guard.updated_at = get_beijing_now()
            removed_count += 1
            logger.info(f"标记不在舰: {guard.nickname} (UID: {uid})")

    for uid, data in guards_data.items():
        guard = Guard.query.filter_by(uid=uid).first()

        if guard:
            # 更新现有舰长（自动更新优先，覆盖手动输入的数据）
            # 记录更新前的数据，用于日志输出
            old_nickname = guard.nickname
            old_accompany_days = guard.accompany_days

            guard.nickname = data['nickname']
            guard.guard_level = data['guard_level']
            guard.accompany_days = data.get('accompany_days', 0)
            guard.last_guard_date = date.today()
            guard.in_guard = True
            guard.updated_at = get_beijing_now()
            updated_count += 1

            # 如果手动修改的数据与自动更新的数据不同，输出日志
            if old_nickname != data['nickname'] or old_accompany_days != data.get('accompany_days', 0):
                logger.info(f"自动更新覆盖手动数据: {old_nickname} -> {data['nickname']} (UID: {uid})")
        else:
            # 创建新舰长
            guard = Guard(
                uid=uid,
                nickname=data['nickname'],
                guard_level=data['guard_level'],
                accompany_days=data.get('accompany_days', 0),
                last_guard_date=date.today(),
                in_guard=True,
                updated_at=get_beijing_now()
            )
            db.session.add(guard)
            created_count += 1
            logger.info(f"新增舰长: {data['nickname']} (UID: {uid})")

    db.session.commit()

    # 输出统计信息
    if removed_count > 0 or created_count > 0 or updated_count > 0:
        logger.info(f"舰长数据更新完成:")
        if created_count > 0:
            logger.info(f"  - 新增: {created_count} 个")
        if updated_count > 0:
            logger.info(f"  - 更新: {updated_count} 个")
        if removed_count > 0:
            logger.info(f"  - 标记不在舰: {removed_count} 个")
    else:
        logger.info("舰长数据无变化")


def start_guards_scheduler(app):
    """
    启动舰长/陪伴榜用户爬取定时任务（每5分钟一次）
    """
    import threading
    import time

    def scheduler():
        while True:
            try:
                with app.app_context():
                    fetch_and_save_guards()
            except Exception as e:
                logger.error(f"舰长爬取任务出错: {e}", exc_info=True)

            # 等待5分钟
            time.sleep(300)

    # 启动后台线程
    thread = threading.Thread(target=scheduler, daemon=True)
    thread.start()
    logger.info("舰长爬取定时任务已启动（每5分钟执行一次）")


def start_guard_gift_scheduler(app):
    """
    启动舰长礼物统计定时任务
    - 每天凌晨2点执行（自动更新当月和历史月份）
    - 每月15日凌晨4点执行
    - 每月最后一日的最后一秒执行
    """
    import threading
    import time
    from datetime import datetime
    from services.guard_gift_service import GuardGiftService

    # 记录上次执行日期，避免同一天重复执行
    last_daily_run = None
    last_monthly_run = None

    def scheduler():
        nonlocal last_daily_run, last_monthly_run
        
        while True:
            try:
                now = datetime.now()
                current_day = now.day
                current_hour = now.hour
                current_minute = now.minute
                current_second = now.second
                today_str = now.strftime('%Y-%m-%d')
                month_str = now.strftime('%Y-%m')

                # 获取当前月份的最后一天
                year = now.year
                month = now.month
                last_day = GuardGiftService.get_last_day_of_month(year, month)

                # 检查是否是每天凌晨2点（每日更新）
                is_daily_2am = (current_hour == 2 and current_minute == 0)
                
                # 检查是否是每月15日凌晨4点
                is_15th_4am = (current_day == 15 and current_hour == 4 and current_minute == 0)

                # 检查是否是每月最后一日的最后一秒（23:59:59）
                is_last_day_last_second = (
                    current_day == last_day.day and
                    current_hour == 23 and
                    current_minute == 59 and
                    current_second == 59
                )

                # 每日更新（凌晨2点）
                if is_daily_2am and last_daily_run != today_str:
                    with app.app_context():
                        logger.info("开始执行每日舰长礼物统计...")
                        
                        # 统计当月
                        eligible_records = GuardGiftService.calculate_monthly_eligible_guards()
                        if eligible_records:
                            logger.info(f"当月舰长礼物统计完成，新增 {len(eligible_records)} 个符合资格的舰长")
                        
                        # 更新历史月份
                        historical_records = GuardGiftService.update_historical_months()
                        if historical_records:
                            logger.info(f"历史月份更新完成，新增 {len(historical_records)} 条记录")
                        
                        last_daily_run = today_str

                # 每月特殊时间点更新
                if (is_15th_4am or is_last_day_last_second) and last_monthly_run != month_str:
                    with app.app_context():
                        logger.info(f"开始执行月度舰长礼物统计任务（{'每月15日4点' if is_15th_4am else '月末最后一秒'}）...")
                        
                        # 统计当月
                        eligible_records = GuardGiftService.calculate_monthly_eligible_guards()
                        if eligible_records:
                            logger.info(f"当月舰长礼物统计完成，新增 {len(eligible_records)} 个符合资格的舰长")
                        else:
                            logger.info("当月舰长礼物统计完成，无新增符合条件的舰长")
                        
                        # 更新历史月份
                        historical_records = GuardGiftService.update_historical_months()
                        if historical_records:
                            logger.info(f"历史月份更新完成，新增 {len(historical_records)} 条记录")
                        
                        last_monthly_run = month_str

            except Exception as e:
                logger.error(f"舰长礼物统计任务出错: {e}", exc_info=True)

            # 每秒检查一次
            time.sleep(1)

    # 启动后台线程
    thread = threading.Thread(target=scheduler, daemon=True)
    thread.start()
    logger.info("舰长礼物统计定时任务已启动（每天凌晨2点、每月15日4点和月末最后一秒执行）")


def start_session_cleanup_scheduler(app):
    """
    启动session清理定时任务
    - 每10分钟清理过期的鉴权session
    """
    import threading
    import time
    from services.auth_service import cleanup_expired_sessions

    def scheduler():
        while True:
            try:
                time.sleep(600)  # 每10分钟执行一次
                
                with app.app_context():
                    cleaned = cleanup_expired_sessions()
                    if cleaned > 0:
                        logger.info(f"清理了 {cleaned} 个过期鉴权session")
                        
            except Exception as e:
                logger.error(f"Session清理任务出错: {e}", exc_info=True)

    thread = threading.Thread(target=scheduler, daemon=True)
    thread.start()
    logger.info("Session清理定时任务已启动（每10分钟执行一次）")


def register_admins():
    """
    系统启动时自动注册管理员
    将配置文件内的管理员注册为管理员角色
    若管理员UID不是舰长/陪伴榜用户，则将该UID入库作为管理员身份
    """
    from db.models import Guard
    admin_uids = Config.ADMIN_UIDS
    if not admin_uids:
        return

    for uid in admin_uids:
        # 检查用户是否已存在
        user = User.query.filter_by(uid=uid).first()

        if user:
            # 用户已存在，添加管理员角色（如果还没有）
            if not user.has_role('admin'):
                user.add_role('admin')
                logger.info(f"已为现有用户 {uid} 添加管理员角色")
        else:
            # 用户不存在，创建新用户
            # 检查是否是舰长/陪伴榜用户，从数据库获取舰长信息
            guard = Guard.query.filter_by(uid=uid).first()
            if guard:
                nickname = guard.nickname
                guard_level = guard.guard_level
            else:
                nickname = f"管理员_{uid}"
                guard_level = 'guard'

            user = User(uid=uid, nickname=nickname)
            user.add_role('admin')

            # 如果是舰长/陪伴榜用户，也添加对应的角色
            if guard_level == 'guard':
                user.add_role('guard')
            elif guard_level == 'captain':
                user.add_role('captain')
            elif guard_level == 'admiral':
                user.add_role('admiral')

            db.session.add(user)
            logger.info(f"已创建管理员用户 {uid} ({nickname})")

    db.session.commit()
    logger.info(f"管理员注册完成，共处理 {len(admin_uids)} 个管理员")


def start_runtime_services(app_instance, role: str = "web"):
    logger.info("runtime role %s owns no in-process background loops", role)


def run_web_server(app_instance, socketio, config=Config):
    ssl_available = False
    if config.SSL_ENABLED and config.SSL_CERT_FILE and config.SSL_KEY_FILE:
        import ssl
        import threading
        import os

        cert_exists = os.path.exists(config.SSL_CERT_FILE)
        key_exists = os.path.exists(config.SSL_KEY_FILE)

        if cert_exists and key_exists:
            try:
                ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                ssl_context.load_cert_chain(config.SSL_CERT_FILE, config.SSL_KEY_FILE)
                ssl_available = True
            except ssl.SSLError as e:
                logger.error(f"加载 SSL 证书失败: {e}")
        else:
            logger.error(f"SSL 证书文件不存在:")
            if not cert_exists:
                logger.error(f"  - 证书文件: {config.SSL_CERT_FILE}")
            if not key_exists:
                logger.error(f"  - 密钥文件: {config.SSL_KEY_FILE}")

    if ssl_available:
        logger.info("启用 HTTPS 支持")
        logger.info(f"  - HTTP 端口: {config.PORT}")
        logger.info(f"  - HTTPS 端口: {config.SSL_PORT}")
        logger.info(f"  - SSL 证书: {config.SSL_CERT_FILE}")
        logger.info(f"  - SSL 密钥: {config.SSL_KEY_FILE}")

        http_thread = threading.Thread(
            target=lambda: socketio.run(
                app_instance,
                host=config.HOST,
                port=config.PORT,
                debug=config.DEBUG,
                use_reloader=False
            ),
            daemon=True
        )
        http_thread.start()

        https_thread = threading.Thread(
            target=lambda: socketio.run(
                app_instance,
                host=config.HOST,
                port=config.SSL_PORT,
                debug=config.DEBUG,
                use_reloader=False,
                ssl_context=ssl_context
            ),
            daemon=True
        )
        https_thread.start()

        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("服务器已停止")
    else:
        logger.info(f"仅启用 HTTP 支持（端口: {config.PORT}）")
        socketio.run(
            app_instance,
            host=config.HOST,
            port=config.PORT,
            debug=config.DEBUG,
            use_reloader=False,
            allow_unsafe_werkzeug=True
        )


if __name__ == '__main__':
    from runtime.web import main

    main()

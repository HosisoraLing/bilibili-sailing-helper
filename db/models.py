from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import json
import logging
from sqlalchemy import event
from sqlalchemy.engine import Engine

# 设置日志
logger = logging.getLogger(__name__)

db = SQLAlchemy(session_options={"expire_on_commit": False})


@event.listens_for(Engine, "connect")
def configure_sqlite_connection(dbapi_connection, connection_record):
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=5000")
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
            except Exception as exc:
                logger.warning("SQLite WAL mode unavailable: %s", exc)
        finally:
            cursor.close()

# =========================
# 北京时间工具
# =========================
BEIJING_TZ = timezone(timedelta(hours=8))

def get_beijing_now():
    """
    获取当前北京时间（无 tzinfo，适合存数据库）
    """
    return datetime.now(BEIJING_TZ).replace(tzinfo=None)


# =========================
# 舰长快照表
# =========================
class Guard(db.Model):
    __tablename__ = 'guards'

    uid = db.Column(db.String(32), primary_key=True)
    nickname = db.Column(db.String(64), nullable=False)
    last_guard_date = db.Column(db.Date, nullable=False)

    # 是否在舰
    in_guard = db.Column(db.Boolean, default=True)

    # 身份：guard/captain/admiral (舰长/提督/总督)
    guard_level = db.Column(db.String(16), default='guard')

    # 陪伴天数
    accompany_days = db.Column(db.Integer, default=0)

    updated_at = db.Column(
        db.DateTime,
        default=get_beijing_now,
        onupdate=get_beijing_now
    )

    def __repr__(self):
        return f"<Guard {self.uid} {self.nickname} {self.guard_level} in_guard={self.in_guard}>"


# =========================
# 地址提交表
# =========================
class Address(db.Model):
    __tablename__ = 'addresses'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    uid = db.Column(db.String(32), nullable=False, unique=True, index=True)
    nickname = db.Column(db.String(64), nullable=False)

    province = db.Column(db.String(32))
    city = db.Column(db.String(32))
    area = db.Column(db.String(32))
    address = db.Column(db.String(256))

    receiver = db.Column(db.String(64))
    phone = db.Column(db.String(32))

    last_guard_date = db.Column(db.Date)
    submitted_at = db.Column(db.DateTime, default=get_beijing_now)

    # 身份：guard/captain/admiral (舰长/提督/总督)
    guard_level = db.Column(db.String(16), default='guard')

    def __repr__(self):
        return f"<Address {self.uid} {self.receiver} {self.guard_level}>"


# =========================
# 用户表
# =========================
class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)

    uid = db.Column(db.String(32), unique=True, nullable=False, index=True)
    nickname = db.Column(db.String(64), nullable=False)

    password_hash = db.Column(db.String(256), nullable=True)

    # 身份列表：JSON 格式 ["admin", "guard", "captain", "admiral"]
    roles = db.Column(db.String(256), default='[]')

    created_at = db.Column(db.DateTime, default=get_beijing_now)

    # ===== Flask-Login 兼容 =====
    def get_id(self):
        return str(self.id)

    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    # ===== 密码 =====
    def set_password(self, password: str):
        """设置密码（使用werkzeug默认配置）"""
        try:
            self.password_hash = generate_password_hash(password)
        except Exception as e:
            logger.error(f"设置密码失败: {e}")
            raise

    def check_password(self, password: str) -> bool:
        """验证密码"""
        if not self.password_hash:
            return False
        try:
            return check_password_hash(self.password_hash, password)
        except Exception as e:
            logger.error(f"密码验证失败: {e}")
            return False

    # ===== 角色管理 =====
    def get_roles(self) -> list:
        """获取用户角色列表"""
        try:
            return json.loads(self.roles)
        except json.JSONDecodeError as e:
            logger.warning(f"解析用户 {self.uid} 角色列表失败: {e}, roles={self.roles}")
            return []
        except Exception as e:
            logger.error(f"获取用户 {self.uid} 角色列表时发生错误: {e}")
            return []

    def set_roles(self, roles: list):
        """设置用户角色列表"""
        try:
            self.roles = json.dumps(roles)
        except (TypeError, ValueError) as e:
            logger.error(f"设置用户 {self.uid} 角色列表失败: {e}")
            raise

    def has_role(self, role: str) -> bool:
        """检查用户是否有指定角色"""
        return role in self.get_roles()

    def add_role(self, role: str):
        """添加角色"""
        roles = self.get_roles()
        if role not in roles:
            roles.append(role)
            self.set_roles(roles)
            logger.info(f"为用户 {self.uid} 添加角色: {role}")

    def remove_role(self, role: str):
        """移除角色"""
        roles = self.get_roles()
        if role in roles:
            roles.remove(role)
            self.set_roles(roles)
            logger.info(f"为用户 {self.uid} 移除角色: {role}")

    def is_admin(self) -> bool:
        """检查是否是管理员"""
        return self.has_role('admin')

    def __repr__(self):
        return f"<User uid={self.uid} roles={self.roles}>"




# =========================
# 弹幕鉴权会话表
# =========================
class AuthSession(db.Model):
    __tablename__ = 'auth_sessions'

    id = db.Column(db.Integer, primary_key=True)

    uid = db.Column(db.String(32), nullable=False, index=True)
    code = db.Column(db.String(32), index=True)

    # pending / success / expired
    status = db.Column(
        db.String(16),
        nullable=False,
        default='pending'
    )

    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=get_beijing_now)
    succeeded_at = db.Column(db.DateTime)
    consumed_at = db.Column(db.DateTime)
    last_attempt_at = db.Column(db.DateTime)

    def is_expired(self) -> bool:
        """
        是否过期：只由时间判断（核心修复点）
        """
        return get_beijing_now() > self.expires_at

    def mark_success(self):
        self.status = 'success'
        self.succeeded_at = get_beijing_now()

    def mark_expired(self):
        self.status = 'expired'

    def __repr__(self):
        return f"<AuthSession uid={self.uid} status={self.status}>"


# =========================
# B站二维码登录任务表
# =========================
class QrLoginTask(db.Model):
    __tablename__ = 'qr_login_tasks'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    task_id = db.Column(db.String(64), nullable=False, unique=True, index=True)
    status = db.Column(db.String(32), nullable=False, default='pending', index=True)
    role = db.Column(db.String(32), index=True)
    qrcode_key = db.Column(db.String(128), index=True)
    qr_url = db.Column(db.String(512))
    payload_json = db.Column(db.Text)
    error_message = db.Column(db.String(512))
    created_at = db.Column(db.DateTime, default=get_beijing_now)
    updated_at = db.Column(
        db.DateTime,
        default=get_beijing_now,
        onupdate=get_beijing_now
    )
    expires_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    def __repr__(self):
        return f"<QrLoginTask task_id={self.task_id} status={self.status}>"


# =========================
# Cookie 完整性元数据表
# =========================
class CookieMetadata(db.Model):
    __tablename__ = 'cookie_metadata'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    role = db.Column(db.String(32), nullable=False, index=True)
    status = db.Column(db.String(32), nullable=False, default='unknown', index=True)
    source = db.Column(db.String(32))
    masked_uid = db.Column(db.String(32), index=True)
    payload_json = db.Column(db.Text)
    last_validated_at = db.Column(db.DateTime)
    last_error = db.Column(db.String(512))
    created_at = db.Column(db.DateTime, default=get_beijing_now)
    updated_at = db.Column(
        db.DateTime,
        default=get_beijing_now,
        onupdate=get_beijing_now
    )

    def __repr__(self):
        return f"<CookieMetadata role={self.role} status={self.status}>"


# =========================
# 鉴权尝试记录表
# =========================
class AuthAttempt(db.Model):
    __tablename__ = 'auth_attempts'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    session_id = db.Column(db.Integer, db.ForeignKey('auth_sessions.id'), index=True)
    uid = db.Column(db.String(32), nullable=False, index=True)
    status = db.Column(db.String(32), nullable=False, index=True)
    code = db.Column(db.String(32), index=True)
    nickname = db.Column(db.String(64))
    room_id = db.Column(db.String(32), index=True)
    payload_json = db.Column(db.Text)
    error_message = db.Column(db.String(512))
    created_at = db.Column(db.DateTime, default=get_beijing_now)

    def __repr__(self):
        return f"<AuthAttempt uid={self.uid} status={self.status}>"


# =========================
# 运行时角色状态表
# =========================
class RuntimeStatus(db.Model):
    __tablename__ = 'runtime_statuses'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    role = db.Column(db.String(32), nullable=False, index=True)
    instance_id = db.Column(db.String(64), nullable=False, index=True)
    state = db.Column(db.String(32), nullable=False, default='unknown', index=True)
    payload_json = db.Column(db.Text)
    last_error = db.Column(db.String(512))
    last_event_at = db.Column(db.DateTime)
    heartbeat_at = db.Column(db.DateTime, default=get_beijing_now, index=True)
    created_at = db.Column(db.DateTime, default=get_beijing_now)
    updated_at = db.Column(
        db.DateTime,
        default=get_beijing_now,
        onupdate=get_beijing_now
    )

    __table_args__ = (
        db.UniqueConstraint('role', 'instance_id', name='uix_runtime_role_instance'),
    )

    def __repr__(self):
        return f"<RuntimeStatus role={self.role} instance={self.instance_id} state={self.state}>"


# =========================
# 调度任务状态表
# =========================
class SchedulerJob(db.Model):
    __tablename__ = 'scheduler_jobs'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    job_id = db.Column(db.String(64), nullable=False, unique=True, index=True)
    job_type = db.Column(db.String(64), nullable=False, index=True)
    status = db.Column(db.String(32), nullable=False, default='pending', index=True)
    requested_by = db.Column(db.String(64), index=True)
    payload_json = db.Column(db.Text)
    result_json = db.Column(db.Text)
    last_error = db.Column(db.String(512))
    created_at = db.Column(db.DateTime, default=get_beijing_now)
    updated_at = db.Column(
        db.DateTime,
        default=get_beijing_now,
        onupdate=get_beijing_now
    )
    scheduled_at = db.Column(db.DateTime, index=True)
    started_at = db.Column(db.DateTime)
    finished_at = db.Column(db.DateTime)

    def __repr__(self):
        return f"<SchedulerJob job_id={self.job_id} status={self.status}>"


# =========================
# 舰长礼物可用名单表
# =========================
class GuardGiftRecord(db.Model):
    __tablename__ = 'guard_gift_records'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    uid = db.Column(db.String(32), nullable=False, index=True)
    nickname = db.Column(db.String(64), nullable=False)

    # 月份，格式：YYYY-MM
    month = db.Column(db.String(7), nullable=False, index=True)

    # 身份：guard/captain/admiral (舰长/提督/总督)
    guard_level = db.Column(db.String(16), default='guard')

    # 陪伴天数（用于判断资格时的原始数据）
    accompany_days = db.Column(db.Integer, default=0)

    # 是否已领取礼物
    received = db.Column(db.Boolean, default=False)

    # 领取时间
    received_at = db.Column(db.DateTime)

    # 创建时间
    created_at = db.Column(db.DateTime, default=get_beijing_now)

    # 更新时间
    updated_at = db.Column(
        db.DateTime,
        default=get_beijing_now,
        onupdate=get_beijing_now
    )

    # 唯一约束：同一用户在同一月份只能有一条记录
    __table_args__ = (
        db.UniqueConstraint('uid', 'month', name='uix_uid_month'),
    )

    def __repr__(self):
        return f"<GuardGiftRecord uid={self.uid} month={self.month} received={self.received}>"

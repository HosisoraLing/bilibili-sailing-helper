from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import json

db = SQLAlchemy()

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
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    # ===== 角色管理 =====
    def get_roles(self) -> list:
        """获取用户角色列表"""
        try:
            return json.loads(self.roles)
        except:
            return []

    def set_roles(self, roles: list):
        """设置用户角色列表"""
        self.roles = json.dumps(roles)

    def has_role(self, role: str) -> bool:
        """检查用户是否有指定角色"""
        return role in self.get_roles()

    def add_role(self, role: str):
        """添加角色"""
        roles = self.get_roles()
        if role not in roles:
            roles.append(role)
            self.set_roles(roles)

    def remove_role(self, role: str):
        """移除角色"""
        roles = self.get_roles()
        if role in roles:
            roles.remove(role)
            self.set_roles(roles)

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

    # pending / success / expired
    status = db.Column(
        db.String(16),
        nullable=False,
        default='pending'
    )

    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=get_beijing_now)

    def is_expired(self) -> bool:
        """
        是否过期：只由时间判断（核心修复点）
        """
        return get_beijing_now() > self.expires_at

    def mark_success(self):
        self.status = 'success'

    def mark_expired(self):
        self.status = 'expired'

    def __repr__(self):
        return f"<AuthSession uid={self.uid} status={self.status}>"


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

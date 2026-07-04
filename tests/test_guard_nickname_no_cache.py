"""
回归测试：验证昵称查询不串号

测试场景：
- 两个不同 UID 连续调用昵称查询
- 断言互不污染（之前缓存装饰器 bug 导致全体用户共享唯一缓存键）
"""
import pytest
from datetime import date
from db.models import db, Guard, User
from services.user_service import UserService


def test_guard_nickname_not_shared_between_users(app):
    """两个不同 UID 查询昵称，结果互不污染"""
    with app.app_context():
        # 创建两个不同 UID 的 Guard 记录
        guard1 = Guard(
            uid='10001',
            nickname='用户A的昵称',
            guard_level='guard',
            in_guard=True,
            accompany_days=30,
            last_guard_date=date.today()
        )
        guard2 = Guard(
            uid='10002',
            nickname='用户B的昵称',
            guard_level='captain',
            in_guard=True,
            accompany_days=60,
            last_guard_date=date.today()
        )
        db.session.add(guard1)
        db.session.add(guard2)
        db.session.commit()

        # 连续查询两个 UID 的昵称
        nickname1 = UserService.get_guard_nickname('10001')
        nickname2 = UserService.get_guard_nickname('10002')

        # 断言：两个昵称各自正确，互不污染
        assert nickname1 == '用户A的昵称', f"UID 10001 昵称应为 '用户A的昵称'，实际为 '{nickname1}'"
        assert nickname2 == '用户B的昵称', f"UID 10002 昵称应为 '用户B的昵称'，实际为 '{nickname2}'"

        # 再次查询，确保结果稳定
        nickname1_again = UserService.get_guard_nickname('10001')
        nickname2_again = UserService.get_guard_nickname('10002')

        assert nickname1_again == '用户A的昵称'
        assert nickname2_again == '用户B的昵称'


def test_guard_nickname_returns_none_for_nonexistent_uid(app):
    """查询不存在的 UID，应返回 None"""
    with app.app_context():
        nickname = UserService.get_guard_nickname('99999')
        assert nickname is None


def test_guard_nickname_query_reads_from_db_directly(app):
    """验证昵称查询直接读取数据库，无缓存干扰"""
    with app.app_context():
        # 创建 Guard 记录
        guard = Guard(
            uid='10003',
            nickname='原始昵称',
            guard_level='guard',
            in_guard=True,
            accompany_days=10,
            last_guard_date=date.today()
        )
        db.session.add(guard)
        db.session.commit()

        # 第一次查询
        nickname1 = UserService.get_guard_nickname('10003')
        assert nickname1 == '原始昵称'

        # 直接修改数据库中的昵称
        guard.nickname = '修改后的昵称'
        db.session.commit()

        # 第二次查询，应立即看到新值（无缓存延迟）
        nickname2 = UserService.get_guard_nickname('10003')
        assert nickname2 == '修改后的昵称', f"应读取到数据库最新值 '修改后的昵称'，实际为 '{nickname2}'"

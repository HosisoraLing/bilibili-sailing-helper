from datetime import datetime
from db.models import db, Address, Guard, get_beijing_now


def get_user_address(uid):
    """
    获取指定用户的地址信息
    返回：Address 对象或 None
    """
    return Address.query.filter_by(uid=uid).first()


def load_addresses():
    """
    从数据库加载所有已提交地址
    返回：{uid: Address}
    """
    rows = Address.query.all()
    return {row.uid: row for row in rows}


def save_address(uid, nickname, form):
    """
    保存或更新地址
    """
    # 检查是否已存在
    addr = Address.query.filter_by(uid=uid).first()

    # 获取舰长身份信息（从数据库）
    guard = Guard.query.filter_by(uid=uid).first()
    guard_level = guard.guard_level if guard else 'guard'

    if addr:
        # 更新现有地址
        addr.province = form.get('province')
        addr.city = form.get('city')
        addr.area = form.get('district')  # 表单字段名是 district
        addr.address = form.get('detail')  # 表单字段名是 detail
        addr.receiver = form.get('name')   # 表单字段名是 name
        addr.phone = form.get('phone')
        addr.submitted_at = get_beijing_now()
        addr.guard_level = guard_level
    else:
        # 创建新地址
        addr = Address(
            uid=uid,
            nickname=nickname,
            province=form.get('province'),
            city=form.get('city'),
            area=form.get('district'),  # 表单字段名是 district
            address=form.get('detail'),  # 表单字段名是 detail
            receiver=form.get('name'),   # 表单字段名是 name
            phone=form.get('phone'),
            submitted_at=get_beijing_now(),
            guard_level=guard_level
        )
        db.session.add(addr)

    db.session.commit()
    return True

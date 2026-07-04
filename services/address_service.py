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


def invalidate_address_cache(uid: str):
    """清除地址缓存（已移除内存缓存，保留接口兼容性）"""
    pass


def save_address(uid, nickname, form):
    """
    保存或更新地址
    """
    if not uid or not nickname:
        return False

    province = form.get('province')
    city = form.get('city')
    area = form.get('district')
    address = form.get('detail')
    receiver = form.get('name')
    phone = form.get('phone')

    if not province or not city or not area:
        return False

    addr = Address.query.filter_by(uid=uid).first()

    guard = Guard.query.filter_by(uid=uid).first()
    guard_level = guard.guard_level if guard else 'guard'

    if addr:
        addr.province = province
        addr.city = city
        addr.area = area
        addr.address = address
        addr.receiver = receiver
        addr.phone = phone
        addr.submitted_at = get_beijing_now()
        addr.guard_level = guard_level
    else:
        addr = Address(
            uid=uid,
            nickname=nickname,
            province=province,
            city=city,
            area=area,
            address=address,
            receiver=receiver,
            phone=phone,
            submitted_at=get_beijing_now(),
            guard_level=guard_level
        )
        db.session.add(addr)

    db.session.commit()

    return True


def delete_address(uid: str) -> bool:
    """
    删除用户地址

    Args:
        uid: 用户UID

    Returns:
        bool: 是否成功删除
    """
    addr = Address.query.filter_by(uid=uid).first()
    if addr:
        db.session.delete(addr)
        db.session.commit()

        # 清除缓存
        invalidate_address_cache(uid)
        return True

    return False


def get_address_count() -> int:
    """
    获取地址记录总数

    Returns:
        int: 地址数量
    """
    return Address.query.count()


def get_addresses_by_guard_level(guard_level: str):
    """
    按舰长等级获取地址列表

    Args:
        guard_level: 舰长等级 (guard/captain/admiral)

    Returns:
        list: 地址列表
    """
    return Address.query.filter_by(guard_level=guard_level).all()

from datetime import datetime
from db.models import db, Address, Guard, get_beijing_now
from utils.cache_utils import address_cache, guard_cache


def get_user_address(uid):
    """
    获取指定用户的地址信息
    返回：Address 对象或 None
    """
    cache_key = f"address:{uid}"

    # 尝试从缓存获取
    cached_addr = address_cache.get(cache_key)
    if cached_addr:
        return cached_addr

    addr = Address.query.filter_by(uid=uid).first()

    # 缓存结果
    if addr:
        address_cache.set(cache_key, addr, ttl=120)

    return addr


def load_addresses():
    """
    从数据库加载所有已提交地址
    返回：{uid: Address}
    """
    # 注意：这个函数加载所有地址，不适合单条缓存
    # 可以考虑使用全量缓存，但需要处理缓存失效问题
    rows = Address.query.all()
    address_map = {row.uid: row for row in rows}

    # 更新缓存
    for uid, addr in address_map.items():
        address_cache.set(f"address:{uid}", addr, ttl=120)

    return address_map


def invalidate_address_cache(uid: str):
    """清除地址缓存"""
    address_cache.delete(f"address:{uid}")


def save_address(uid, nickname, form):
    """
    保存或更新地址
    """
    # 检查是否已存在
    addr = Address.query.filter_by(uid=uid).first()

    # 获取舰长身份信息（从缓存或数据库）
    guard = guard_cache.get(f"guard:{uid}")
    if not guard:
        guard = Guard.query.filter_by(uid=uid).first()
        if guard:
            guard_cache.set(f"guard:{uid}", guard, ttl=300)

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

    # 更新缓存
    address_cache.set(f"address:{uid}", addr, ttl=120)

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

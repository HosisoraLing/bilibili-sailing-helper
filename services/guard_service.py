import requests
from datetime import date

from config import GUARD_URL, ROOM_ID, RUID
from constants import GuardLevel
from utils.cache_utils import api_response_cache, guard_cache
from utils.log_utils import get_logger

logger = get_logger(__name__)

# 粉丝团成员排行榜 API
FANS_MEMBERS_URL = "https://api.live.bilibili.com/xlive/general-interface/v1/rank/getFansMembersRank"


DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Referer': f'https://live.bilibili.com/{ROOM_ID}'
}

# 身份映射：B站 API 返回的等级 -> 内部标识
# 注意：新API中，3=舰长，2=提督，1=总督
GUARD_LEVEL_MAP = {
    3: GuardLevel.GUARD,      # 舰长
    2: GuardLevel.CAPTAIN,    # 提督
    1: GuardLevel.ADMIRAL     # 总督
}

# 身份中文名称映射
GUARD_LEVEL_NAME_MAP = {
    GuardLevel.GUARD: '舰长',
    GuardLevel.CAPTAIN: '提督',
    GuardLevel.ADMIRAL: '总督'
}


def fetch_guards(use_cache: bool = True):
    """
    拉取当前直播间所有在舰舰长（使用新API）
    返回：{uid: {'nickname': name, 'guard_level': level, 'accompany_days': days}}

    Args:
        use_cache: 是否使用缓存，默认 True
    """
    cache_key = f"guards:{ROOM_ID}:{RUID}"

    # 尝试从缓存获取
    if use_cache:
        cached_data = api_response_cache.get(cache_key)
        if cached_data:
            return cached_data

    guards = {}
    page = 1

    try:
        while True:
            params = {
                "roomid": ROOM_ID,
                "ruid": RUID,
                "page": page,
                "page_size": 30
            }

            resp = requests.get(
                GUARD_URL,
                params=params,
                headers=DEFAULT_HEADERS,
                timeout=10
            )
            data = resp.json()

            if data.get("code") != 0:
                logger.error(f"请求失败: {data}")
                break

            d = data.get("data", {})

            # page=1 时合并 top3
            if page == 1:
                for item in d.get("top3", []):
                    guard_info = parse_guard_user(item)
                    if guard_info:
                        guards[guard_info['uid']] = guard_info

            lst = d.get("list", [])
            if not lst:
                break

            for item in lst:
                guard_info = parse_guard_user(item)
                if guard_info:
                    guards[guard_info['uid']] = guard_info

            page += 1

        # 缓存结果（1分钟）
        if use_cache:
            api_response_cache.set(cache_key, guards, ttl=60)

        return guards

    except Exception as e:
        logger.error(f"获取舰长列表失败: {e}", exc_info=True)
        # 出错时返回缓存数据（即使已过期）
        cached_data = api_response_cache.get(cache_key)
        if cached_data:
            return cached_data
        return {}


def parse_guard_user(item: dict):
    """
    解析单个舰长用户信息
    返回：{uid, nickname, guard_level, accompany_days}
    """
    try:
        uinfo = item.get("uinfo", {})
        base = uinfo.get("base", {})
        guard = uinfo.get("guard", {})

        uid = str(uinfo.get("uid", ""))
        if not uid:
            return None

        # guard_level: 3=舰长, 2=提督, 1=总督
        guard_level_num = guard.get("level", 3)
        guard_level = GUARD_LEVEL_MAP.get(guard_level_num, 'guard')

        # accompany_days: 陪伴天数
        accompany_days = item.get("accompany", 0)

        return {
            "uid": uid,
            "nickname": base.get("name", ""),
            "guard_level": guard_level,
            "accompany_days": accompany_days
        }
    except Exception as e:
        logger.error(f"解析舰长信息失败: {e}, item: {item}", exc_info=True)
        return None


def fetch_fans_members(page: int = 1, page_size: int = 30, rank_type: int = 1, use_cache: bool = True) -> dict:
    """
    拉取粉丝团成员排行榜（陪伴榜）

    Args:
        page: 页数
        page_size: 每页数量（最大30，超过则作为10处理）
        rank_type: 排序方式
                   1: 按照粉丝牌还亮着的粉丝团成员的亲密度排序
                   2: 按照所有没上过舰的粉丝团成员的亲密度排序
        use_cache: 是否使用缓存，默认 True

    Returns:
        dict: 包含以下字段
            - 'items': 粉丝团成员列表（已按亲密度排序）
            - 'total': 总数量
            - 'medal_status': 粉丝牌状态
    """
    cache_key = f"fans_members:{RUID}:{page}:{page_size}:{rank_type}"

    # 尝试从缓存获取
    if use_cache:
        cached_data = api_response_cache.get(cache_key)
        if cached_data:
            return cached_data

    params = {
        "ruid": RUID,
        "page": page,
        "page_size": page_size,
        "rank_type": rank_type
    }

    # 当 rank_type=2 时需要时间戳
    if rank_type == 2:
        import time
        params["ts"] = int(time.time() * 1000)

    try:
        resp = requests.get(
            FANS_MEMBERS_URL,
            params=params,
            headers=DEFAULT_HEADERS,
            timeout=10
        )
        data = resp.json()

        if data.get("code") != 0:
            logger.error(f"请求粉丝团成员失败: {data}")
            return {"items": [], "total": 0, "medal_status": 0}

        d = data.get("data", {})
        items = d.get("item", [])
        total = d.get("num", 0)
        medal_status = d.get("medal_status", 0)

        # 解析粉丝团成员信息
        parsed_items = []
        for item in items:
            parsed = parse_fans_member(item)
            if parsed:
                parsed_items.append(parsed)

        result = {
            "items": parsed_items,
            "total": total,
            "medal_status": medal_status
        }

        # 缓存结果（30秒）
        if use_cache:
            api_response_cache.set(cache_key, result, ttl=30)

        return result

    except Exception as e:
        logger.error(f"请求粉丝团成员失败: {e}", exc_info=True)
        # 出错时返回缓存数据
        cached_data = api_response_cache.get(cache_key)
        if cached_data:
            return cached_data
        return {"items": [], "total": 0, "medal_status": 0}


def parse_fans_member(item: dict):
    """
    解析单个粉丝团成员信息

    Returns:
        dict: 包含以下字段
            - 'uid': 用户UID
            - 'nickname': 用户名
            - 'face': 头像URL
            - 'score': 亲密度
            - 'medal_name': 粉丝牌名字
            - 'medal_level': 粉丝牌等级
            - 'guard_level': 大航海类型 (1=总督, 2=提督, 3=舰长)
            - 'guard_level_name': 大航海类型中文名
            - 'user_rank': 排名
    """
    try:
        uid = str(item.get("uid", ""))
        if not uid:
            return None

        guard_level = item.get("guard_level", 0)
        guard_level_name = ""
        if guard_level == 1:
            guard_level_name = "总督"
        elif guard_level == 2:
            guard_level_name = "提督"
        elif guard_level == 3:
            guard_level_name = "舰长"

        return {
            "uid": uid,
            "nickname": item.get("name", ""),
            "face": item.get("face", ""),
            "score": item.get("score", 0),
            "medal_name": item.get("medal_name", ""),
            "medal_level": item.get("level", 0),
            "guard_level": guard_level,
            "guard_level_name": guard_level_name,
            "user_rank": item.get("user_rank", 0)
        }
    except Exception as e:
        logger.error(f"解析粉丝团成员信息失败: {e}, item: {item}", exc_info=True)
        return None


def get_guard_info(uid: str) -> dict:
    """
    获取舰长信息（带缓存）

    Args:
        uid: 用户UID

    Returns:
        dict: 舰长信息或 None
    """
    cache_key = f"guard_info:{uid}"

    # 尝试从缓存获取
    cached_info = guard_cache.get(cache_key)
    if cached_info:
        return cached_info

    # 从数据库获取
    guard = Guard.query.filter_by(uid=uid).first()
    if guard:
        info = {
            "uid": guard.uid,
            "nickname": guard.nickname,
            "guard_level": guard.guard_level,
            "in_guard": guard.in_guard,
            "accompany_days": guard.accompany_days,
            "last_guard_date": guard.last_guard_date.isoformat() if guard.last_guard_date else None
        }
        guard_cache.set(cache_key, info, ttl=300)
        return info

    return None


def invalidate_guard_cache(uid: str):
    """清除舰长缓存"""
    guard_cache.delete(f"guard:{uid}")
    guard_cache.delete(f"guard_info:{uid}")
    guard_cache.delete(f"guard_nickname:{uid}")

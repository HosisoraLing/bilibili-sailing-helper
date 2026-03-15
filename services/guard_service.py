import requests
from datetime import date

from config import GUARD_URL, ROOM_ID, RUID

# 粉丝团成员排行榜 API
FANS_MEMBERS_URL = "https://api.live.bilibili.com/xlive/general-interface/v1/rank/getFansMembersRank"


DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Referer': f'https://live.bilibili.com/{ROOM_ID}'
}

# 身份映射：B站 API 返回的等级 -> 内部标识
# 注意：新API中，3=舰长，2=提督，1=总督
GUARD_LEVEL_MAP = {
    3: 'guard',      # 舰长
    2: 'captain',    # 提督
    1: 'admiral'     # 总督
}

# 身份中文名称映射
GUARD_LEVEL_NAME_MAP = {
    'guard': '舰长',
    'captain': '提督',
    'admiral': '总督'
}


def fetch_guards():
    """
    拉取当前直播间所有在舰舰长（使用新API）
    返回：{uid: {'nickname': name, 'guard_level': level, 'accompany_days': days}}
    """
    guards = {}
    page = 1

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
            print(f"⚠ 请求失败: {data}")
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

    return guards


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
        print(f"⚠ 解析舰长信息失败: {e}, item: {item}")
        return None


def fetch_fans_members(page: int = 1, page_size: int = 30, rank_type: int = 1) -> dict:
    """
    拉取粉丝团成员排行榜（陪伴榜）

    Args:
        page: 页数
        page_size: 每页数量（最大30，超过则作为10处理）
        rank_type: 排序方式
                   1: 按照粉丝牌还亮着的粉丝团成员的亲密度排序
                   2: 按照所有没上过舰的粉丝团成员的亲密度排序

    Returns:
        dict: 包含以下字段
            - 'items': 粉丝团成员列表（已按亲密度排序）
            - 'total': 总数量
            - 'medal_status': 粉丝牌状态
    """
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
            print(f"⚠ 请求粉丝团成员失败: {data}")
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

        # 粉丝团成员API已按rank_type排序，直接返回
        # 注意：粉丝团成员API不提供accompany_days字段
        # 该字段仅在大航海成员API中可用

        return {
            "items": parsed_items,
            "total": total,
            "medal_status": medal_status
        }
    except Exception as e:
        print(f"⚠ 请求粉丝团成员失败: {e}")
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
        print(f"⚠ 解析粉丝团成员信息失败: {e}, item: {item}")
        return None

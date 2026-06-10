from __future__ import annotations

from typing import Any


def normalize_danmaku_event(raw_event: dict[str, Any], room_id: int | str) -> dict[str, str] | None:
    if not isinstance(raw_event, dict):
        return None
    raw_cmd = str(raw_event.get("cmd") or "")
    if not raw_cmd.startswith("DANMU_MSG"):
        return None

    info = raw_event.get("info")
    if not isinstance(info, list) or len(info) < 3:
        return None
    user_info = info[2]
    if not isinstance(user_info, list) or len(user_info) < 2:
        return None

    uid = user_info[0]
    nickname = user_info[1]
    content = info[1] if len(info) > 1 else ""
    if uid is None or not content:
        return None

    return {
        "uid": str(uid),
        "nickname": str(nickname or ""),
        "content": str(content),
        "room_id": str(room_id),
        "raw_cmd": raw_cmd,
    }

import os
import json
import requests
from config import REGION_JSON_PATH, ALI_REGION_URL

def ensure_region_json():
    if os.path.exists(REGION_JSON_PATH):
        return

    raw = requests.get(ALI_REGION_URL, timeout=15).json()
    result = {}

    for p_code, p_name in raw.get("86", {}).items():
        result[p_name] = {}
        for c_code, c_name in raw.get(p_code, {}).items():
            result[p_name][c_name] = list(raw.get(c_code, {}).values())

    with open(REGION_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False)

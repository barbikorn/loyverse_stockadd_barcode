"""sku_generator.py — Auto-increment SKU based on category prefix from Mapping Sheet"""

import re

import config
import sheets_auth


# ─── Mapping Sheet ────────────────────────────────────────────

def _load_prefix_map() -> dict[str, str]:
    """
    โหลด Mapping Sheet แล้วคืน dict: {category_name_lower → prefix}
    คาดว่า Mapping Sheet มี 2 columns: category | prefix
    """
    ss = sheets_auth.open_sheet_by_url(config.MAPPING_SHEET_URL)
    
    try:
        ws = ss.worksheet(config.MAPPING_SHEET_NAME)
    except Exception as e:
        available = [w.title for w in ss.worksheets()]
        raise ValueError(
            f"ไม่พบ Worksheet ชื่อ '{config.MAPPING_SHEET_NAME}' ใน Mapping Sheet\n"
            f"   (Available sheets: {available})\n"
            f"   Original error: {repr(e)}"
        )

    records = ws.get_all_records()   # list of dict จาก header row

    if not records:
        return {}

    # Check headers (case-insensitive check)
    headers = [str(k).lower() for k in records[0].keys()]
    if "category" not in headers or "prefix" not in headers:
         raise ValueError(
            f"Mapping Sheet ต้องมี column 'category' และ 'prefix'\n"
            f"   (Found headers: {list(records[0].keys())})"
        )

    mapping: dict[str, str] = {}
    for row in records:
        # Find key regardless of case
        cat_key = next((k for k in row.keys() if str(k).lower() == "category"), None)
        prefix_key = next((k for k in row.keys() if str(k).lower() == "prefix"), None)
        
        if cat_key and prefix_key:
            cat = str(row[cat_key]).strip()
            prefix = str(row[prefix_key]).strip().upper()
            if cat and prefix:
                mapping[cat.lower()] = prefix

    return mapping


def get_prefix_for_category(cat_name: str) -> str | None:
    """คืน prefix ของ category หรือ None ถ้าไม่พบใน Mapping Sheet"""
    prefix_map = _load_prefix_map()
    return prefix_map.get(cat_name.strip().lower())


# ─── SKU increment logic ──────────────────────────────────────

def _extract_number(sku: str, prefix: str) -> int | None:
    """
    แยกเลข running number ออกจาก SKU
    ตัวอย่าง: prefix="MM", sku="MM007" → 7
    """
    pattern = rf"^{re.escape(prefix)}(\d+)$"
    m = re.match(pattern, sku, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def get_next_sku(prefix: str, last_sku: str | None) -> str:
    """
    คำนวณ SKU ถัดไป
    prefix="MM", last_sku="MM003" → "MM004"
    prefix="MM", last_sku=None   → "MM001"
    """
    pad = config.SKU_DIGIT_PAD
    if last_sku:
        num = _extract_number(last_sku, prefix)
        next_num = (num + 1) if num is not None else 1
    else:
        next_num = 1
    return f"{prefix}{str(next_num).zfill(pad)}"

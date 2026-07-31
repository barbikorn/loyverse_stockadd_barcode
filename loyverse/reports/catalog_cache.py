"""
catalog_cache.py — cache item_id → category (ชื่อเจ้าของฝากขาย) ในหน่วยความจำ

ทำไมต้องมี: ทุกครั้งที่เปิดรายงาน ถ้าดึง /items ใหม่หมดทุกครั้งจะกิน rate limit
เร็วเกินไปและช้า (ร้านมีสินค้าหลักพันตัว = หลายสิบ requests) จึง cache ไว้พร้อม TTL
และมีปุ่มให้ผู้ใช้สั่ง refresh เองได้ (ไม่ใช้ lru_cache เพราะ invalidate ไม่ได้)
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from loyverse import config
from loyverse import loyverse_api as lv

NO_CATEGORY_NAME = "(ไม่มีหมวดหมู่)"


@dataclass(frozen=True)
class ItemInfo:
    item_id: str
    item_name: str
    category_id: str | None
    category_name: str  # NO_CATEGORY_NAME ถ้า category_id เป็น None หรือหาไม่เจอ


@dataclass
class Catalog:
    items: dict[str, ItemInfo] = field(default_factory=dict)          # item_id → ItemInfo
    categories: list[tuple[str, str]] = field(default_factory=list)   # [(category_id, name)]
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_lock = threading.Lock()
_cache: Catalog | None = None


def _fetch_catalog() -> Catalog:
    categories = lv.list_categories()
    category_name_by_id = {c["id"]: c["name"] for c in categories}

    items: dict[str, ItemInfo] = {}
    for item in lv.iter_all_items():
        category_id = item.get("category_id")
        category_name = category_name_by_id.get(category_id, NO_CATEGORY_NAME)
        items[item["id"]] = ItemInfo(
            item_id=item["id"],
            item_name=item.get("item_name", ""),
            category_id=category_id,
            category_name=category_name,
        )

    sorted_categories = sorted(
        ((c["id"], c["name"]) for c in categories), key=lambda c: c[1].lower()
    )
    return Catalog(items=items, categories=sorted_categories, fetched_at=datetime.now(timezone.utc))


def get_catalog(force_refresh: bool = False) -> Catalog:
    """
    คืน Catalog จาก cache (สร้างใหม่ถ้าหมดอายุตาม REPORT_CATALOG_TTL_SEC หรือถูกสั่ง refresh)
    thread-safe ด้วย lock กันสองคำขอสร้าง catalog พร้อมกัน
    """
    global _cache
    with _lock:
        if _cache is not None and not force_refresh:
            age = (datetime.now(timezone.utc) - _cache.fetched_at).total_seconds()
            if age < config.REPORT_CATALOG_TTL_SEC:
                return _cache
        _cache = _fetch_catalog()
        return _cache


def clear_cache() -> None:
    """ล้าง cache — ใช้ตอนผู้ใช้กดปุ่ม 'รีเฟรชแคตตาล็อก' บนหน้าเว็บ"""
    global _cache
    with _lock:
        _cache = None

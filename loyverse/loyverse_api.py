"""loyverse_api.py — Loyverse REST API wrapper"""

import re
import time
from functools import lru_cache

import requests

from loyverse import config

_HEADERS = {
    "Authorization": f"Bearer {config.LOYVERSE_TOKEN}",
    "Content-Type": "application/json",
}


# ─── Low-level request ────────────────────────────────────────

def _get(path: str, params: dict = None) -> dict:
    """GET พร้อม auto-retry เมื่อเจอ rate limit (429)"""
    while True:
        res = requests.get(
            f"{config.LOYVERSE_API_BASE}{path}",
            headers=_HEADERS,
            params=params or {},
        )
        if res.status_code == 429:
            print("⚠️  Rate limit — รอ 5 วินาที...")
            time.sleep(5)
            continue
        res.raise_for_status()
        return res.json()


def _post(path: str, payload: dict) -> requests.Response:
    return requests.post(
        f"{config.LOYVERSE_API_BASE}{path}",
        headers=_HEADERS,
        json=payload,
    )


# ─── Stores ───────────────────────────────────────────────────

def get_stores() -> list[dict]:
    """คืน list ของ stores ทั้งหมด"""
    data = _get("/stores")
    return data.get("stores", [])


@lru_cache(maxsize=1)
def _get_default_store_id() -> str:
    """คืน store_id แรกที่พบ (ใช้ cache เพื่อลด request)"""
    if config.LOYVERSE_STORE_ID:
        return config.LOYVERSE_STORE_ID
    
    stores = get_stores()
    if not stores:
        raise Exception("ไม่พบ Store ใน Loyverse Account นี้")
    
    # Return the first store ID
    return stores[0]["id"]


# ─── Categories ───────────────────────────────────────────────

class CategoryNotFoundError(Exception):
    """Category ไม่มีใน Loyverse — ไม่สร้างให้อัตโนมัติ"""

    def __init__(self, category_name: str):
        self.category_name = category_name
        super().__init__(f"Category '{category_name}' not found in Loyverse")


class PriceMismatchError(Exception):
    """ราคาใน Sheet ไม่ตรงกับราคาใน Loyverse"""

    def __init__(self, sheet_price: float, system_price: float):
        self.sheet_price = sheet_price
        self.system_price = system_price
        super().__init__(format_price_mismatch(sheet_price, system_price))


def format_price_mismatch(sheet_price: float, system_price: float) -> str:
    return (
        f"ราคาไม่ตรงกัน — Sheet: {sheet_price:,.2f} ≠ ระบบ: {system_price:,.2f} บาท "
        f"(แก้ราคาใน Sheet ให้ตรงกับระบบ หรืออัปเดตราคาในระบบก่อน)"
    )


def assert_price_matches(sheet_price: float, system_price: float) -> None:
    if sheet_price > 0 and system_price > 0 and abs(sheet_price - system_price) > 0.01:
        raise PriceMismatchError(sheet_price, system_price)


def get_all_categories() -> dict[str, str]:
    """คืน dict: {category_name_lower → category_id} (รองรับ pagination)"""
    cat_map: dict[str, str] = {}
    cursor = None
    while True:
        params = {"limit": 250}
        if cursor:
            params["cursor"] = cursor
        data = _get("/categories", params)
        for cat in data.get("categories", []):
            if not cat.get("deleted_at"):
                cat_map[cat["name"].lower()] = cat["id"]
        cursor = data.get("cursor")
        if not cursor:
            break
    return cat_map


def find_category_id(cat_name: str) -> str | None:
    """ค้นหา category_id จากชื่อ (case-insensitive) หรือ None ถ้าไม่พบ"""
    cat_map = get_all_categories()
    return cat_map.get(cat_name.strip().lower())


def list_categories() -> list[dict]:
    """
    คืน [{'id':..., 'name':...}] ทั้งหมด (รวม pagination, ตัด deleted)
    ต่างจาก get_all_categories() ตรงที่คืนทิศทาง id→name (รองรับชื่อซ้ำกันได้)
    ใช้สำหรับหน้ารายงานที่ต้อง list ตัวเลือก category ให้ผู้ใช้เลือก
    """
    categories: list[dict] = []
    cursor = None
    while True:
        params = {"limit": 250}
        if cursor:
            params["cursor"] = cursor
        data = _get("/categories", params)
        for cat in data.get("categories", []):
            if not cat.get("deleted_at"):
                categories.append({"id": cat["id"], "name": cat["name"]})
        cursor = data.get("cursor")
        if not cursor:
            break
    return categories


# ─── Variant / Item lookup ────────────────────────────────────

def find_variant_by_sku(sku: str) -> tuple[str, str, float, str] | None:
    """คืน (variant_id, sku, price, variant_name) จาก SKU หรือ None ถ้าไม่พบ"""
    data = _get("/variants", {"sku": sku})
    variants = data.get("variants", [])
    if variants:
        v = variants[0]
        
        # Extract price
        price = None
        if "stores" in v and v["stores"]:
             # Try to find price for default store, or use first one
             default_store = _get_default_store_id()
             found_store = None
             for s in v["stores"]:
                 if s.get("store_id") == default_store:
                     found_store = s
                     break
             
             if not found_store:
                 found_store = v["stores"][0]
            
             price = found_store.get("price")

        # Fallback to default_price if store price is missing/None
        if price is None:
            price = v.get("default_price")

        # Final safety check
        if price is None:
            price = 0.0
        else:
            price = float(price)

        # Extract variant name
        opts = [v.get(k) for k in ["option1_value", "option2_value", "option3_value"] if v.get(k)]
        var_name = " ".join(opts)

        return v["variant_id"], v.get("sku", ""), price, var_name
    return None


def find_variant_by_name(product_name: str, category_id: str | None = None) -> tuple[str, str, float, str] | None:
    """ค้นหา variant_id จากชื่อสินค้า กรองด้วย category_id (ถ้าระบุ) รองรับ pagination"""
    cursor = None
    while True:
        params = {"limit": 250}
        if cursor:
            params["cursor"] = cursor
        
        data = _get("/items", params)
        for item in data.get("items", []):
            if item.get("item_name", "").lower() != product_name.lower():
                continue
            if category_id and item.get("category_id") != category_id:
                continue

            variants = item.get("variants", [])
            if variants:
                v = variants[0]
                
                # Extract price
                price = None
                if "stores" in v and v["stores"]:
                    default_store = _get_default_store_id()
                    found_store = None
                    for s in v["stores"]:
                        if s.get("store_id") == default_store:
                            found_store = s
                            break
                    
                    if not found_store:
                        found_store = v["stores"][0]
                        
                    price = found_store.get("price")

                if price is None:
                    price = v.get("default_price")
                if price is None:
                    price = 0.0
                else:
                    price = float(price)

                opts = [v.get(k) for k in ["option1_value", "option2_value", "option3_value"] if v.get(k)]
                var_name = " ".join(opts)

                return v["variant_id"], v.get("sku", ""), price, var_name
        
        cursor = data.get("cursor")
        if not cursor:
            return None


def get_last_sku_in_category(category_id: str, prefix: str) -> str | None:
    """
    ดึง SKU ล่าสุด (running number สูงสุด) ของสินค้าใน category นี้
    กรองเฉพาะ SKU ที่ match pattern ของ prefix
    คืน SKU string หรือ None ถ้าไม่มีสินค้าใน category เลย
    """
    pattern = re.compile(rf"^{re.escape(prefix)}\d+$", re.IGNORECASE)
    max_num = 0
    last_sku: str | None = None
    cursor = None

    while True:
        params = {"limit": 250}
        if cursor:
            params["cursor"] = cursor

        data = _get("/items", params)
        for item in data.get("items", []):
            if item.get("category_id") != category_id:
                continue
            if item.get("deleted_at"):
                continue
            for variant in item.get("variants", []):
                sku = variant.get("sku", "") or ""
                if pattern.match(sku):
                    num_str = sku[len(prefix):]
                    try:
                        num = int(num_str)
                        if num > max_num:
                            max_num = num
                            last_sku = sku
                    except ValueError:
                        pass
        
        cursor = data.get("cursor")
        if not cursor:
            break

    return last_sku


def iter_all_items():
    """Generator ไล่ items ทุกหน้า (limit 250 + cursor) ตัดสินค้าที่ลบแล้วออก"""
    cursor = None
    while True:
        params = {"limit": 250}
        if cursor:
            params["cursor"] = cursor
        data = _get("/items", params)
        for item in data.get("items", []):
            if not item.get("deleted_at"):
                yield item
        cursor = data.get("cursor")
        if not cursor:
            break


# ─── Receipts ─────────────────────────────────────────────────

def iter_receipts(created_at_min: str, created_at_max: str):
    """
    Generator ไล่ receipts ทุกหน้าในช่วงเวลา (ISO 8601 UTC) ที่ store default
    yield receipt dict ทีละใบ — ใช้ generator เพื่อไม่กินแรมตอนช่วงวันยาว
    """
    store_id = _get_default_store_id()
    cursor = None
    while True:
        params = {
            "limit": 250,
            "created_at_min": created_at_min,
            "created_at_max": created_at_max,
            "store_id": store_id,
        }
        if cursor:
            params["cursor"] = cursor
        data = _get("/receipts", params)
        yield from data.get("receipts", [])
        cursor = data.get("cursor")
        if not cursor:
            break


# ─── Inventory ────────────────────────────────────────────────

def get_current_stock(variant_id: str) -> float:
    params: dict = {"variant_ids": variant_id}
    # Use default store if not configured
    store_id = _get_default_store_id()
    if store_id:
        params["store_ids"] = store_id
        
    data = _get("/inventory", params)
    levels = data.get("inventory_levels", [])
    return levels[0]["in_stock"] if levels else 0


def update_stock(variant_id: str, add_qty: int) -> tuple[float, float]:
    """เพิ่มสต็อก add_qty หน่วย คืน (stock_before, stock_after)"""
    stock_before = get_current_stock(variant_id)
    stock_after = stock_before + add_qty
    
    store_id = _get_default_store_id()
    level: dict = {
        "variant_id": variant_id,
        "stock_after": stock_after,
        "store_id": store_id
    }
    
    payload = {"inventory_levels": [level]}
    _post("/inventory", payload).raise_for_status()
    return stock_before, stock_after


# ─── Item creation ────────────────────────────────────────────

def create_item(
    product_name: str,
    sku: str,
    initial_qty: int,
    category_id: str | None = None,
    price: float = 0.0,
) -> None:
    """สร้างสินค้าใหม่พร้อมตั้งสต็อกเริ่มต้น และ category (optional)"""
    store_id = _get_default_store_id()
    
    # Note: API create item ไม่รองรับการ set stock โดยตรงใน payload
    # เราต้องสร้าง item ก่อน แล้วค่อย update stock ทีหลัง
    
    # store_entry สำหรับกำหนดว่าสินค้านี้ขายที่ store ไหน (และราคา)
    # แต่ถ้าไม่ระบุ price, cost ก็ใส่แค่ store_id ได้ (หรือว่างไว้ก็ได้ถ้า default)
    store_entry: dict = {
        "store_id": store_id, 
    }
    if price > 0:
        store_entry["price"] = price
        store_entry["pricing_type"] = "FIXED"

    payload: dict = {
        "item_name": product_name,
        "track_stock": True,
        "variants": [{"sku": sku, "stores": [store_entry]}],
    }
    if category_id:
        payload["category_id"] = category_id

    res = _post("/items", payload)
    if res.status_code not in (200, 201):
        raise Exception(f"API Error {res.status_code}: {res.text}")
    
    # Extract variant_id from response to update stock
    try:
        data = res.json()
        variant_id = data["variants"][0]["variant_id"]
        
        if initial_qty > 0:
            print(f"📦 กำลังอัปเดตสต็อกเริ่มต้น ({initial_qty})...")
            update_stock(variant_id, initial_qty)
            
    except (KeyError, IndexError, Exception) as e:
        print(f"⚠️  สร้างสินค้าสำเร็จ แต่อัปเดตสต็อกไม่สำเร็จ: {e}")



def create_category(name: str) -> str:
    """สร้าง category ใหม่ คืน category_id"""
    payload = {"name": name, "color": "GREY"}  # Default color
    res = _post("/categories", payload)
    if res.status_code not in (200, 201):
        # ถ้า error ว่ามีอยู่แล้ว (409?) หรืออื่นๆ
        # แต่ปกติ API นี้ถ้า create ซ้ำอาจจะ error หรือ return เดิม
        # ถ้า error ลอง search หา id อีกรอบเผื่อ race condition
        cat_id = find_category_id(name)
        if cat_id:
            return cat_id
        raise Exception(f"Failed to create category '{name}': {res.text}")
    return res.json()["id"]


def build_item_display_name(category_name: str, product_name: str) -> str:
    """ชื่อสินค้าที่จะเก็บใน Loyverse — ให้ตรงกับ label บน barcode คือ '(category) name'"""
    if category_name:
        return f"({category_name}) {product_name}".strip()
    return product_name or ""


def ensure_item_exists(
    product_name: str,
    sku: str | None,
    category_name: str,
    price: float = 0.0
) -> tuple[str, str, float, str]:
    """
    ตรวจสอบว่าสินค้ามีอยู่แล้วหรือไม่ (ค้นหาจาก SKU หรือ ชื่อ+Category)
    ถ้าไม่มีจะสร้างใหม่โดยใช้ Auto SKU และสต็อกเริ่มต้นเป็น 0
    ชื่อสินค้าที่เก็บใน Loyverse จะมี '(category)' นำหน้า เหมือนกับ label บน barcode
    คืน (variant_id, sku, price, variant_name)
    """
    from loyverse import sku_generator

    # 1. หา category_id (ไม่สร้างใหม่ถ้าไม่พบ)
    cat_id = find_category_id(category_name)
    if not cat_id:
        raise CategoryNotFoundError(category_name)

    display_name = build_item_display_name(category_name, product_name)

    # 2. ค้นหาด้วย SKU (ถ้ามี)
    if sku:
        found = find_variant_by_sku(sku)
        if found:
            assert_price_matches(price, found[2])
            return found

    # 3. ค้นหาด้วยชื่อ + category
    found = find_variant_by_name(display_name, category_id=cat_id)
    if found:
        assert_price_matches(price, found[2])
        return found

    # 4. ถ้าไม่พบ ให้สร้างใหม่
    # หา prefix และ auto-increment SKU
    prefix = sku_generator.get_prefix_for_category(category_name)
    if not prefix:
        raise ValueError(f"ไม่พบ prefix สำหรับ category '{category_name}' ใน Mapping Sheet")

    last_sku = get_last_sku_in_category(cat_id, prefix)
    auto_sku = sku_generator.get_next_sku(prefix, last_sku)

    print(f"🆕 กำลังสร้างสินค้าใหม่: {display_name} (SKU: {auto_sku})")
    create_item(display_name, auto_sku, initial_qty=0, category_id=cat_id, price=price)
    
    # ค้นหาอีกรอบเพื่อเอา variant_id
    found = find_variant_by_sku(auto_sku)
    if not found:
        raise Exception(f"สร้างสินค้าสำเร็จแต่ค้นหาไม่พบ: {auto_sku}")
        
    return found

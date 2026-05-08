"""loyverse_api.py — Loyverse REST API wrapper"""

import re
import time
from functools import lru_cache

import requests

import config

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

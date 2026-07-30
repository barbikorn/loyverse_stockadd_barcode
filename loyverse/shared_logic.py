"""
shared_logic.py — Logic shared between step 1 and step 2
"""

from pathlib import Path
from loyverse import config
from loyverse.sheets import reader as sheets
from loyverse import loyverse_api as lv
from loyverse import barcode_gen


def get_missing_required_fields(row: dict, *, require_qty: bool = True) -> list[str]:
    """คืนรายชื่อ column ที่ว่าง (ตาม header ใน sheet)"""
    checks = [
        ("name", config.SHEET_COL_PRODUCT_NAME),
        ("type", config.SHEET_COL_TYPE),
        ("price_raw", config.SHEET_COL_PRICE),
    ]
    if require_qty:
        checks.insert(2, ("qty_raw", config.SHEET_COL_QTY))
    missing = []
    for key, label in checks:
        if sheets.is_cell_empty(row.get(key, "")):
            missing.append(label)
    return missing


def missing_fields_message(missing: list[str]) -> str:
    return f"Missing required fields: {', '.join(missing)}"


def apply_status_message(result: dict, status: str, message: str) -> dict:
    """ตั้ง Status + ข้อความเหตุผล (เขียนลงคอลัมน์ Message ใน Sheet)"""
    result["Status"] = status
    result["Detail/Error"] = message
    result["Message"] = message
    return result


def sheet_message(result: dict) -> str:
    """ข้อความที่เขียนลงคอลัมน์ Message"""
    if result["Status"] in ("OUT", "Error"):
        return result.get("Message") or result.get("Detail/Error") or ""
    return result.get("Message") or result.get("Action") or ""


def to_transaction_record(row: dict, result: dict, *, include_qty: bool = True) -> dict:
    """แปลง row + ผลประมวลผล → รูปแบบที่ sheets_writer ใช้"""
    sku = result.get("SKU") or row.get("sku", "") or "-"
    record = {
        "Product Name": row.get("product_name", ""),
        "SKU": sku,
        "Category": row.get("category", ""),
        "Stock Before": result.get("Stock Before", "-"),
        "Stock After": result.get("Stock After", "-"),
        "Action": result.get("Action", ""),
        "Status": result.get("Status", ""),
        "Detail/Error": result.get("Detail/Error") or result.get("Message", ""),
    }
    if include_qty:
        record["Quantity Added"] = row.get("total_number", "")
    return record


def process_row_step1(row: dict, barcode_dir: Path) -> dict:
    """
    Step 1: Ensure item exists in Loyverse (stock 0) and generate barcode
    """
    p_name = row["product_name"]
    p_sku = row["sku"]
    p_cat = row.get("category", "")
    p_price = row.get("price", 0.0)
    
    result = {
        "Status": "Success",
        "Action": "",
        "SKU": p_sku or "-",
        "Barcode File": "-",
        "Detail/Error": "",
        "Message": "",
    }

    missing = get_missing_required_fields(row, require_qty=False)
    if missing:
        return apply_status_message(result, "OUT", missing_fields_message(missing))

    if not lv.find_category_id(p_cat):
        return apply_status_message(
            result,
            "OUT",
            f"Category '{p_cat}' (ชื่อไฟล์ Google Sheet) not found in Loyverse",
        )

    try:
        # Ensure item exists (stock 0 if new)
        variant_id, found_sku, f_price, f_var = lv.ensure_item_exists(
            product_name=p_name,
            sku=p_sku if p_sku else None,
            category_name=p_cat,
            price=p_price
        )
        
        result["SKU"] = found_sku
        result["Action"] = "Item Ready (Stock 0)"
        
        # Generate barcode
        barcode_file = barcode_gen.generate(
            sku=found_sku,
            output_dir=barcode_dir,
            product_name=p_name,
            price=f_price or p_price,
            variant_name=f_var,
            category=p_cat,
        )
        result["Barcode File"] = barcode_file or "-"
        
    except lv.CategoryNotFoundError as e:
        apply_status_message(result, "OUT", str(e))
    except lv.PriceMismatchError as e:
        apply_status_message(result, "OUT", str(e))
    except Exception as e:
        apply_status_message(result, "Error", str(e))

    return result

def process_row_step2(row: dict) -> dict:
    """
    Step 2: Update stock in Loyverse
    """
    p_name = row["product_name"]
    p_sku = row["sku"]
    add_qty = row["total_number"]
    p_price = row.get("price", 0.0)

    result = {
        "Status": "Success",
        "Action": "",
        "Stock Before": "-",
        "Stock After": "-",
        "Detail/Error": "",
        "Message": "",
    }

    missing = get_missing_required_fields(row)
    if missing:
        return apply_status_message(result, "OUT", missing_fields_message(missing))

    if not p_sku:
        return apply_status_message(result, "Error", "Missing SKU (Run Step 1 first)")

    if add_qty <= 0:
        return apply_status_message(result, "Error", "Quantity must be greater than 0")

    try:
        # Find variant by SKU
        found = lv.find_variant_by_sku(p_sku)
        if not found:
            raise ValueError(f"SKU '{p_sku}' not found in Loyverse")

        variant_id, _, f_price, _ = found
        lv.assert_price_matches(p_price, f_price)

        # Update stock
        before, after = lv.update_stock(variant_id, add_qty)
        result["Stock Before"] = before
        result["Stock After"] = after
        result["Action"] = f"Stock Updated (+{add_qty})"

    except lv.PriceMismatchError as e:
        apply_status_message(result, "OUT", str(e))
    except Exception as e:
        apply_status_message(result, "Error", str(e))

    return result

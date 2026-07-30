"""
loyverse_sync.py — Main pipeline
  1. อ่าน input จาก Input Sheet (Private, via gspread)
  2. ต่อแถว:
     a. ถ้าพบสินค้าแล้ว (SKU หรือชื่อ) → update stock
     b. ถ้าไม่พบ (NEW ITEM):
        - ตรวจ category column
        - ค้นหา category ใน Loyverse (ถ้าไม่มี → Status OUT)
        - ค้นหา prefix จาก Mapping Sheet
        - auto-increment SKU
        - สร้างสินค้าใหม่พร้อม category
  3. Generate barcode PNG
  4. Export รายงาน Excel (local)
  5. Write results → Transaction Sheet
"""

from datetime import datetime
from pathlib import Path

import pandas as pd

from loyverse import config
from loyverse.sheets import reader as sheets
from loyverse import loyverse_api as lv
from loyverse import barcode_gen
from loyverse import sku_generator
from loyverse.sheets import writer as sheets_writer
from loyverse import shared_logic


# ─── Per-row processing ───────────────────────────────────────

def _process_row(row: dict, barcode_dir: Path) -> dict:
    p_name   = row["product_name"]
    p_sku    = row["sku"]
    add_qty  = row["total_number"]
    p_cat    = row.get("category", "")
    p_price  = row.get("price", 0.0)
    p_var    = row.get("variant", "")

    result = {
        "Product Name":   p_name,
        "SKU":            p_sku or "-",
        "Category":       p_cat or "-",
        "Quantity Added": add_qty,
        "Stock Before":   "-",
        "Stock After":    "-",
        "Status":         "Success",
        "Action":         "",
        "Barcode File":   "-",
        "Detail/Error":   "",
    }

    # ── 0. Validate required fields ───────────────────────────
    missing = shared_logic.get_missing_required_fields(row)
    if missing:
        result["Status"] = "OUT"
        result["Detail/Error"] = shared_logic.missing_fields_message(missing)
        icon = "⚠️"
        print(f"{icon} {p_name or '(no name)'} | SKU: {result['SKU']} | {result['Detail/Error']}")
        return result

    try:
        variant_id = None
        f_price    = 0.0
        f_var      = ""
        current_price    = p_price
        current_var_name = p_var

        # ── 1. หา category_id จากชื่อ category ───────────────
        cat_id = lv.find_category_id(p_cat)

        # ── 2. ค้นหาด้วย SKU ก่อน (ถ้ามี) ────────────────────
        if p_sku:
            found = lv.find_variant_by_sku(p_sku)
            if found:
                variant_id, found_sku, f_price, f_var = found
                result["SKU"] = found_sku
                result["Action"] = "Update Stock (Found by SKU)"

        # ── 3. ค้นหาด้วยชื่อ + category ──────────────────────
        if not variant_id:
            found = lv.find_variant_by_name(p_name, category_id=cat_id)
            if found:
                variant_id, found_sku, f_price, f_var = found
                result["SKU"] = found_sku
                result["Action"] = "Update Stock (Found by Name+Category)"

        # ── 4. Price mismatch check ────────────────────────────
        if variant_id:
            lv.assert_price_matches(p_price, f_price)

        # ── 5. ตั้งค่าราคา/variant สำหรับ barcode ────────────
        if not current_price and f_price > 0:
            current_price = f_price
        if not current_var_name and f_var:
            current_var_name = f_var

        # ── 6. อัปเดตสต็อกสินค้าที่มีอยู่แล้ว ─────────────────
        if variant_id:
            before, after = lv.update_stock(variant_id, add_qty)
            result["Stock Before"] = before
            result["Stock After"]  = after

        else:
            # ── 7. NEW ITEM flow ───────────────────────────────

            # 7a. ตรวจว่า category มีใน Loyverse ไหม (ไม่สร้างใหม่)
            if cat_id is None:
                result["Status"] = "OUT"
                result["Detail/Error"] = f"Category '{p_cat}' not found in Loyverse"
                icon = "⚠️"
                print(f"{icon} {p_name} | SKU: {result['SKU']} | {result['Detail/Error']}")
                return result

            result["Category"] = p_cat

            # 7b. ค้นหา prefix จาก Mapping Sheet
            prefix = sku_generator.get_prefix_for_category(p_cat)
            if prefix is None:
                raise ValueError(
                    f"ไม่พบ prefix สำหรับ category '{p_cat}' ใน Mapping Sheet"
                )

            # 7c. หา SKU ล่าสุดใน category → auto-increment
            last_sku = lv.get_last_sku_in_category(cat_id, prefix)
            auto_sku = sku_generator.get_next_sku(prefix, last_sku)
            result["SKU"] = auto_sku

            # 7d. สร้างสินค้าใหม่
            lv.create_item(p_name, auto_sku, add_qty, category_id=cat_id, price=p_price)
            result["Action"]       = f"Created New Item (Auto SKU: {auto_sku})"
            result["Stock Before"] = 0
            result["Stock After"]  = add_qty
            current_price = p_price

        # ── 8. Generate barcode ────────────────────────────────
        sku_for_barcode = result.get("SKU", "")
        if sku_for_barcode and sku_for_barcode != "-":
            result["Barcode File"] = barcode_gen.generate(
                sku=sku_for_barcode,
                output_dir=barcode_dir,
                product_name=p_name,
                price=current_price,
                variant_name=current_var_name
            ) or "-"

    except Exception as e:
        result["Status"]       = "Error"
        result["Detail/Error"] = str(e)

    icon = "✅" if result["Status"] == "Success" else ("⚠️" if result["Status"] == "OUT" else "❌")
    msg = result["Detail/Error"] if result["Status"] in ("Error", "OUT") else (result["Action"] or result["Detail/Error"])
    print(f"{icon} {p_name} | SKU: {result['SKU']} | {msg}")
    return result


# ─── Main pipeline ────────────────────────────────────────────

def run() -> None:
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(config.OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    file_name, input_data = sheets.fetch_input_records()
    barcode_dir = config.get_barcode_output_dir(file_name)
    col_cache: dict[int, dict[str, int]] = {}

    print(f"📁 โฟลเดอร์ barcode: {barcode_dir.resolve()}\n")

    report = []
    for ws, row_idx, row in input_data:
        ws_id = id(ws)
        if ws_id not in col_cache:
            col_cache[ws_id] = sheets.get_output_column_indices(ws)
        cols = col_cache[ws_id]

        if row.get("status") == "Success":
            print(f"⏩ ข้าม {row['product_name']} (Status: Success)")
            continue

        result = _process_row(row, barcode_dir)
        report.append(result)

        sheets.update_row_status(
            ws,
            row_idx,
            cols["status"],
            cols["message"],
            result["Status"],
            result["Detail/Error"] or result["Action"],
        )

    # ── Export local Excel ─────────────────────────────────────
    if report and config.ENABLE_LOCAL_REPORT:
        report_path = output_dir / f"{config.REPORT_FILENAME_PREFIX}_{timestamp}.xlsx"
        pd.DataFrame(report).to_excel(str(report_path), index=False)
        print(f"\n📊 รายงาน Excel : {Path(report_path).resolve()}")
    elif not report:
        print("\n⚠️  ไม่มีรายการใหม่ที่ต้องประมวลผล")

    print(f"🖼️  Barcode PNG  : {barcode_dir.resolve()}")

    # ── Write results → Transaction Sheet ─────────────────────
    if report:
        sheets_writer.write_results(report, timestamp)

    # ── Summary ───────────────────────────────────────────────
    success = sum(1 for r in report if r["Status"] == "Success")
    error   = len(report) - success
    print(f"\n{'─'*50}")
    print(f"✅ สำเร็จ: {success} รายการ  |  ❌ Error: {error} รายการ")
    print(f"{'─'*50}")


# ─── Entry point ──────────────────────────────────────────────
if __name__ == "__main__":
    run()

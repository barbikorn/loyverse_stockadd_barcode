"""sheets_writer.py — Write sync results (CSV mode or Google Sheets mode)

TRANSACTION_OUTPUT_MODE=csv    → append to local CSV file (no credentials.json needed)
TRANSACTION_OUTPUT_MODE=sheets → append to Google Sheet (requires credentials.json)
"""

import csv
import os
from datetime import datetime
from pathlib import Path

from loyverse import config

_HEADERS = [
    "Timestamp",
    "Product Name",
    "SKU",
    "Category",
    "Quantity Added",
    "Stock Before",
    "Stock After",
    "Action",
    "Status",
    "Detail/Error",
]


def _ts_str(timestamp: str) -> str:
    try:
        dt = datetime.strptime(timestamp, "%Y%m%d_%H%M%S")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return timestamp


def _build_rows(records: list[dict], timestamp: str) -> list[list]:
    ts = _ts_str(timestamp)
    return [[
        ts,
        r.get("Product Name", ""),
        r.get("SKU", ""),
        r.get("Category", ""),
        r.get("Quantity Added", ""),
        r.get("Stock Before", ""),
        r.get("Stock After", ""),
        r.get("Action", ""),
        r.get("Status", ""),
        r.get("Detail/Error", ""),
    ] for r in records]


# ─── CSV writer ───────────────────────────────────────────────

def _write_csv(records: list[dict], timestamp: str) -> None:
    csv_path = Path(config.TRANSACTION_CSV_PATH)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    file_exists = csv_path.exists()
    rows = _build_rows(records, timestamp)

    with open(csv_path, mode="a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(_HEADERS)   # header เฉพาะครั้งแรก
        writer.writerows(rows)

    print(f"📄 Transaction CSV : {csv_path.resolve()} (+{len(rows)} rows)")


# ─── Google Sheets writer ─────────────────────────────────────

def _write_sheets(records: list[dict], timestamp: str) -> None:
    from loyverse.sheets import auth as sheets_auth

    if not config.TRANSACTION_SHEET_URL:
        print("⚠️  TRANSACTION_SHEET_URL ไม่ได้ตั้งค่า — ข้าม write-back")
        return

    print("📝 กำลังเขียนผลลัพธ์ลง Transaction Sheet...")
    try:
        ss = sheets_auth.open_sheet_by_url(config.TRANSACTION_SHEET_URL)
        try:
            ws = ss.worksheet(config.TRANSACTION_SHEET_NAME)
        except Exception:
            ws = ss.add_worksheet(
                title=config.TRANSACTION_SHEET_NAME,
                rows=1000, cols=len(_HEADERS)
            )
            ws.append_row(_HEADERS, value_input_option="RAW")

        existing = ws.get_all_values()
        if not existing or existing[0] != _HEADERS:
            ws.insert_row(_HEADERS, index=1, value_input_option="RAW")

        rows = _build_rows(records, timestamp)
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        print(f"✅ เขียน {len(rows)} แถว → {config.TRANSACTION_SHEET_NAME}")
    except Exception as e:
        print(f"⚠️  เขียนลง Transaction Sheet ไม่สำเร็จ: {repr(e)}")
        
        # Try to suggest solution with email
        try:
            import json
            with open(config.GOOGLE_CREDENTIALS_FILE) as f:
                email = json.load(f).get("client_email")
            print(f"   👉 สาเหตุอาจเกิดจากยังไม่ได้แชร์ Sheet ให้กับ Service Account")
            print(f"   👉 กรุณากด Share (Editor) ให้กับอีเมล: {email}")
        except:
            pass

        print("   (หรือลองเปลี่ยนเป็น TRANSACTION_OUTPUT_MODE=csv ถ้าไม่มี credentials.json)")


# ─── Public entry point ───────────────────────────────────────

def write_results(records: list[dict], timestamp: str) -> None:
    """
    เขียนผลลัพธ์ตาม TRANSACTION_OUTPUT_MODE:
      'csv'    → output/transactions.csv  (ไม่ต้อง credentials)
      'sheets' → Google Sheet             (ต้อง credentials.json)
    """
    if not records:
        return

    mode = config.TRANSACTION_OUTPUT_MODE
    if mode == "csv":
        _write_csv(records, timestamp)
    elif mode == "sheets":
        _write_sheets(records, timestamp)
    else:
        print(f"⚠️  TRANSACTION_OUTPUT_MODE='{mode}' ไม่รู้จัก (ใช้ 'csv' หรือ 'sheets')")
        _write_csv(records, timestamp)   # fallback to csv

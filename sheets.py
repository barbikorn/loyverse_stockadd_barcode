"""sheets.py — Google Sheets reader (Private via gspread Service Account)"""

import config
import sheets_auth


def _parse_row(row: dict) -> dict | None:
    """แปลง dict row จาก gspread → dict ที่ใช้งานได้ หรือ None ถ้าไม่ valid"""
    name = str(row.get(config.SHEET_COL_PRODUCT_NAME, "")).strip()
    if not name or name.lower() == "nan":
        return None

    sku = str(row.get(config.SHEET_COL_SKU, "")).strip()
    if sku.lower() in ("nan", "none", ""):
        sku = ""

    try:
        qty = int(float(str(row.get(config.SHEET_COL_QTY, 0))))
    except (ValueError, TypeError):
        qty = 0

    category = str(row.get(config.SHEET_COL_CATEGORY, "")).strip()
    if category.lower() in ("nan", "none"):
        category = ""

    try:
        price_str = str(row.get(config.SHEET_COL_PRICE, 0)).replace(",", "")
        price = float(price_str)
    except (ValueError, TypeError):
        price = 0.0

    status = str(row.get(config.SHEET_COL_STATUS, "")).strip()

    return {
        "product_name": name,
        "sku": sku,
        "total_number": qty,
        "category": category,
        "price": price,
        "status": status,
    }


def get_or_create_col_index(ws, col_name: str) -> int:
    """คืน index (1-based) ของ column name ถ้าไม่มีจะสร้างเพิ่ม"""
    # อ่าน header row (row 1)
    headers = ws.row_values(1)
    if col_name in headers:
        return headers.index(col_name) + 1
    
    # ถ้าไม่มี ให้เพิ่มต่อท้าย
    new_col_idx = len(headers) + 1
    ws.update_cell(1, new_col_idx, col_name)
    return new_col_idx


def update_row_status(ws, row_idx: int, status_col_idx: int, msg_col_idx: int, status: str, message: str):
    """อัปเดตสถานะกลับไปที่ Input Sheet"""
    ws.update_cell(row_idx, status_col_idx, status)
    ws.update_cell(row_idx, msg_col_idx, message)


def fetch_input_records(url: str = config.INPUT_SHEET_URL):
    """
    ดึงข้อมูลทุกแถวจาก Input Sheet (Private)
    คืน (worksheet, list[(row_index, parsed_dict)])
    """
    print("📋 กำลังอ่านข้อมูลจาก Input Sheet (gspread)...")

    ss = sheets_auth.open_sheet_by_url(url)
    ws = ss.get_worksheet(0)
    
    # ใช้ get_all_values เพื่อให้ได้ row index ที่แน่นอน
    all_values = ws.get_all_values()
    if not all_values:
        return ws, []
        
    headers = all_values[0]
    
    # ตรวจสอบ required columns
    required = [config.SHEET_COL_PRODUCT_NAME, config.SHEET_COL_QTY]
    missing = [c for c in required if c not in headers]
    if missing:
        raise ValueError(f"ไม่พบ column: {missing}\nHeaders: {headers}")

    col_map = {name: idx for idx, name in enumerate(headers)}
    
    records = []
    # Start from row 2 (index 1 in 0-based list, index 2 in 1-based sheet)
    for i, row_values in enumerate(all_values[1:], start=2):
        row_dict = {}
        for col_name, col_idx in col_map.items():
            val = row_values[col_idx] if col_idx < len(row_values) else ""
            row_dict[col_name] = val
            
        parsed = _parse_row(row_dict)
        if parsed:
            records.append((i, parsed))
            
    print(f"✅ อ่านข้อมูลสำเร็จ: {len(records)} รายการ")
    return ws, records

"""sheets.py — Google Sheets reader (Private via gspread Service Account)"""

from loyverse import config
from loyverse.sheets import auth as sheets_auth


def is_cell_empty(val) -> bool:
    s = str(val).strip()
    return not s or s.lower() in ("nan", "none")


def build_product_name(name: str, product_type: str = "") -> str:
    """รวมชื่อสินค้าเป็น type.name เมื่อมี type (เช่น postcard.Memonote)"""
    name = name.strip()
    product_type = product_type.strip()
    if not name or name.lower() == "nan":
        return ""
    if product_type and product_type.lower() not in ("nan", "none"):
        return f"{product_type}.{name}"
    return name


def _parse_row(row: dict, category: str, sheet_tab: str = "") -> dict | None:
    """แปลง dict row จาก gspread → dict ที่ใช้งานได้ หรือ None ถ้าแถวว่างทั้งหมด"""
    name = str(row.get(config.SHEET_COL_PRODUCT_NAME, "")).strip()
    if is_cell_empty(name):
        name = ""

    product_type = str(row.get(config.SHEET_COL_TYPE, "")).strip()
    if is_cell_empty(product_type):
        product_type = ""

    qty_raw = str(row.get(config.SHEET_COL_QTY, "")).strip()
    price_raw = str(row.get(config.SHEET_COL_PRICE, "")).strip()

    sku = str(row.get(config.SHEET_COL_SKU, "")).strip()
    if is_cell_empty(sku):
        sku = ""

    if all(is_cell_empty(v) for v in [name, product_type, qty_raw, price_raw, sku]):
        return None

    full_name = build_product_name(name, product_type) if name else ""

    try:
        qty = int(float(qty_raw)) if not is_cell_empty(qty_raw) else 0
    except (ValueError, TypeError):
        qty = 0

    try:
        price = float(price_raw.replace(",", "")) if not is_cell_empty(price_raw) else 0.0
    except (ValueError, TypeError):
        price = 0.0

    status = str(row.get(config.SHEET_COL_STATUS, "")).strip()
    state = str(row.get(config.SHEET_COL_STATE, "")).strip()

    return {
        "name": name,
        "product_name": full_name,
        "type": product_type,
        "sku": sku,
        "total_number": qty,
        "qty_raw": qty_raw,
        "category": category,
        "file_name": category,
        "sheet_tab": sheet_tab,
        "price": price,
        "price_raw": price_raw,
        "status": status,
        "state": state,
    }


def get_or_create_col_index(ws, col_name: str) -> int:
    """คืน index (1-based) ของ column name ถ้าไม่มีจะสร้างเพิ่ม"""
    headers = ws.row_values(1)
    if col_name in headers:
        return headers.index(col_name) + 1

    new_col_idx = len(headers) + 1
    ws.update_cell(1, new_col_idx, col_name)
    return new_col_idx


def get_output_column_indices(ws) -> dict[str, int]:
    """คอลัมน์ที่ step scripts ใช้เขียนผลกลับไปที่ชีต"""
    return {
        "status": get_or_create_col_index(ws, config.SHEET_COL_STATUS),
        "message": get_or_create_col_index(ws, config.SHEET_COL_MESSAGE),
        "state": get_or_create_col_index(ws, config.SHEET_COL_STATE),
        "sku": get_or_create_col_index(ws, config.SHEET_COL_SKU),
    }


def update_row_status(ws, row_idx: int, status_col_idx: int, msg_col_idx: int, status: str, message: str):
    """อัปเดตสถานะกลับไปที่ Input Sheet"""
    ws.update_cell(row_idx, status_col_idx, status)
    ws.update_cell(row_idx, msg_col_idx, message)


def update_row_state(ws, row_idx: int, state_col_idx: int, state: str):
    """อัปเดต Process_State กลับไปที่ Input Sheet"""
    ws.update_cell(row_idx, state_col_idx, state)


def update_row_sku(ws, row_idx: int, sku_col_idx: int, sku: str):
    """อัปเดต SKU กลับไปที่ Input Sheet"""
    ws.update_cell(row_idx, sku_col_idx, sku)


def _read_worksheet(ws, category: str, sheet_tab: str) -> list[tuple[int, dict]]:
    """อ่านแถวจาก worksheet เดียว คืน list[(row_index, parsed_dict)]"""
    all_values = ws.get_all_values()
    if not all_values:
        return []

    headers = all_values[0]
    required = [
        config.SHEET_COL_PRODUCT_NAME,
        config.SHEET_COL_TYPE,
        config.SHEET_COL_PRICE,
    ]
    missing = [c for c in required if c not in headers]
    if missing:
        raise ValueError(
            f"แท็บ '{ws.title}' ไม่พบ column: {missing}\nHeaders: {headers}"
        )

    col_map = {name: idx for idx, name in enumerate(headers)}
    records = []
    for i, row_values in enumerate(all_values[1:], start=2):
        row_dict = {}
        for col_name, col_idx in col_map.items():
            val = row_values[col_idx] if col_idx < len(row_values) else ""
            row_dict[col_name] = val

        parsed = _parse_row(row_dict, category, sheet_tab=sheet_tab)
        if parsed:
            records.append((i, parsed))

    return records


def fetch_input_records(url: str = config.INPUT_SHEET_URL) -> tuple[str, list[tuple]]:
    """
    ดึงข้อมูลจาก Input Spreadsheet
    ชื่อไฟล์ Google Sheet (ss.title) = category ใน Loyverse
    คืน (file_name, list[(worksheet, row_index, parsed_dict)])
    """
    print("📋 กำลังอ่านข้อมูลจาก Input Sheet (gspread)...")

    ss = sheets_auth.open_sheet_by_url(url)
    category = ss.title.strip()
    if not category:
        raise ValueError(
            "ชื่อ Google Sheet ว่าง — ตั้งชื่อไฟล์ให้ตรงกับ category ใน Loyverse"
        )
    print(f"📁 ไฟล์ '{category}' → category ใน Loyverse")

    if config.INPUT_SHEET_TAB:
        worksheets = [ss.worksheet(config.INPUT_SHEET_TAB)]
    else:
        worksheets = ss.worksheets()

    all_records: list[tuple] = []
    for ws in worksheets:
        tab_records = _read_worksheet(ws, category, sheet_tab=ws.title)
        for row_idx, parsed in tab_records:
            all_records.append((ws, row_idx, parsed))
        if tab_records:
            print(f"  📄 แท็บ '{ws.title}': {len(tab_records)} รายการ")

    print(f"✅ อ่านข้อมูลสำเร็จ: {len(all_records)} รายการรวม")
    return category, all_records

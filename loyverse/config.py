# ==============================================================
#  config.py — Loads settings from .env file
#  This is the ONLY place that reads from .env.
#  All other modules import from here instead of calling os.getenv() directly.
# ==============================================================

import os
import re
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Project root is one level up from this package: <root>/loyverse/config.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(f"Missing required env var: '{key}' — check your .env file")
    return val


# ─── Loyverse API ──────────────────────────────────────────────
LOYVERSE_TOKEN    = _require("LOYVERSE_TOKEN")
LOYVERSE_STORE_ID = os.getenv("LOYVERSE_STORE_ID", "")       # optional
LOYVERSE_API_BASE = os.getenv("LOYVERSE_API_BASE", "https://api.loyverse.com/v1.0")

# ─── Google Sheets ─────────────────────────────────────────────
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

# optional — the Web UI supplies this per-run; used as a fallback/default for the CLI
INPUT_SHEET_URL  = os.getenv("INPUT_SHEET_URL", "")
# ว่าง = อ่านทุกแท็บ | ระบุชื่อ = อ่านแท็บเดียว (category = ชื่อไฟล์ Google Sheet)
INPUT_SHEET_TAB    = os.getenv("INPUT_SHEET_TAB", "").strip()
MAPPING_SHEET_URL  = _require("MAPPING_SHEET_URL")
MAPPING_SHEET_NAME = os.getenv("MAPPING_SHEET_NAME", "Mapping")

# Transaction output: "csv" (default, no credentials needed) or "sheets"
TRANSACTION_OUTPUT_MODE = os.getenv("TRANSACTION_OUTPUT_MODE", "csv").lower()
TRANSACTION_CSV_PATH    = os.getenv("TRANSACTION_CSV_PATH", "output/transactions.csv")
TRANSACTION_SHEET_URL   = os.getenv("TRANSACTION_SHEET_URL", "")
TRANSACTION_SHEET_NAME  = os.getenv("TRANSACTION_SHEET_NAME", "Transactions")

# ─── Sheet column names ────────────────────────────────────────
SHEET_COL_PRODUCT_NAME = os.getenv("SHEET_COL_PRODUCT_NAME", "product_name")
SHEET_COL_TYPE         = os.getenv("SHEET_COL_TYPE",         "type")
SHEET_COL_SKU          = os.getenv("SHEET_COL_SKU",          "sku")
SHEET_COL_QTY          = os.getenv("SHEET_COL_QTY",          "total_number")
SHEET_COL_PRICE        = os.getenv("SHEET_COL_PRICE",        "Price")
SHEET_COL_STATUS       = os.getenv("SHEET_COL_STATUS",       "Status")
SHEET_COL_MESSAGE      = os.getenv("SHEET_COL_MESSAGE",      "Message")
SHEET_COL_STATE        = os.getenv("SHEET_COL_STATE",        "Process_State")

# ─── SKU format ────────────────────────────────────────────────
SKU_DIGIT_PAD = int(os.getenv("SKU_DIGIT_PAD", "3"))   # e.g. 3 → MM001

# ─── Output paths ──────────────────────────────────────────────
OUTPUT_DIR                = os.getenv("OUTPUT_DIR",                "output")
BARCODE_OUTPUT_DIR_PREFIX = os.getenv("BARCODE_OUTPUT_DIR_PREFIX", "barcodes")
REPORT_FILENAME_PREFIX    = os.getenv("REPORT_FILENAME_PREFIX",    "loyverse_sync_report")
ENABLE_LOCAL_REPORT       = os.getenv("ENABLE_LOCAL_REPORT",       "true").lower() == "true"


def _safe_dir_name(name: str) -> str:
    """ชื่อโฟลเดอร์ที่ปลอดภัยสำหรับ Windows/macOS/Linux"""
    safe = re.sub(r'[\\/*?:"<>|]', "_", str(name)).strip()
    return safe or "unknown"


def get_barcode_output_dir(file_name: str) -> Path:
    """โฟลเดอร์ barcode: output/{YYYYMMDD}/{ชื่อไฟล์ Google Sheet}/"""
    date_str = datetime.now().strftime("%Y%m%d")
    barcode_dir = Path(OUTPUT_DIR) / date_str / _safe_dir_name(file_name)
    barcode_dir.mkdir(parents=True, exist_ok=True)
    return barcode_dir

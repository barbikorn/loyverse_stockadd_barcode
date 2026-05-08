"""sheets_auth.py — Google Sheets Service Account authentication (gspread)"""

from functools import lru_cache
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

import config

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


@lru_cache(maxsize=1)
def get_client() -> gspread.Client:
    """คืน authorized gspread Client (cache ครั้งแรกเท่านั้น)"""
    creds_path = Path(config.GOOGLE_CREDENTIALS_FILE)
    if not creds_path.exists():
        raise FileNotFoundError(
            f"❌ ไม่พบ '{creds_path}' — กรุณาดาวน์โหลด credentials.json จาก Google Cloud Console\n"
            "   แล้ว Share Sheets ทั้งหมดให้ service account email"
        )
    creds = Credentials.from_service_account_file(str(creds_path), scopes=_SCOPES)
    return gspread.authorize(creds)


def open_sheet_by_url(url: str) -> gspread.Spreadsheet:
    """เปิด Spreadsheet จาก URL"""
    return get_client().open_by_url(url)

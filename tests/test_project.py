"""
test_project.py -- Test suite for the loyverse package
Run from project root:  python tests/test_project.py
Tests run without real Google Sheets or Loyverse API credentials.
"""
import sys
import os
import tempfile
import inspect
import py_compile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Make the project root importable regardless of where this is run from.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PASS = "[PASS]"
FAIL = "[FAIL]"
results = []


def test(name, fn):
    try:
        fn()
        results.append((PASS, name))
        print(f"  {PASS}  {name}")
    except Exception as e:
        results.append((FAIL, name))
        print(f"  {FAIL}  {name}")
        print(f"       -> {e}")


def _reset(*modules):
    """Remove cached modules to force fresh reload"""
    for m in modules:
        sys.modules.pop(m, None)


# Base env — only truly required keys (STORE_ID is now optional)
BASE_ENV = {
    "LOYVERSE_TOKEN":          "TEST_TOKEN",
    "INPUT_SHEET_URL":         "https://docs.google.com/spreadsheets/d/FAKE_IN/edit",
    "MAPPING_SHEET_URL":       "https://docs.google.com/spreadsheets/d/FAKE_MAP/edit",
    "TRANSACTION_OUTPUT_MODE": "csv",
    "TRANSACTION_CSV_PATH":    "output/transactions_test.csv",
}


def full_env(**extra) -> dict:
    """Merge BASE_ENV with any extra overrides for inner patches"""
    return {**BASE_ENV, **extra}


# ─── 0. Syntax Check ──────────────────────────────────────────
print("\n=== [0] Syntax Check ===")
py_files = [
    "loyverse/config.py",
    "loyverse/loyverse_api.py",
    "loyverse/barcode_gen.py",
    "loyverse/sku_generator.py",
    "loyverse/shared_logic.py",
    "loyverse/sheets/auth.py",
    "loyverse/sheets/reader.py",
    "loyverse/sheets/writer.py",
    "loyverse/steps/step1_barcode_gen.py",
    "loyverse/steps/step2_stock_update.py",
    "loyverse/steps/legacy_sync.py",
    "loyverse/web/app.py",
]
for f in py_files:
    def _check(f=f):
        py_compile.compile(str(ROOT / f), doraise=True)
    test(f"Syntax: {f}", _check)


# ─── 1. Config ────────────────────────────────────────────────
print("\n=== [1] Config ===")

def _load_config():
    _reset("loyverse.config")
    with patch.dict(os.environ, BASE_ENV):
        from loyverse import config
        assert config.LOYVERSE_TOKEN == "TEST_TOKEN"
        assert config.LOYVERSE_STORE_ID == ""   # optional — default empty
        assert config.SKU_DIGIT_PAD == 3
        assert config.OUTPUT_DIR == "output"
        assert config.TRANSACTION_OUTPUT_MODE == "csv"
        assert config.TRANSACTION_SHEET_NAME == "Transactions"
        assert config.MAPPING_SHEET_NAME == "Mapping"
test("config: loads all values, STORE_ID optional (defaults '')", _load_config)

def _store_id_optional():
    """Running without LOYVERSE_STORE_ID must NOT raise"""
    _reset("loyverse.config")
    env_no_store = {k: v for k, v in BASE_ENV.items() if k != "LOYVERSE_STORE_ID"}
    with patch.dict(os.environ, env_no_store, clear=True):
        from loyverse import config
        assert config.LOYVERSE_STORE_ID == ""
test("config: LOYVERSE_STORE_ID is optional (no EnvironmentError)", _store_id_optional)

def _missing_token():
    """_require() must raise EnvironmentError when key is absent."""
    _reset("loyverse.config")
    original_getenv = os.getenv
    def fake_getenv(key, default=None):
        if key == "LOYVERSE_TOKEN":
            return None   # simulate missing
        return original_getenv(key, default)
    with patch("os.getenv", side_effect=fake_getenv):
        token_backup = os.environ.pop("LOYVERSE_TOKEN", None)
        try:
            from loyverse import config  # noqa: F401
            raise AssertionError("Should have raised EnvironmentError")
        except EnvironmentError as e:
            assert "LOYVERSE_TOKEN" in str(e)
        finally:
            _reset("loyverse.config")
            if token_backup:
                os.environ["LOYVERSE_TOKEN"] = token_backup
test("config: raises EnvironmentError when LOYVERSE_TOKEN missing", _missing_token)


# ─── 2. SKU Generator ─────────────────────────────────────────
print("\n=== [2] SKU Generator (pure logic) ===")

_reset("loyverse.config", "loyverse.sku_generator", "loyverse.sheets.auth")
sys.modules["loyverse.sheets.auth"] = MagicMock()
with patch.dict(os.environ, BASE_ENV):
    from loyverse import config
    from loyverse import sku_generator

def _first_item():
    assert sku_generator.get_next_sku("MM", None) == "MM001"
test("get_next_sku: first item (None) -> MM001", _first_item)

def _increment():
    assert sku_generator.get_next_sku("MM", "MM005") == "MM006"
test("get_next_sku: MM005 -> MM006", _increment)

def _fd_prefix():
    assert sku_generator.get_next_sku("FD", "FD099") == "FD100"
test("get_next_sku: FD099 -> FD100", _fd_prefix)

def _three_digit_pad():
    result = sku_generator.get_next_sku("AB", None)
    assert result == "AB001", f"Expected AB001, got '{result}'"
test("get_next_sku: 3-digit zero-pad enforced", _three_digit_pad)

def _extract_num():
    assert sku_generator._extract_number("MM042", "MM") == 42
test("_extract_number: MM042 -> 42", _extract_num)

def _extract_none():
    assert sku_generator._extract_number("FD001", "MM") is None
test("_extract_number: FD001 with prefix MM -> None (no match)", _extract_none)

def _extract_case():
    assert sku_generator._extract_number("mm010", "MM") == 10
test("_extract_number: case-insensitive (mm010 matches MM) -> 10", _extract_case)


# ─── 3. Sheets Auth ───────────────────────────────────────────
print("\n=== [3] Sheets Auth ===")

_reset("loyverse.sheets.auth", "loyverse.config")
with patch.dict(os.environ, BASE_ENV):
    from loyverse import config as _cfg  # noqa: F401

def _no_creds():
    _reset("loyverse.sheets.auth")
    from loyverse.sheets import auth as sheets_auth
    sheets_auth.get_client.cache_clear()
    try:
        sheets_auth.get_client()
        raise AssertionError("Should have raised FileNotFoundError")
    except FileNotFoundError as e:
        assert "credentials" in str(e).lower() or "ไม่พบ" in str(e)
test("sheets.auth: FileNotFoundError when credentials.json absent", _no_creds)


# ─── 4. Barcode Generator ─────────────────────────────────────
print("\n=== [4] Barcode Generator ===")

_reset("loyverse.barcode_gen")
from loyverse import barcode_gen

def _empty_sku():
    result = barcode_gen.generate("", Path(tempfile.mkdtemp()))
    assert result is None
test("barcode_gen: empty SKU -> None", _empty_sku)

def _safe_fn():
    result = barcode_gen._safe_filename('AB:CD/EF*GH?"<>|')
    for bad_char in [':', '/', '*', '?', '"', '<', '>', '|']:
        assert bad_char not in result, f"Illegal char '{bad_char}' still in: {result}"
test("barcode_gen: _safe_filename removes all illegal characters", _safe_fn)

def _gen_png():
    with tempfile.TemporaryDirectory() as tmp:
        path = barcode_gen.generate("TEST001", Path(tmp))
        assert path is not None
        assert path.endswith(".png")
        assert os.path.exists(path)
test("barcode_gen: creates PNG file for valid SKU (TEST001)", _gen_png)


# ─── 5. Transaction Writer (CSV mode) ─────────────────────────
print("\n=== [5] Transaction Writer (CSV mode) ===")

SAMPLE_RECORDS = [
    {
        "Product Name": "Test Product A", "SKU": "MM001", "Category": "Shoes",
        "Quantity Added": 5, "Stock Before": 10, "Stock After": 15,
        "Action": "Update Stock (Found by SKU)", "Status": "Success", "Detail/Error": "",
    },
    {
        "Product Name": "Test Product B", "SKU": "MM002", "Category": "Shoes",
        "Quantity Added": 3, "Stock Before": 0, "Stock After": 3,
        "Action": "Created New Item (Auto SKU: MM002)", "Status": "Success", "Detail/Error": "",
    },
    {
        "Product Name": "Bad Product", "SKU": "-", "Category": "Unknown",
        "Quantity Added": 1, "Stock Before": "-", "Stock After": "-",
        "Action": "", "Status": "Error", "Detail/Error": "Category not found",
    },
]


def _write_with_csv(records, csv_path, timestamp):
    env = full_env(TRANSACTION_CSV_PATH=str(csv_path), TRANSACTION_OUTPUT_MODE="csv")
    with patch.dict(os.environ, env):
        _reset("loyverse.config", "loyverse.sheets.writer")
        from loyverse import config as _c  # noqa: F401
        from loyverse.sheets import writer as sw
        sw.write_results(records, timestamp)


def _csv_creates_file():
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "tx.csv"
        _write_with_csv(SAMPLE_RECORDS, csv_path, "20260311_130000")
        assert csv_path.exists(), "CSV file was not created"
test("sheets.writer (csv): creates CSV file", _csv_creates_file)

def _csv_has_header():
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "tx.csv"
        _write_with_csv(SAMPLE_RECORDS, csv_path, "20260311_130000")
        with open(csv_path, encoding="utf-8-sig") as f:
            first_line = f.readline().strip()
        assert "Timestamp" in first_line and "Product Name" in first_line, \
            f"Header missing: {first_line}"
test("sheets.writer (csv): header row written correctly", _csv_has_header)

def _csv_row_count():
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "tx.csv"
        _write_with_csv(SAMPLE_RECORDS, csv_path, "20260311_130000")
        with open(csv_path, encoding="utf-8-sig") as f:
            lines = f.readlines()
        assert len(lines) == 4, f"Expected 4 lines (header+3 data), got {len(lines)}"
test("sheets.writer (csv): correct row count (header + 3 data)", _csv_row_count)

def _csv_append():
    """Second write_results call appends, does not overwrite"""
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "tx.csv"
        _write_with_csv(SAMPLE_RECORDS[:1], csv_path, "20260311_130000")
        _write_with_csv(SAMPLE_RECORDS[1:], csv_path, "20260311_140000")
        with open(csv_path, encoding="utf-8-sig") as f:
            lines = f.readlines()
        # header(1) + run1(1) + run2(2) = 4 lines
        assert len(lines) == 4, f"Expected 4 lines on append, got {len(lines)}"
test("sheets.writer (csv): appends on second run (no overwrite)", _csv_append)

def _csv_error_row_included():
    """Error rows must also be written to CSV"""
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "tx.csv"
        _write_with_csv(SAMPLE_RECORDS, csv_path, "20260311_130000")
        with open(csv_path, encoding="utf-8-sig") as f:
            content = f.read()
        assert "Error" in content, "Error status not found in CSV"
        assert "Category not found" in content
test("sheets.writer (csv): error rows included in CSV", _csv_error_row_included)


# ─── 6. loyverse_api ──────────────────────────────────────────
print("\n=== [6] loyverse_api: structure & STORE_ID handling ===")

_reset("loyverse.loyverse_api", "loyverse.config")
sys.modules["loyverse.sheets.auth"] = MagicMock()
with patch.dict(os.environ, BASE_ENV):
    from loyverse import config as _cfg2  # noqa: F401
    from loyverse import loyverse_api as lv

def _fn_exists():
    required = [
        "find_variant_by_sku", "find_variant_by_name",
        "get_all_categories", "find_category_id",
        "get_last_sku_in_category", "get_current_stock",
        "update_stock", "create_item",
    ]
    for fn in required:
        assert hasattr(lv, fn), f"Missing function: {fn}"
test("loyverse_api: all required functions exist", _fn_exists)

def _create_item_sig():
    sig = inspect.signature(lv.create_item)
    params = list(sig.parameters.keys())
    assert "category_id" in params, f"create_item missing category_id: {params}"
test("loyverse_api: create_item accepts category_id parameter", _create_item_sig)

def _update_stock_no_store_id():
    """update_stock payload must NOT include store_id when STORE_ID is empty"""
    captured = {}
    def mock_post(path, payload):
        captured["payload"] = payload
        mock_resp = MagicMock()
        mock_resp.raise_for_status = lambda: None
        return mock_resp

    _reset("loyverse.loyverse_api", "loyverse.config")
    with patch.dict(os.environ, full_env(LOYVERSE_STORE_ID="")):
        from loyverse import config as _c3  # noqa: F401
        from loyverse import loyverse_api as lv3
        with patch.object(lv3, "_post", side_effect=mock_post), \
             patch.object(lv3, "get_current_stock", return_value=5.0):
            lv3.update_stock("FAKE_VARIANT", 3)
    level = captured["payload"]["inventory_levels"][0]
    assert "store_id" not in level, f"store_id should be absent when empty, got: {level}"
test("loyverse_api: update_stock omits store_id when LOYVERSE_STORE_ID is empty", _update_stock_no_store_id)

def _create_item_no_store_id():
    """create_item store entry must NOT include store_id when STORE_ID is empty"""
    captured = {}
    def mock_post(path, payload):
        captured["payload"] = payload
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        return mock_resp

    _reset("loyverse.loyverse_api", "loyverse.config")
    with patch.dict(os.environ, full_env(LOYVERSE_STORE_ID="")):
        from loyverse import config as _c4  # noqa: F401
        from loyverse import loyverse_api as lv4
        with patch.object(lv4, "_post", side_effect=mock_post):
            lv4.create_item("Test Item", "MM001", 5)
    store_entry = captured["payload"]["variants"][0]["stores"][0]
    assert "store_id" not in store_entry, f"store_id should be absent, got: {store_entry}"
    assert store_entry["stock_after"] == 5
test("loyverse_api: create_item omits store_id when LOYVERSE_STORE_ID is empty", _create_item_no_store_id)


# ─── Summary ──────────────────────────────────────────────────
print("\n" + "=" * 55)
passed = sum(1 for r in results if r[0] == PASS)
total  = len(results)
print(f"  RESULT: {passed}/{total} tests passed")
if passed == total:
    print("  All tests PASSED!")
else:
    failed_names = [r[1] for r in results if r[0] == FAIL]
    print(f"  {len(failed_names)} test(s) FAILED:")
    for n in failed_names:
        print(f"    - {n}")
print("=" * 55)

sys.exit(0 if passed == total else 1)

# CLAUDE.md

Context for AI coding agents working in this repo. Read this first.

## What this project is

A Python automation tool that syncs products from **Google Sheets → Loyverse POS**.
It auto-generates SKUs, prints barcode PNG labels, and logs every transaction.

The flow mirrors a real warehouse receiving process and is split into **two steps**:

1. **Step 1 — `step1_barcode_gen.py`**: For rows with state `PENDING`, ensure the
   item exists in Loyverse (created with **stock 0** if new), auto-assign an SKU,
   generate a barcode PNG, then flip the row state to `BARCODE_READY`.
2. **Step 2 — `step2_stock_update.py`**: For rows with state `BARCODE_READY`, add
   the real received quantity into Loyverse inventory, then flip state to `COMPLETED`.

State machine in the sheet's `Process_State` column:
`PENDING → BARCODE_READY → COMPLETED`

## How to run

```bash
pip install -r requirements.txt              # one-time

# Web UI (preferred — URL entered in the browser)
python -m loyverse.web.app                    # dev server at :5000
docker compose up --build                     # or via Docker

# CLI (uses INPUT_SHEET_URL from .env)
python -m loyverse.steps.step1_barcode_gen    # create items + barcodes
python -m loyverse.steps.step2_stock_update   # add real stock once goods arrive

python -m loyverse.diagnostics                # verify Google service-account access
python tests/test_project.py                  # run the test suite (no real creds needed)

# Sales-by-category report (also available at /reports/sales in the Web UI)
python -m loyverse.reports.sales_by_category --from 2026-07-01 --to 2026-07-30 \
       [--category "ร้านเอ" --category "ร้านบี"] [--excel out.xlsx]
```

Barcodes land in `output/{YYYYMMDD}/{sheet-file-name}/{SKU}.png`.
Transaction log appends to `output/transactions.csv` (or a Google Sheet, see config).

## Layout

The code is a single package, `loyverse/`, imported with absolute paths
(`from loyverse import config`, `from loyverse.sheets import reader as sheets`).
Run things as modules from the repo root (`python -m loyverse...`), not as loose scripts.

## Architecture / module map

| Module | Role |
|---|---|
| `loyverse/config.py` | **The only place that reads `.env`.** Everything imports config values from here — never call `os.getenv()` elsewhere. Resolves `.env` from the repo root via `PROJECT_ROOT`. |
| `loyverse/sheets/auth.py` | gspread Service Account auth (needs `credentials.json`). |
| `loyverse/sheets/reader.py` | Reads/parses the Input Sheet, writes status/SKU/state back to it. |
| `loyverse/sheets/writer.py` | Appends the transaction log → CSV or Google Sheet (`TRANSACTION_OUTPUT_MODE`). |
| `loyverse/loyverse_api.py` | Loyverse REST wrapper: categories, variants, items, inventory. Has 429 retry. |
| `loyverse/sku_generator.py` | Reads the Mapping Sheet (`category → prefix`) and computes the next running SKU. |
| `loyverse/barcode_gen.py` | Renders Code128 barcode PNG + label (name, price) using Pillow. Font in `loyverse/assets/fonts/`. |
| `loyverse/shared_logic.py` | Per-row business logic shared by both steps (`process_row_step1/2`). |
| `loyverse/steps/step1_barcode_gen.py` / `step2_stock_update.py` | The two pipeline entry points. `run(url=None, progress=None)` returns a summary dict and, if given a `progress` callback, emits `{start,item,summary}` events the web UI streams live. |
| `loyverse/steps/legacy_sync.py` | **Legacy** single-pass pipeline. Prefer the two-step modules. |
| `loyverse/reports/catalog_cache.py` | In-memory cache (TTL, clearable) of `item_id → category` built from `/items` + `/categories`. Deleted/uncategorized items fall into `(สินค้าถูกลบ)` / `(ไม่มีหมวดหมู่)` buckets so sales are never silently dropped. |
| `loyverse/reports/sales_by_category.py` | Sales-by-category report. `aggregate()` is pure (receipts + Catalog → `SalesReport`, no I/O — this is what the tests exercise). `build_report()` does the I/O: local date range → UTC (`utc_range()`, timezone-aware) → `loyverse_api.iter_receipts()` → `aggregate()`. Also a CLI entry point (`python -m loyverse.reports.sales_by_category`). |
| `loyverse/reports/excel_export.py` | Renders a `SalesReport` to `.xlsx` (`build_workbook()` → `io.BytesIO`): one `สรุปรวมทุกราย` overview sheet, then **one consignment-statement sheet per consignor** (invoice-style: line items with qty/unit price/line total, then a right-aligned payout block and signature lines), print-ready and safe to forward to that one consignor. Totals are live `=SUM(...)` formulas, not baked-in values. |
| `loyverse/web/app.py` | Flask UI: `/` (input form), `/run` (SSE — streams live progress while a step runs), `/transactions` (view log), `/reports/sales` + `/reports/sales/export` + `/reports/sales/refresh-catalog` (sales-by-category report + Excel export). Served by gunicorn as `loyverse.web.app:app`. |
| `loyverse/diagnostics.py` | Diagnostic for Google Sheets permissions (was `check_auth.py`). |
| `tools/dump_items.py` | Standalone scratch script that dumps all items/SKUs. Has a **hardcoded placeholder token** — not part of the real pipeline; don't wire it in. |
| `tests/test_project.py` | Test suite. Run with `python tests/test_project.py` from the repo root. |

Data flow: `steps.*` → `sheets.reader.fetch_input_records()` → `shared_logic.process_row_*`
→ `loyverse_api` (+ `sku_generator`, `barcode_gen`) → write back to sheet + `sheets.writer`.

## Conventions (follow these when editing)

- **Config access**: `from loyverse import config`; do not read env vars directly elsewhere.
- **Imports**: always absolute from the `loyverse` package — no implicit/relative flat imports.
- **Status vocabulary** used on result dicts and written to the sheet:
  - `Success` — processed OK
  - `OUT` — business rule rejected the row (missing fields, category not in Loyverse,
    price mismatch). Recoverable by the user, not an exception.
  - `Error` — unexpected failure.
- **Domain errors** are real exceptions in `loyverse_api.py`: `CategoryNotFoundError`,
  `PriceMismatchError`. Catch these to produce an `OUT` status rather than `Error`.
- **Categories are never auto-created** in Loyverse — if a category is missing the row
  goes `OUT`. (Mapping Sheet maps category→prefix; that's separate.)
- **The Google Sheet file's title == the Loyverse category name.** This is load-bearing.
- Comments and user-facing print strings are largely in **Thai**. Match the existing
  language/tone of the file you're editing rather than converting to English.
- Heavy use of emoji in console output (`🚀 ✅ ⚠️ ❌ 📦`). Keep the style consistent.
- gspread clients and store IDs are cached via `lru_cache` — be aware when reasoning
  about test isolation (`test_project.py` pops modules from `sys.modules` to reset).
- **Sales-by-category report (`loyverse/reports/`)**: "Category" here means the
  consignment owner the sale is paid out to, not a product-type grouping — the report
  deliberately has no cost/profit/margin columns (an owner shouldn't see other owners'
  cost data) and no VAT handling (the shop doesn't charge VAT yet). Only one store
  exists, so there's no store filter. If either of these changes, extend
  `sales_by_category.CategoryRow` / `excel_export` rather than repurposing existing fields.
  The Excel file is an **outward-facing document** handed to each consignor, so each
  statement sheet must stay self-contained: never add cross-consignor figures to a
  statement sheet. `ItemRow.unit_price` is a weighted average (`gross / qty`), falling
  back to the line's list `price` when net qty is 0 — don't "simplify" it to a last-seen
  price. The statement's payout block asserts `net = gross - discounts`; if a residual
  ever appears (e.g. VAT arrives) `_residual()` surfaces it as its own line rather than
  letting the arithmetic look wrong.

## Secrets — never touch or commit

- `.env`, `credentials.json`, `token.json` are gitignored. **Do not read, print, or
  echo their contents.** Use `.env.example` as the reference for variable names.
- `tools/dump_items.py` contains a placeholder API token string — never replace it with a real one.

## Key environment variables

Required: `LOYVERSE_TOKEN`, `MAPPING_SHEET_URL` (and `INPUT_SHEET_URL` for the CLI;
the Web UI supplies the input URL per-run, so it's optional there).
Common optional: `TRANSACTION_OUTPUT_MODE` (`csv` default / `sheets`),
`SKU_DIGIT_PAD` (default 3), `INPUT_SHEET_TAB`, `SHEET_COL_*` overrides.
See `.env.example` and the table in `README.md` for the full list.

> ⚠️ Note: column-name defaults differ between `config.py` (e.g. `product_name`,
> `total_number`, `Price`) and `.env.example` (e.g. `Name`, `Add Number`). The
> running config is whatever `.env` sets, falling back to `config.py` defaults.
> When debugging "column not found" errors, check the actual `.env` first.

## Gotchas

- Step 2 fails a row with "Missing SKU (Run Step 1 first)" if Step 1 wasn't run —
  the two steps are ordered and stateful via `Process_State`.
- Price matching tolerance is 0.01; mismatches raise `PriceMismatchError` → `OUT`.
- Loyverse item creation can't set stock in the create payload; `create_item` creates
  then calls `update_stock` separately.
- Tests must pass without real credentials — keep new logic mockable / import-safe.

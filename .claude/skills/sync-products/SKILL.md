---
name: sync-products
description: Run the Google Sheet → Loyverse product sync (barcode generation and/or stock update), interpret the run output, and troubleshoot failed rows. Use when the user wants to "sync products", "generate barcodes", "update stock", run step1/step2, or asks why a row failed / shows OUT / Error status.
---

# sync-products

Drive and troubleshoot the two-step Loyverse sync. Read `CLAUDE.md` first for the
architecture and status vocabulary.

## The two steps

The sheet's `Process_State` column drives everything: `PENDING → BARCODE_READY → COMPLETED`.

Run from the repo root as modules. (Or use the Web UI: `python -m loyverse.web.app`,
then click **Process 1** / **Process 2**.)

1. **Step 1 — create items + barcodes** (processes `PENDING` rows):
   ```bash
   python -m loyverse.steps.step1_barcode_gen
   ```
   Creates missing items in Loyverse at **stock 0**, assigns an auto SKU, writes a
   barcode PNG to `output/{YYYYMMDD}/{sheet-name}/`, sets state → `BARCODE_READY`.

2. **Step 2 — add real stock** (processes `BARCODE_READY` rows):
   ```bash
   python -m loyverse.steps.step2_stock_update
   ```
   Adds `total_number` quantity into Loyverse inventory, sets state → `COMPLETED`.

Run Step 1, let the user print/verify barcodes and receive goods, then run Step 2.
Never run Step 2 expecting it to create items — it will fail rows with "Missing SKU".

## Before running

- Confirm `.env` exists (do **not** print its contents) and `credentials.json` is present.
- If Google Sheets access is in doubt, run `python -m loyverse.diagnostics` first.
- To dry-check logic without real creds, run `python tests/test_project.py`.

## Reading the result

Each row gets a `Status` written back to the sheet:

| Status | Meaning | Action |
|---|---|---|
| `Success` | Processed OK | none |
| `OUT` | Business rule rejected the row | fix the data, see below |
| `Error` | Unexpected failure | inspect the message / stack |

## Troubleshooting `OUT` / `Error` rows

| Symptom | Cause | Fix |
|---|---|---|
| `Category '...' not found in Loyverse` | Sheet file title ≠ a Loyverse category | Rename the Sheet file to match the category, or create the category in Loyverse (the tool never auto-creates it). |
| `ไม่พบ prefix สำหรับ category` | category missing from Mapping Sheet | Add a `category, prefix` row to the `Mapping` tab. |
| `ราคาไม่ตรงกัน` / PriceMismatch | Sheet price ≠ Loyverse price (tol 0.01) | Align the price in the sheet or in Loyverse. |
| `Missing required fields: ...` | empty name/type/price (and qty for step 2) | Fill the cells. |
| `Missing SKU (Run Step 1 first)` | Step 2 ran before Step 1 | Run `step1_barcode_gen.py` first. |
| `403 Forbidden` (gspread) | Sheet not shared with service account | Share the sheet as Editor with the `client_email` from `credentials.json` (run `check_auth.py` to print it). |
| `429` rate limit | too many API calls | The wrapper auto-retries after 5s; just wait. |

## After a run

Point the user to:
- Barcodes: `output/{YYYYMMDD}/{sheet-name}/`
- Transaction log: `output/transactions.csv` (or the Transaction Sheet if `TRANSACTION_OUTPUT_MODE=sheets`)

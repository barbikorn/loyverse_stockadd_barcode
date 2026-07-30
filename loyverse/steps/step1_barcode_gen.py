"""
step1_barcode_gen.py — Step 1: Create items (stock 0) and generate barcodes

run(url, progress) emits progress events through the optional `progress` callback
so a UI can show live status. Each event is a dict:
  {"type": "start",   "step": 1, "total": N, "file_name": ...}
  {"type": "item",    "index": i, "total": N, "name", "category", "sku", "status", "message"}
  {"type": "summary", "step": 1, "total": N, "success": x, "out": y, "error": z}
The function also returns the final summary dict.
"""

from datetime import datetime

from loyverse import config
from loyverse.sheets import reader as sheets
from loyverse import shared_logic
from loyverse.sheets import writer as sheets_writer


def run(url: str | None = None, progress=None) -> dict:
    def emit(event: dict) -> None:
        if progress:
            progress(event)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name, input_data = sheets.fetch_input_records(url or config.INPUT_SHEET_URL)
    barcode_dir = config.get_barcode_output_dir(file_name)

    print("🚀 Starting Step 1: Barcode Generation")
    print(f"📁 Barcode folder: {barcode_dir.resolve()}\n")

    # Pre-filter to the rows this step will actually process (state PENDING / empty),
    # so the total is known up front and the UI can render an accurate progress bar.
    todo = [
        (ws, row_idx, row)
        for ws, row_idx, row in input_data
        if row.get("state", "").upper() in ("", "PENDING")
    ]
    total = len(todo)
    emit({"type": "start", "step": 1, "total": total, "file_name": file_name})

    col_cache: dict[int, dict[str, int]] = {}
    report: list[dict] = []
    counts = {"success": 0, "out": 0, "error": 0}

    for index, (ws, row_idx, row) in enumerate(todo, start=1):
        ws_id = id(ws)
        if ws_id not in col_cache:
            col_cache[ws_id] = sheets.get_output_column_indices(ws)
        cols = col_cache[ws_id]

        cat = row.get("category", "")
        label = row.get("product_name") or row.get("name") or f"row {row_idx}"
        print(f"📦 [{cat}] ({index}/{total}) {label}...")

        result = shared_logic.process_row_step1(row, barcode_dir)
        report.append(shared_logic.to_transaction_record(row, result, include_qty=False))
        status = result["Status"]

        if status == "Success":
            sheets.update_row_sku(ws, row_idx, cols["sku"], result["SKU"])
            sheets.update_row_state(ws, row_idx, cols["state"], "BARCODE_READY")
            sheets.update_row_status(
                ws, row_idx, cols["status"], cols["message"],
                "Success", shared_logic.sheet_message(result),
            )
            counts["success"] += 1
        elif status == "OUT":
            sheets.update_row_status(
                ws, row_idx, cols["status"], cols["message"],
                "OUT", shared_logic.sheet_message(result),
            )
            counts["out"] += 1
        else:
            sheets.update_row_status(
                ws, row_idx, cols["status"], cols["message"],
                "Error", shared_logic.sheet_message(result),
            )
            counts["error"] += 1

        icon = "✅" if status == "Success" else ("⚠️" if status == "OUT" else "❌")
        print(f"{icon} [{cat}] {label} | SKU: {result['SKU']} | {status}")
        emit({
            "type": "item", "index": index, "total": total,
            "name": label, "category": cat, "sku": result["SKU"],
            "status": status, "message": shared_logic.sheet_message(result),
        })

    if report:
        sheets_writer.write_results(report, timestamp)

    print(f"\n✨ Step 1 Completed: Processed {total} items.")
    summary = {"step": 1, "total": total, **counts}
    emit({"type": "summary", **summary})
    return summary


if __name__ == "__main__":
    run()

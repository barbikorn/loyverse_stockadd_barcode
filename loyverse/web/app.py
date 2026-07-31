"""
app.py — Web UI for loyverseAPI

Two pages:
  /              Input page: paste an Input Sheet URL, run Process 1 or Process 2.
  /transactions  Transaction page: paste a Transaction Sheet URL, view the log.

Run:
    pip install -r requirements.txt
    python -m loyverse.web.app          # dev server
    # or: gunicorn loyverse.web.app:app  # production
    # open http://127.0.0.1:5000
"""

import json
import queue
import threading
from datetime import date

import requests
from flask import Flask, Response, redirect, render_template, request, send_file, url_for

from loyverse import config
from loyverse.sheets import auth as sheets_auth
from loyverse.steps import step1_barcode_gen
from loyverse.steps import step2_stock_update
from loyverse.reports import catalog_cache
from loyverse.reports import excel_export
from loyverse.reports import sales_by_category as sbc

app = Flask(__name__)

# Process key → (label, module). Each module exposes run(url=..., progress=...).
PROCESSES = {
    "step1": ("Process 1 · สร้างสินค้า + Barcode", step1_barcode_gen),
    "step2": ("Process 2 · อัปเดตสต็อก", step2_stock_update),
}


@app.route("/", methods=["GET"])
def index():
    # Pre-fill with the .env value as a convenience; the user can override it.
    url = (config.INPUT_SHEET_URL or "").strip()
    return render_template("index.html", url=url, processes=PROCESSES)


def _sse(event: dict) -> str:
    """Format a dict as one Server-Sent Events message."""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.route("/run")
def run_stream():
    """
    Run a process and stream live progress to the browser via Server-Sent Events.
    The step pushes {start|item|summary} events through its `progress` callback;
    we relay each one to the client as it happens.
    """
    proc = request.args.get("process", "")
    url = (request.args.get("url") or "").strip()

    def generate():
        if proc not in PROCESSES:
            yield _sse({"type": "error", "message": "ไม่พบ Process ที่เลือก"})
            return
        if not url:
            yield _sse({"type": "error", "message": "กรุณาใส่ URL ของ Google Sheet"})
            return

        label, module = PROCESSES[proc]
        events: "queue.Queue" = queue.Queue()
        DONE = object()

        def worker():
            try:
                module.run(url=url, progress=events.put)
            except Exception as exc:  # any failure becomes a terminal error event
                events.put({"type": "error", "message": str(exc)})
            finally:
                events.put(DONE)

        threading.Thread(target=worker, daemon=True).start()

        yield _sse({"type": "open", "label": label})
        while True:
            event = events.get()
            if event is DONE:
                break
            yield _sse(event)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",  # disable proxy buffering so events arrive live
    }
    return Response(generate(), mimetype="text/event-stream", headers=headers)


@app.route("/transactions", methods=["GET"])
def transactions():
    url = (request.args.get("url") or config.TRANSACTION_SHEET_URL or "").strip()
    headers: list[str] = []
    rows: list[list[str]] = []
    error = ""

    if url:
        try:
            ss = sheets_auth.open_sheet_by_url(url)
            try:
                ws = ss.worksheet(config.TRANSACTION_SHEET_NAME)
            except Exception:
                ws = ss.sheet1  # fall back to the first tab
            values = ws.get_all_values()
            if values:
                headers, rows = values[0], values[1:]
                rows.reverse()  # newest first
        except Exception as exc:
            error = f"อ่าน Transaction Sheet ไม่สำเร็จ: {exc}"

    return render_template(
        "transactions.html",
        url=url,
        headers=headers,
        rows=rows,
        error=error,
    )


def _parse_report_args(args):
    """
    แปลง query params ของหน้ารายงาน → (date_from, date_to, category_ids, error)
    error เป็น "" ถ้าไม่มีปัญหา — ใช้ร่วมกันทั้ง /reports/sales และ /reports/sales/export
    """
    today = sbc.today_in_tz()
    default_from = today.replace(day=1)

    raw_from = (args.get("from") or "").strip()
    raw_to = (args.get("to") or "").strip()

    try:
        date_from = date.fromisoformat(raw_from) if raw_from else default_from
    except ValueError:
        return default_from, today, [], "รูปแบบวันที่ (จาก) ไม่ถูกต้อง"

    try:
        date_to = date.fromisoformat(raw_to) if raw_to else today
    except ValueError:
        return date_from, today, [], "รูปแบบวันที่ (ถึง) ไม่ถูกต้อง"

    if date_to < date_from:
        return date_from, date_to, [], "ช่วงวันที่ไม่ถูกต้อง: วันที่ 'ถึง' ต้องไม่ก่อนวันที่ 'จาก'"

    if (date_to - date_from).days + 1 > config.REPORT_MAX_RANGE_DAYS:
        return date_from, date_to, [], f"ช่วงวันที่กว้างเกินไป (สูงสุด {config.REPORT_MAX_RANGE_DAYS} วัน)"

    category_ids = [c for c in args.getlist("category") if c]
    return date_from, date_to, category_ids, ""


def _friendly_report_error(exc: Exception) -> str:
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        code = exc.response.status_code
        if code in (401, 403):
            return "Token ไม่ถูกต้องหรือไม่มีสิทธิ์ RECEIPTS_READ / ITEMS_READ"
        if code == 402:
            return "บัญชี Loyverse หมดอายุ subscription"
    return f"เกิดข้อผิดพลาด: {exc}"


@app.route("/reports/sales", methods=["GET"])
def sales_report():
    date_from, date_to, category_ids, error = _parse_report_args(request.args)

    try:
        catalog = catalog_cache.get_catalog()
    except Exception as exc:
        catalog = catalog_cache.Catalog()
        error = error or _friendly_report_error(exc)

    report = None
    if not error:
        try:
            report = sbc.build_report(date_from, date_to, category_ids=category_ids or None)
        except Exception as exc:
            error = _friendly_report_error(exc)

    return render_template(
        "reports_sales.html",
        date_from=date_from,
        date_to=date_to,
        category_ids=set(category_ids),
        categories=catalog.categories,
        report=report,
        error=error,
        currency=config.REPORT_CURRENCY_SYMBOL,
    )


@app.route("/reports/sales/export", methods=["GET"])
def sales_report_export():
    date_from, date_to, category_ids, error = _parse_report_args(request.args)
    if error:
        return error, 400

    try:
        report = sbc.build_report(date_from, date_to, category_ids=category_ids or None)
    except Exception as exc:
        return _friendly_report_error(exc), 400

    bio = excel_export.build_workbook(report)
    fname = excel_export.suggested_filename(report)
    return send_file(
        bio,
        as_attachment=True,
        download_name=fname,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/reports/sales/refresh-catalog", methods=["POST"])
def sales_report_refresh_catalog():
    catalog_cache.clear_cache()
    params = request.form.to_dict(flat=False)
    return redirect(url_for("sales_report", **params))


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)

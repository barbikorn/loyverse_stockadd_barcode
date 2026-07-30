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

from flask import Flask, Response, render_template, request

from loyverse import config
from loyverse.sheets import auth as sheets_auth
from loyverse.steps import step1_barcode_gen
from loyverse.steps import step2_stock_update

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


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)

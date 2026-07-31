# Implementation Plan — หน้าสรุปยอดขาย by Category (+ Export Excel)

Feature: หน้าเว็บใหม่ `/reports/sales` สำหรับดูยอดขายแยกตาม Category
ในช่วงวันที่ที่เลือก และ export เป็นไฟล์ Excel (.xlsx)

**บริบทสำคัญ (ยืนยันจากผู้ใช้แล้ว — กำหนดขอบเขตทั้งหมด):**
- Category **= เจ้าของสินค้าที่นำมาฝากขาย** (consignment) ไม่ใช่หมวดหมู่สินค้าทั่วไป
  → รายงานนี้ใช้เพื่อ**สรุปยอดขายเพื่อจ่ายเงินคืนให้เจ้าของแต่ละราย** ไม่ใช่รายงานบัญชีภายใน
- ยังไม่มี VAT ในระบบ → ไม่ต้องแยกภาษี, `total_money` ใช้เป็นยอดขายสุทธิได้ตรงๆ
- ไม่ต้องมีต้นทุน/กำไรขั้นต้น (`cost`, `gross_profit`, `margin_pct`) — เจ้าของ category
  ไม่ควรเห็นข้อมูลต้นทุนของสินค้าที่ไม่ใช่ของตัวเอง และไฟล์นี้จะถูกส่งต่อให้เจ้าของโดยตรง
- มีสาขาเดียว → ตัด `store_id` filter และ multi-store UI ออกทั้งหมด (ใช้
  `_get_default_store_id()` ที่มีอยู่แล้วพอ ไม่ต้องเพิ่ม UI เลือกสาขา)

---

## 1. ข้อจำกัดจาก Loyverse API (ตรวจแล้วจาก `docs/api_doc.txt`)

สิ่งที่ต้องรู้ก่อนออกแบบ เพราะมันกำหนดสถาปัตยกรรมทั้งหมด:

| ข้อเท็จจริง | อ้างอิง | ผลต่อ design |
|---|---|---|
| `GET /receipts` **ไม่มี** query param `category_id` | api_doc.txt:2844-2892 | ต้องดึง receipts ทั้งช่วงวันมา แล้ว aggregate ฝั่งเรา |
| `line_item` มีแค่ `item_id`, `variant_id`, `sku`, `item_name` — **ไม่มี** `category_id` | api_doc.txt:2785-2804 | ต้องสร้าง lookup `item_id → category_id` จาก `GET /items` |
| `GET /categories` คืน `{id, name}` | api_doc.txt:390-435 | สร้าง `category_id → name` |
| filter ช่วงเวลา: `created_at_min` / `created_at_max` (ISO 8601, **UTC**) | api_doc.txt:2877-2883, 234-235 | ต้องแปลง local date (Asia/Bangkok) → UTC ก่อนยิง |
| pagination: `limit` max 250 (default 50), `cursor` | api_doc.txt:224-229 | loop cursor จนไม่มี `cursor` |
| rate limit: 300 req / 300 sec → 429 | api_doc.txt:231-232 | ใช้ `_get()` เดิมที่มี retry 429 อยู่แล้ว |
| `receipt_type` = `SALE` / `REFUND`; refund เป็น receipt แยกและค่าเงินเป็น **บวก** | api_doc.txt:2628-2635, 2661-2663 | net = SALE − REFUND (ต้องลบเอง) |
| `cancelled_at` = receipt ที่ถูกยกเลิก | api_doc.txt:2653-2655 | ต้อง **ตัดออก** ไม่นับยอด |
| `line_item` มี `gross_total_money`, `total_discount`, `total_money` | api_doc.txt:2793-2801 | ใช้พอสำหรับยอดขาย ไม่ต้องใช้ `cost` / `cost_total` |
| `sold_by_weight` → quantity เป็นทศนิยมได้ | api_doc.txt:1439-1442 | qty ต้องเป็น `float` ไม่ใช่ `int` |
| ต้องมี permission `RECEIPTS_READ`, `ITEMS_READ` | api_doc.txt:63-82 | Personal token มีครบอยู่แล้ว (unlimited access) |

> ตัด `store_id` filter ออกจากสโคป — มีสาขาเดียว ใช้ `_get_default_store_id()` เดิมพอ
> ไม่ต้อง filter/แสดง store ใน UI

**สรุปกลยุทธ์:** ดึง receipts ตามช่วงวัน → join line_items กับ item index (in-memory) →
group by category (= เจ้าของสินค้าฝากขาย) → คำนวณ metrics → render / export

**นิยาม metric (เรียบง่าย — ไม่มี VAT, ไม่มีต้นทุน/กำไร):**

```
qty_sold       = Σ quantity                    (SALE) − Σ (REFUND)
gross_sales    = Σ line_item.gross_total_money (SALE) − Σ (REFUND)   ← ก่อนหักส่วนลด
discounts      = Σ line_item.total_discount    (SALE) − Σ (REFUND)
net_sales      = Σ line_item.total_money       (SALE) − Σ (REFUND)   ← ยอดที่ต้องจ่ายคืนเจ้าของ
receipts_count = จำนวน receipt ที่มี line item ของ category นั้น (นับแบบ distinct)
share_pct      = net_sales / net_sales_ทั้งหมด * 100
```

`net_sales` คือตัวเลขหลักที่ใช้จ่ายเงินคืนเจ้าของสินค้า — ไม่มี VAT ต้องหักในสโคปนี้
(ถ้าอนาคตมีค่าคอมมิชชั่น/ส่วนแบ่ง % ต่อเจ้าของแต่ละราย ค่อยเพิ่มคอลัมน์
"ยอดโอนสุทธิ = net_sales × (1 − commission%)" เป็น phase ถัดไป — ดูข้อ 12)

---

## 2. โครงสร้างไฟล์ที่จะเพิ่ม/แก้

```
loyverse/
  loyverse_api.py                 ← [แก้] เพิ่ม iter_receipts(), iter_all_items(), list_categories()
  reports/                        ← [ใหม่] package
    __init__.py
    catalog_cache.py              ← [ใหม่] cache item_id→category (TTL)
    sales_by_category.py          ← [ใหม่] core aggregation + CLI entry point
    excel_export.py               ← [ใหม่] สร้างไฟล์ .xlsx (pandas + openpyxl)
  web/
    app.py                        ← [แก้] เพิ่ม 3 routes
    templates/
      base.html                   ← [แก้] เพิ่มลิงก์ nav + CSS ของ stat tile / filter bar
      reports_sales.html          ← [ใหม่] หน้าจอรายงาน
  config.py                       ← [แก้] เพิ่ม env var ของรายงาน
tests/test_project.py             ← [แก้] เพิ่มเทสต์ (mock ไม่ใช้ creds จริง)
docs/plan_sales_by_category.md    ← ไฟล์นี้
README.md / CLAUDE.md             ← [แก้] เอกสาร
.env.example                      ← [แก้] env vars ใหม่
```

**ไม่มี dependency ใหม่** — `pandas` + `openpyxl` อยู่ใน `requirements.txt` แล้ว
(timezone ใช้ `zoneinfo` จาก stdlib; Windows อาจต้อง `tzdata` — ดูข้อ 9)

---

## 3. Layer 1 — `loyverse_api.py` (เพิ่มฟังก์ชัน ห้ามแก้ของเดิม)

ทำตาม convention เดิม: ใช้ `_get()` ที่มี 429-retry, docstring/คอมเมนต์ภาษาไทย

```python
# ─── Receipts ─────────────────────────────────────────────────

def iter_receipts(created_at_min: str, created_at_max: str):
    """
    Generator ไล่ receipts ทุกหน้าในช่วงเวลา (ISO 8601 UTC) ที่สาขา default
    yield receipt dict ทีละใบ — ใช้ generator เพื่อไม่กินแรมตอนช่วงวันยาว
    """
    store_id = _get_default_store_id()
    cursor = None
    while True:
        params = {
            "limit": 250,
            "created_at_min": created_at_min,
            "created_at_max": created_at_max,
            "store_id": store_id,
        }
        if cursor:
            params["cursor"] = cursor
        data = _get("/receipts", params)
        yield from data.get("receipts", [])
        cursor = data.get("cursor")
        if not cursor:
            break


def iter_all_items():
    """Generator ไล่ items ทุกหน้า (ใช้สร้าง item→category index)"""
    # เหมือน pattern ใน get_last_sku_in_category() — limit 250 + cursor


def list_categories() -> list[dict]:
    """คืน [{'id':..., 'name':...}] ทั้งหมด (รวม pagination, ตัด deleted)"""
    # get_all_categories() เดิมคืน name→id ซึ่งจะทับกันถ้าชื่อซ้ำ
    # และเรา "ต้องใช้ทิศทางกลับ" (id→name) จึงเพิ่มฟังก์ชันใหม่ ไม่แก้ของเดิม
```

หมายเหตุ: `params` ที่ส่งเป็น `None` ต้องไม่ใส่ลง dict (Loyverse จะตอบ 400 `INVALID_VALUE`)

---

## 4. Layer 2 — `reports/catalog_cache.py`

ปัญหา: ทุกครั้งที่เปิดรายงาน ถ้าดึง `/items` ใหม่หมด (ร้านมี 5,000 items = 20 requests)
จะกิน rate limit เร็วมากและช้า

```python
@dataclass(frozen=True)
class ItemInfo:
    item_id: str
    item_name: str
    category_id: str | None
    category_name: str          # "(ไม่มีหมวดหมู่)" ถ้า category_id เป็น None

class Catalog:
    items: dict[str, ItemInfo]              # item_id → ItemInfo
    categories: list[tuple[str, str]]        # [(category_id, name)] เรียงตามชื่อ
    fetched_at: datetime

def get_catalog(force_refresh: bool = False) -> Catalog:
    """
    cache ใน module-level variable + TTL (config.REPORT_CATALOG_TTL_SEC, default 600)
    ใช้ threading.Lock กันสอง request สร้างพร้อมกัน (Flask + gunicorn thread worker)
    """
```

- ใช้ **lock + TTL ธรรมดา** ไม่ใช้ `lru_cache` เพราะต้องมีปุ่ม "รีเฟรชแคตตาล็อก" บนหน้าเว็บ
  (ของเดิมในโปรเจกต์ใช้ `lru_cache` ซึ่ง invalidate ไม่ได้ → ปัญหาเดิมที่ CLAUDE.md เตือนไว้)
- fallback: line_item ที่ `item_id` ไม่อยู่ใน catalog (สินค้าถูกลบไปแล้ว) → จัดเข้า
  bucket `"(สินค้าถูกลบ)"` ไม่ทิ้งยอดขายหาย และ **ไม่** ยิง `/items/{id}` เพิ่ม (กัน N+1)

---

## 5. Layer 3 — `reports/sales_by_category.py` (หัวใจ — pure & testable)

```python
@dataclass
class CategoryRow:
    category_id: str | None
    category_name: str
    qty_sold: float
    gross_sales: float
    discounts: float
    net_sales: float
    share_pct: float
    receipts_count: int
    items: list[ItemRow]     # breakdown ระดับสินค้า (สำหรับ expand + sheet 2)

@dataclass
class ItemRow:
    sku: str; item_name: str; variant_name: str | None
    qty_sold: float; net_sales: float

@dataclass
class SalesReport:
    date_from: date; date_to: date            # local date ที่ผู้ใช้เลือก
    tz_name: str
    category_filter: list[str]                # [] = ทุก category
    rows: list[CategoryRow]                   # เรียง net_sales มาก→น้อย
    totals: CategoryRow                       # แถวรวม
    receipts_scanned: int; refunds_scanned: int; cancelled_skipped: int
    generated_at: datetime
```

**ฟังก์ชันหลัก (แยก I/O ออกจาก logic เพื่อเทสต์ได้):**

```python
def aggregate(receipts: Iterable[dict], catalog: Catalog,
              category_ids: list[str] | None = None) -> SalesReport
    # pure: รับ iterable ของ receipt dict → คืน SalesReport  ← ส่วนที่เทสต์หนัก

def build_report(date_from: date, date_to: date,
                 category_ids: list[str] | None = None,
                 progress: Callable | None = None) -> SalesReport
    # ทำ I/O: local date → UTC range → iter_receipts() → aggregate()
```

**ลำดับ logic ใน `aggregate()`:**

1. `if receipt.get("cancelled_at"): cancelled_skipped += 1; continue`
2. `sign = -1 if receipt["receipt_type"] == "REFUND" else +1`
3. ทุก `line_item`:
   - `info = catalog.items.get(line["item_id"])` → ได้ `category_id/name` (fallback ตามข้อ 4)
   - ถ้ามี `category_ids` filter และไม่ตรง → ข้าม
   - accumulate ทุก metric × `sign` (ใช้ `_num()` helper: `float(x or 0)`)
   - accumulate ระดับ item key = `(variant_id or item_id)`
   - เก็บ `receipt_number` ลง `set` ต่อ category → `receipts_count`
4. คำนวณ `share_pct` หลังรวมเสร็จ; ปัด 2 ตำแหน่งตอน **แสดง/export** เท่านั้น
   (คำนวณเก็บด้วย float เต็ม เพื่อไม่ให้ totals ≠ ผลรวมของแถว)
5. เรียง `rows` ตาม `net_sales` desc; `items` ในแต่ละ row ก็เรียงเหมือนกัน

**การแปลงเวลา (จุดพลาดง่ายที่สุด):**

```python
tz = ZoneInfo(config.REPORT_TIMEZONE)              # default "Asia/Bangkok"
start = datetime.combine(date_from, time.min, tz)  # 00:00:00.000 local
end   = datetime.combine(date_to + timedelta(days=1), time.min, tz)  # exclusive
created_at_min = start.astimezone(UTC).isoformat(timespec="milliseconds")...  # "...Z"
created_at_max = (end - timedelta(milliseconds=1)).astimezone(UTC)...
```
เลือกใช้ `created_at` (ไม่ใช่ `receipt_date`) เพื่อให้ตรงกับที่ API filter ให้
— แต่จะ **แสดง `receipt_date`** ใน sheet รายละเอียด และเขียน note กำกับไว้

**CLI entry point** (ตาม convention `python -m loyverse...`):

```bash
python -m loyverse.reports.sales_by_category --from 2026-07-01 --to 2026-07-30 \
       [--category "ร้านเอ" --category "ร้านบี"] [--excel out.xlsx]
```
พิมพ์ตารางสรุปลง console (emoji style `📊 ✅ ⚠️` ตาม convention เดิม)

---

## 6. Layer 4 — `reports/excel_export.py`

```python
def build_workbook(report: SalesReport) -> io.BytesIO
def suggested_filename(report: SalesReport) -> str
    # "sales_by_category_20260701-20260730.xlsx"
```

ใช้ `pandas.ExcelWriter(engine="openpyxl")` แล้วแต่งด้วย openpyxl:

**Sheet 1 — `สรุปตามหมวดหมู่`**
- A1:A4 = block ข้อมูลหัวรายงาน (merge): ช่วงวันที่, timezone, category filter,
  เวลาที่สร้าง, จำนวน receipts ที่สแกน / refund / ที่ยกเลิกและถูกตัดออก
- แถว header (แถว 6): Category | จำนวนที่ขาย | ยอดขายรวม (Gross) | ส่วนลด | ยอดขายสุทธิ | สัดส่วนยอดขาย % | จำนวนบิล
  - style: bold, background `5E2F10` (สีแบรนด์เดียวกับเว็บ), font ขาว, freeze pane `A7`
- ข้อมูลเรียง net_sales desc; number format `#,##0.00` สำหรับเงิน, `0.00"%"` สำหรับ %
- แถวสุดท้าย = **รวมทั้งหมด** (bold + border บน) — เขียนเป็นสูตร `=SUM(...)` ไม่ใช่ค่านิ่ง
  เพื่อให้ผู้รับรายงานตรวจได้ และคงถูกต้องหลังผู้ใช้ filter/ลบแถว
- `ws.auto_filter.ref` = ช่วงตาราง + ปรับความกว้างคอลัมน์ตามความยาวข้อความ

**Sheet 2 — `รายละเอียดตามสินค้า`**
- Category | SKU | ชื่อสินค้า | ตัวเลือก(variant) | จำนวนที่ขาย | ยอดขายสุทธิ
- ใช้ตรวจย้อนกลับว่ายอดของ category (เจ้าของ) มาจากสินค้าตัวไหน — เอาไว้แนบให้เจ้าของดูละเอียด

**Encoding/ตัวเลข:** ปล่อยให้เป็น native number ใน xlsx (ห้ามใส่ค่าเป็น string
มี comma) ไม่งั้น Excel รวมยอดต่อไม่ได้

---

## 7. Layer 5 — Web (Flask)

### Routes (`loyverse/web/app.py`)

| Route | Method | หน้าที่ |
|---|---|---|
| `/reports/sales` | GET | render form + ผลลัพธ์ (ถ้ามี query param ครบ) |
| `/reports/sales/export` | GET | คืนไฟล์ .xlsx ด้วย query param เดียวกัน |
| `/reports/sales/refresh-catalog` | POST | ล้าง cache แคตตาล็อกแล้ว redirect กลับ |

**Query params (ใช้ร่วมกันทั้ง view และ export → ปุ่ม export แค่ copy querystring):**
`from=YYYY-MM-DD`, `to=YYYY-MM-DD`, `category=<id>` (ซ้ำได้หลายตัว)

ทำ helper เดียว `_parse_report_args(request.args)` → `(date_from, date_to, category_ids, error)`
ใช้ทั้งสอง route เพื่อไม่ให้ validation แตกกัน

**Validation & error handling** (คืน error เป็นข้อความไทยบนหน้า ไม่ใช่ 500):
- date format ผิด / `to` < `from` → "ช่วงวันที่ไม่ถูกต้อง"
- ช่วงวันกว้างเกิน `config.REPORT_MAX_RANGE_DAYS` (default 366) → เตือนและไม่ยิง API
- `requests.HTTPError` 401/403 → "Token ไม่ถูกต้องหรือไม่มีสิทธิ์ RECEIPTS_READ"
- 402 → "บัญชี Loyverse หมดอายุ subscription"
- default: `from` = วันที่ 1 ของเดือนปัจจุบัน, `to` = วันนี้ (ตาม `REPORT_TIMEZONE`)

**Export response:**
```python
return send_file(bio, as_attachment=True, download_name=fname,
                 mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
```

**ทำไมไม่ใช้ SSE เหมือน `/run`:** รายงานเป็น request/response สั้น (ปกติ < 10 s)
→ ทำ **synchronous GET** ธรรมดา ให้ URL แชร์/bookmark ได้ (ข้อดีสำคัญของรายงาน)
ถ้าช่วงวันยาวมากจนช้า → phase 2 เพิ่ม SSE progress ได้โดยที่ `build_report()`
รับ `progress=` ไว้แล้วตั้งแต่แรก (ตาม pattern ของ `step1/step2`)

### UI (`templates/reports_sales.html`) — design spec

ใช้ธีมเดิมทั้งหมด (`--bg` ส้ม, `--card` ครีม, `.card`, `.btn-1/2`, `.badge-*`) เพื่อให้กลมกลืน

```
┌─ Filter card ───────────────────────────────────────────────┐
│ [ช่วงวันที่: 2026-07-01] [ถึง: 2026-07-30]                   │
│ presets:  วันนี้ | เมื่อวาน | 7 วัน | เดือนนี้ | เดือนก่อน     │  ← ปุ่ม chip
│ Category (เจ้าของ):  ☑ ทั้งหมด  ☐ ร้านเอ  ☐ ร้านบี ...          │
│            (checkbox grid หลายคอลัมน์ + ช่องค้นหา filter client) │
│ [📊 ดูรายงาน]  [⬇️ Export Excel]   [↻ รีเฟรชแคตตาล็อก]        │
└──────────────────────────────────────────────────────────────┘

┌─ Summary tiles (3 ใบ, grid) ──────────────────────────────────┐
│ ยอดขายสุทธิรวม  |  จำนวนที่ขายรวม  |  จำนวนบิล                  │
└──────────────────────────────────────────────────────────────┘

┌─ ตารางสรุป ──────────────────────────────────────────────────┐
│ Category (เจ้าของ) ▲▼ | จำนวนที่ขาย | Gross | ส่วนลด | สุทธิ | สัดส่วน │
│  แถวมี bar สัดส่วนบางๆ ด้านหลังตัวเลข "สัดส่วน" (pure CSS)      │
│  คลิกชื่อ category → expand แสดง ItemRow ย่อย (<details> ธรรมดา)│
│  แถวรวม (sticky ล่าง, bold)                                   │
└──────────────────────────────────────────────────────────────┘
หมายเหตุ: refund ถูกหักออกแล้ว · บิลที่ยกเลิก N ใบไม่ถูกนับ · ข้อมูล ณ <time>
```

- **client-side sort** ตารางด้วย JS สั้นๆ (vanilla, ไม่มี lib) — ข้อมูลอยู่ในหน้าแล้ว
- ตัวเลขเงินจัดขวา, `toLocaleString("th-TH")` / Jinja filter `"{:,.2f}"`
- ตัวเลขติดลบ (จาก refund มากกว่าขาย) → สีแดง `.err`
- empty state: "ไม่พบยอดขายในช่วงวันที่ที่เลือก" ไม่ใช่ตารางเปล่า
- CSS ใหม่ (`.tiles`, `.tile`, `.chips`, `.cat-grid`, `.bar-cell`) เพิ่มใน `base.html`
  ต่อจากบล็อกเดิม — ไม่แตะ style ที่มีอยู่
- เพิ่มลิงก์ nav: `<a href="{{ url_for('sales_report') }}">Sales by Category</a>`

---

## 8. Config / env vars ที่จะเพิ่ม (`config.py` + `.env.example`)

```python
# ─── Reports ───────────────────────────────────────────────────
REPORT_TIMEZONE        = os.getenv("REPORT_TIMEZONE", "Asia/Bangkok")
REPORT_MAX_RANGE_DAYS  = int(os.getenv("REPORT_MAX_RANGE_DAYS", "366"))
REPORT_CATALOG_TTL_SEC = int(os.getenv("REPORT_CATALOG_TTL_SEC", "600"))
REPORT_CURRENCY_SYMBOL = os.getenv("REPORT_CURRENCY_SYMBOL", "฿")
```
ทุกตัว optional มี default → ผู้ใช้เดิมไม่ต้องแก้ `.env` เลย (ห้าม `_require()` ใหม่)
เข้าถึงผ่าน `from loyverse import config` เท่านั้น ตาม convention

---

## 9. ความเสี่ยง & วิธีรับมือ

| ความเสี่ยง | ผลกระทบ | วิธีรับมือ |
|---|---|---|
| ร้านมี receipts เยอะ (30 วัน = หลายพันใบ) | ช้า + ชน rate limit 300/300s | `limit=250`, generator, cache catalog, จำกัดช่วงวัน, แสดง spinner + เวลา |
| `zoneinfo` ไม่มี tz database บน Windows | `ZoneInfoNotFoundError` ตอนรัน dev | try/except → fallback `timezone(timedelta(hours=7))` + เตือน; แนะนำ `pip install tzdata` ใน README (ไม่บังคับ) |
| ตัวเลขไม่ตรงกับ Back Office ของ Loyverse | เจ้าของ category ไม่เชื่อยอด | เทียบ 1 วันจริงกับ Back Office ก่อน ship |
| สินค้าถูกลบ / ไม่มี category | ยอดขายหาย | bucket `(สินค้าถูกลบ)` / `(ไม่มีหมวดหมู่)` — รวมใน totals เสมอ |
| Composite item | ยอดถูกนับที่ category ของตัว composite ไม่ใช่ components | เป็นพฤติกรรมที่ถูกต้อง — ระบุใน note บนหน้า |
| หลาย category ชื่อซ้ำกัน | รวมยอดผิด | group ด้วย `category_id` (ไม่ใช่ชื่อ) แล้วแสดงชื่อ |
| Flask dev server + blocking request | ผู้ใช้กดซ้ำ → ยิง API ซ้อน | disable ปุ่มตอน submit + cache catalog |

---

## 10. Test plan (`tests/test_project.py` — ต้องผ่านโดยไม่ต้องมี creds จริง)

เพิ่มในสไตล์เดิม (`test(name, fn)` + `patch.dict(os.environ, full_env())`):

1. **Syntax check** — เพิ่ม 4 ไฟล์ใหม่ในลิสต์ `py_files`
2. `aggregate()` — SALE 2 ใบ 2 category → ตัวเลขทุก metric ถูก, `share_pct` รวม = 100
3. `aggregate()` — มี REFUND → net_sales/qty ถูกหักออก (ทดสอบค่าติดลบได้ด้วย)
4. `aggregate()` — receipt มี `cancelled_at` → ไม่ถูกนับ + `cancelled_skipped == 1`
5. `aggregate()` — `item_id` ไม่อยู่ใน catalog → เข้า bucket `(สินค้าถูกลบ)`
6. `aggregate()` — filter `category_ids` → เหลือเฉพาะที่เลือก, `share_pct` คิดจาก subset
7. `aggregate()` — `sold_by_weight` qty = 1.5 → รวมเป็น float ไม่ปัดเป็น int
8. **timezone**: `_utc_range(date(2026,7,1), date(2026,7,1))` →
   `2026-06-30T17:00:00.000Z` … `2026-07-01T16:59:59.999Z` (Asia/Bangkok = UTC+7)
9. `iter_receipts()` — mock `_get` คืน 2 หน้าพร้อม cursor → ได้ receipt ครบทั้ง 2 หน้า
   และ **ไม่วน infinite** เมื่อไม่มี cursor
10. `build_workbook()` — สร้าง xlsx ใน `BytesIO` → เปิดกลับด้วย openpyxl
    เจอ 2 sheet, header ตรง, ยอดรวมตรง
11. **Flask routes** ด้วย `app.test_client()` + mock `build_report`:
    - `/reports/sales` (ไม่มี param) → 200, มีค่า default ในฟอร์ม
    - `/reports/sales?from=...&to=...` → 200 มีชื่อ category ในหน้า
    - `to` < `from` → 200 + ข้อความ error (ไม่ใช่ 500)
    - `/reports/sales/export?...` → 200, `Content-Type` เป็น xlsx, `Content-Disposition` attachment
12. `_parse_report_args()` — ครอบ edge: date เพี้ยน, category ซ้ำ, ช่วงกว้างเกิน limit

---

## 11. ลำดับงาน (แนะนำทำตามนี้ ทีละ commit)

| # | งาน | ไฟล์ | ประมาณ |
|---|---|---|---|
| 1 | API layer: `iter_receipts`, `iter_all_items`, `list_categories` | `loyverse_api.py` | 40 บรรทัด |
| 2 | `reports/__init__.py` + `catalog_cache.py` | ใหม่ | 60 |
| 3 | `sales_by_category.py`: dataclasses + `aggregate()` (pure) | ใหม่ | 110 |
| 4 | เทสต์ข้อ 2-8 ให้ผ่าน **ก่อน** ต่อ UI | `tests/` | 110 |
| 5 | `build_report()` + `_utc_range()` + CLI `main()` | ใหม่ | 70 |
| 6 | `excel_export.py` (2 sheets + styling) | ใหม่ | 100 |
| 7 | Flask routes + `_parse_report_args()` | `web/app.py` | 80 |
| 8 | `reports_sales.html` + CSS/nav ใน `base.html` | templates | 200 |
| 9 | เทสต์ข้อ 1, 9-12 | `tests/` | 90 |
| 10 | เอกสาร: README (ตาราง env + วิธีใช้), CLAUDE.md (module map + route) , `.env.example` | docs | — |
| 11 | **Verify กับข้อมูลจริง**: เทียบ 1 วัน กับ Back Office Loyverse | — | manual |

**Definition of done:**
`python tests/test_project.py` ผ่านทั้งหมด · เปิด `/reports/sales` เลือกช่วงวัน +
category แล้วเห็นตาราง · กด Export ได้ไฟล์ xlsx ที่เปิดใน Excel แล้วยอดตรงกับหน้าเว็บ ·
ยอด net sales ตรงกับ Back Office ของ Loyverse ในวันที่ทดสอบ

---

## 12. ที่ตั้งใจ *ไม่* ทำใน phase นี้ (บอกไว้ให้ชัด)

- กราฟ/chart (ตัวเลข + ตารางพอสำหรับส่งให้เจ้าของ category) → phase 2
- เทียบช่วงเวลา (period vs period), แนวโน้มรายวัน → phase 2
- ค่าคอมมิชชั่น/ส่วนแบ่ง % ต่อเจ้าของแต่ละราย (ถ้าธุรกิจต้องหักค่าเช่าพื้นที่/GP
  ก่อนโอนเงิน ค่อยเพิ่มคอลัมน์ "ยอดโอนสุทธิ" ทีหลัง — ตอนนี้ export แค่ยอดขายดิบ)
- แคชผลรายงานลง SQLite/parquet สำหรับช่วงวันย้อนหลังยาว → phase 3 (ทำเมื่อพบว่าช้าจริง)
- export CSV / PDF, ส่งอีเมลอัตโนมัติ, ตั้ง schedule
- แยกยอดตาม employee / payment type / dining option
- multi-store (ตอนนี้มีสาขาเดียว — ถ้าขยายสาขาค่อยกลับมาเพิ่ม filter)
- auth/login หน้าเว็บ (ตอนนี้ทั้งแอปยังไม่มี — ถ้าจะ deploy ออกเน็ตต้องคุยเรื่องนี้ก่อน)

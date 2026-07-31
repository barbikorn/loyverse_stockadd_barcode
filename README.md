# loyverseAPI

> ระบบ sync สินค้าจาก **Google Sheet → Loyverse POS** พร้อม auto-SKU, barcode generation และ transaction log
> ใช้งานได้ทั้งแบบ **Web UI** และ **Command Line**

---

## How to Use (วิธีใช้งานแบบเร็ว)

มี 3 วิธีให้เลือกใช้:

| วิธี | เหมาะกับ | คำสั่ง |
|---|---|---|
| 🐳 **Docker (แนะนำ)** | รัน Web UI ง่ายสุด ไม่ต้องลง Python | `docker compose up --build` |
| 🌐 **Web UI** | ใช้งานผ่านหน้าเว็บ | `python app.py` |
| ⌨️ **CLI** | รันแบบ script / อัตโนมัติ | `python step1_barcode_gen.py` |

### ก่อนเริ่ม (ทุกวิธีต้องมี)
1. คัดลอก `.env.example` → `.env` แล้วใส่ค่า `LOYVERSE_TOKEN` และ `MAPPING_SHEET_URL`
2. วางไฟล์ `credentials.json` (Google Service Account key) ไว้ใน root ของโปรเจกต์
3. Share Google Sheet ทุกไฟล์ให้ `client_email` ใน `credentials.json` (สิทธิ์ Editor)

> 💡 Web UI จะให้กรอก **URL ของ Input Sheet** ในหน้าเว็บโดยตรง ไม่จำเป็นต้องตั้ง `INPUT_SHEET_URL` ใน `.env`

---

## 🌐 Web UI

หน้าเว็บมี 2 หน้า:

### หน้า 1 — Input / Run (`/`)
1. วาง **URL ของ Google Sheet (Input Data)**
2. กดปุ่มเลือก process:
   - **Process 1 · สร้างสินค้า + Barcode** → รัน Step 1 (สร้างสินค้า stock 0 + barcode)
   - **Process 2 · อัปเดตสต็อก** → รัน Step 2 (เพิ่มสต็อกจริง)
3. ระหว่างรันจะเห็น **progress แบบ real-time**: แถบความคืบหน้า (กี่/ทั้งหมด),
   รายการที่ทำเสร็จทีละแถวพร้อมสถานะ (สำเร็จ / ตีกลับ / ผิดพลาด),
   และเมื่อจบจะมี **การ์ดสรุปผล** บอกชัดเจนว่าสำเร็จกี่รายการ ตีกลับกี่ ผิดพลาดกี่ จากทั้งหมดเท่าไร
   (ทำงานผ่าน Server-Sent Events — ไม่ต้องรีเฟรชหน้า)

### หน้า 2 — Transactions (`/transactions`)
- วาง **URL ของ Transaction Google Sheet** เพื่อดู transaction log แบบตาราง (รายการใหม่สุดอยู่บน)

### หน้า 3 — Sales by Category (`/reports/sales`)
สรุปยอดขายแยกตาม **Category** (= เจ้าของสินค้าที่นำมาฝากขาย) สำหรับใช้จ่ายเงินคืนเจ้าของแต่ละราย
- เลือกช่วงวันที่ (มี preset: วันนี้ / เมื่อวาน / 7 วันล่าสุด / เดือนนี้ / เดือนก่อน) และเลือก Category ที่ต้องการดู
  (ไม่เลือกเลย = แสดงทุก Category)
- ตารางแสดง จำนวนที่ขาย, ยอดขายรวม (Gross), ส่วนลด, **ยอดต้องจ่าย** (สุทธิ), สัดส่วน % — คลิกชื่อ category
  เพื่อดู breakdown ระดับสินค้า (SKU, จำนวน, ราคา/หน่วย, ยอดขายรวม, ส่วนลด, สุทธิ), คลิก header เพื่อ sort
- กด **⬇️ Export Excel** เพื่อดาวน์โหลดไฟล์ `.xlsx` (ชุดข้อมูลเดียวกับที่เห็นบนหน้าเว็บ) โครงสร้างไฟล์:
  - ชีต **`สรุปรวมทุกราย`** — ภาพรวมทุกผู้ฝากขาย (ใช้ภายใน)
  - ชีต **1 ชีตต่อผู้ฝากขาย 1 ราย** — จัดหน้าแบบ *ใบสรุปยอดขายฝากขาย (Consignment Sales Statement)*:
    หัวเอกสาร (ชื่อผู้ฝากขาย / ช่วงวันที่ / วันที่ออก / เลขที่เอกสาร) → ตารางรายการสินค้า
    (ลำดับ, SKU, ชื่อสินค้า, ตัวเลือก, จำนวน, ราคา/หน่วย, ยอดขายรวม, ส่วนลด, ยอดสุทธิ) →
    บล็อกสรุปยอดชิดขวา (Gross → หักส่วนลด → **ยอดสุทธิที่ต้องจ่าย**) → หมายเหตุ → ช่องลงนามผู้จ่าย/ผู้รับเงิน
  - แต่ละชีตตั้ง print area + fit-to-width 1 หน้า และซ้ำหัวตารางทุกหน้าเวลาปริ้นต์ → **ส่งต่อให้เจ้าของได้เลย
    โดยเขาไม่เห็นข้อมูลของรายอื่น** (ถ้าเลือกผู้ฝากขายรายเดียว ชื่อไฟล์จะมีชื่อรายนั้นให้ด้วย)
  - ยอดรวมในไฟล์เขียนเป็นสูตร `=SUM(...)` ไม่ใช่ค่านิ่ง เพื่อให้ผู้รับตรวจยอดเองได้
- กด **↻ รีเฟรชแคตตาล็อก** ถ้าเพิ่งเพิ่ม/แก้ไข category หรือสินค้าใน Loyverse แล้วรายงานยังไม่อัปเดต
  (ระบบ cache รายการสินค้าไว้ `REPORT_CATALOG_TTL_SEC` วินาที เพื่อลด request ไปที่ Loyverse API)

> ⚠️ ยอดขายอิงจาก `receipt.line_items` (ไม่รวมต้นทุน/กำไร) refund ถูกหักออกจากยอดแล้ว
> และบิลที่ถูกยกเลิก (`cancelled_at`) จะไม่ถูกนับ — รายงานนี้ยังไม่รองรับ VAT และมีสาขาเดียว

### รันด้วย Docker (แนะนำ)
```bash
docker compose up --build
# เปิด http://localhost:5000
```
- `.env`, `credentials.json`, และโฟลเดอร์ `output/` จะถูก mount เข้า container อัตโนมัติ
- barcode ที่ generate จะถูกบันทึกลง `output/` บนเครื่อง host

### รันด้วย Python (ไม่ใช้ Docker)
```bash
pip install -r requirements.txt
python -m loyverse.web.app
# เปิด http://127.0.0.1:5000
```

> ⚠️ Web UI ยังไม่มีระบบ login — รันบน localhost เท่านั้น อย่าเปิดออก public โดยไม่ใส่ authentication ก่อน

---

## File Structure

```
loyverseAPI/
│
├── .env                       ← ค่า config จริง (ห้าม commit ใน git)
├── .env.example               ← template .env สำหรับ setup
├── .gitignore
├── requirements.txt
├── Dockerfile                 ← image สำหรับรัน Web UI (gunicorn)
├── docker-compose.yml         ← รัน Web UI ด้วย docker compose
│
├── loyverse/                  ← Python package หลักของระบบ
│   ├── config.py              ← อ่าน .env และ export ค่า config ทั้งหมด
│   ├── loyverse_api.py        ← Loyverse REST API wrapper
│   ├── sku_generator.py       ← Auto-generate SKU จาก prefix + running number
│   ├── barcode_gen.py         ← สร้าง barcode PNG จาก SKU
│   ├── shared_logic.py        ← Logic กลางที่ใช้ร่วมกันทั้ง 2 step
│   ├── diagnostics.py         ← ตรวจสอบสิทธิ์ Google Sheets (เดิม check_auth.py)
│   │
│   ├── assets/fonts/          ← ฟอนต์สำหรับ barcode (Helvetica.ttf)
│   │
│   ├── sheets/                ← ทุกอย่างที่เกี่ยวกับ Google Sheets
│   │   ├── auth.py            ← Service Account authentication (gspread)
│   │   ├── reader.py          ← อ่านข้อมูลจาก Input Sheet
│   │   └── writer.py          ← เขียน transaction log → CSV หรือ Google Sheet
│   │
│   ├── steps/
│   │   ├── step1_barcode_gen.py   ← Step 1: สร้างสินค้า (สต็อก 0) + Barcode
│   │   ├── step2_stock_update.py  ← Step 2: อัปเดตสต็อกจริงเข้าระบบ
│   │   └── legacy_sync.py         ← (Legacy) รันแบบขั้นตอนเดียว
│   │
│   ├── reports/                ← รายงานสรุปยอดขายแยกตาม Category
│   │   ├── catalog_cache.py    ← cache item_id → category (TTL, ล้างได้ผ่านปุ่มรีเฟรช)
│   │   ├── sales_by_category.py← aggregate() (pure logic) + build_report() + CLI
│   │   └── excel_export.py     ← สร้างไฟล์ .xlsx (2 ชีต) จาก SalesReport
│   │
│   └── web/                   ← Flask Web UI
│       ├── app.py             ← หน้า Input/Run + Transactions + Sales by Category
│       └── templates/         ← HTML templates
│
├── tests/test_project.py      ← test suite (รันโดยไม่ต้องมี credential จริง)
├── tools/dump_items.py        ← script เสริม dump สินค้า/SKU ทั้งหมด (standalone)
├── docs/                      ← เอกสารอ้างอิง API
│
└── output/                    ← ไฟล์ที่ generate (auto-created)
    ├── transactions.csv       ← transaction log (append ทุกครั้งที่รัน)
    └── {YYYYMMDD}/{ชื่อไฟล์ Sheet}/{SKU}.png
```

---

## How It Works (Two-Step Process)

ระบบแบ่งการทำงานออกเป็น 2 ขั้นตอน เพื่อให้สอดคล้องกับ Physical Flow ของการรับสินค้า:

### Step 1: Barcode Generation (`step1_barcode_gen.py`)
1. อ่านแถวที่มีสถานะเป็น **PENDING** (หรือว่าง)
2. ตรวจสอบสินค้าใน Loyverse:
   - ถ้ายังไม่มี: สร้างสินค้าใหม่ (Auto SKU) โดยตั้ง **สต็อกเริ่มต้นเป็น 0**
   - ถ้ามีแล้ว: ดึงข้อมูล SKU เดิม
3. สร้างไฟล์ Barcode PNG พร้อมรายละเอียดสินค้า
4. อัปเดต SKU กลับไปที่ Sheet และเปลี่ยนสถานะเป็น **BARCODE_READY**

### Step 2: Stock Update (`step2_stock_update.py`)
1. อ่านแถวที่มีสถานะเป็น **BARCODE_READY**
2. อัปเดตจำนวนสต็อก (Add Quantity) เข้าสู่ระบบ Loyverse ตามจำนวนในช่อง `total_number`
3. เปลี่ยนสถานะเป็น **COMPLETED**

---

## Google Sheets Setup

### 1. Input Sheet
สร้าง Google Sheet มี header row ดังนี้:

| product_name | sku | total_number | category | Price | Status | Message | Process_State |
|---|---|---|---|---|---|---|---|
| เสื้อยืดขาว |  | 10 | เสื้อผ้า | 250 | | | PENDING |

- **Process_State**: คอลัมน์สำหรับควบคุมขั้นตอน (PENDING -> BARCODE_READY -> COMPLETED)
- **Status / Message**: ระบบจะเขียนผลลัพธ์การทำงานกลับมาให้

### 2. Mapping Sheet
สร้าง Google Sheet แล้วสร้าง tab ชื่อ `Mapping`:

| category | prefix |
|---|---|
| เสื้อผ้า | MM |
| อาหาร | FD |

#### 3c. ถ้าใช้ Private Sheet (TRANSACTION_OUTPUT_MODE=sheets)

1. [Google Cloud Console](https://console.cloud.google.com) → สร้าง Project
2. เปิด **Google Sheets API** และ **Google Drive API**
3. IAM → Service Accounts → สร้าง Service Account → ดาวน์โหลด JSON key → บันทึกเป็น `credentials.json`
4. Share ทุก sheet ให้ `client_email` ใน `credentials.json` → Editor

---

## Running (CLI)

ทางเลือกสำหรับรันแบบ command line (ใช้ `INPUT_SHEET_URL` จาก `.env`):

### 1. ติดตั้ง Dependencies
```bash
pip install -r requirements.txt
```

รันแบบ module จาก root ของโปรเจกต์ (`-m`):

### 2. ขั้นตอนที่ 1: สร้างสินค้าและ Barcode
รันคำสั่งนี้เมื่อต้องการสร้างสินค้าใหม่ในระบบและพิมพ์ Barcode:
```bash
python -m loyverse.steps.step1_barcode_gen
```

### 3. ขั้นตอนที่ 2: อัปเดตสต็อกเมื่อรับสินค้า
รันคำสั่งนี้เมื่อตรวจรับสินค้าจริงเรียบร้อยแล้ว:
```bash
python -m loyverse.steps.step2_stock_update
```

### คำสั่งเสริม
```bash
python -m loyverse.diagnostics      # ตรวจสอบสิทธิ์ Google Sheets
python tests/test_project.py        # รัน test suite

# สรุปยอดขายแยกตาม Category (พิมพ์ลง console และ/หรือ export .xlsx)
python -m loyverse.reports.sales_by_category --from 2026-07-01 --to 2026-07-30 \
       [--category "ร้านเอ" --category "ร้านบี"] [--excel out.xlsx]
```

> Web UI กับ CLI ใช้ logic เดียวกัน (`loyverse/steps/`) —
> ต่างกันแค่ Web UI รับ URL จากหน้าเว็บ ส่วน CLI อ่านจาก `.env`

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `LOYVERSE_TOKEN` | ✅ | — | API token จาก Loyverse Back Office |
| `INPUT_SHEET_URL` | ✅ | — | URL ของ Input Google Sheet |
| `MAPPING_SHEET_URL` | ✅ | — | URL ของ Mapping Google Sheet |
| `SHEET_COL_STATE` | ❌ | `Process_State` | ชื่อคอลัมน์สำหรับเก็บสถานะ (State) |
| `LOYVERSE_STORE_ID` | ❌ | `""` | Store ID (ถ้าไม่ใส่จะ apply ทุก store) |
| `TRANSACTION_OUTPUT_MODE` | ❌ | `csv` | `csv` หรือ `sheets` |
| `SKU_DIGIT_PAD` | ❌ | `3` | จำนวนหลักของ running number |
| `OUTPUT_DIR` | ❌ | `output` | folder สำหรับ output ทั้งหมด |
| `REPORT_TIMEZONE` | ❌ | `Asia/Bangkok` | timezone ที่ใช้ตีความช่วงวันที่ในหน้ารายงาน |
| `REPORT_MAX_RANGE_DAYS` | ❌ | `366` | จำนวนวันสูงสุดที่เลือกดูรายงานได้ในครั้งเดียว |
| `REPORT_CATALOG_TTL_SEC` | ❌ | `600` | อายุ cache ของรายการสินค้า/category (วินาที) ก่อนดึงใหม่ |
| `REPORT_CURRENCY_SYMBOL` | ❌ | `฿` | สัญลักษณ์สกุลเงินที่แสดงในหน้ารายงาน |

---

## Troubleshooting

| ปัญหา | สาเหตุ | วิธีแก้ |
|---|---|---|
| `Missing required env var: LOYVERSE_TOKEN` | ไม่มี `.env` หรือไม่ได้ใส่ token | ตรวจสอบ `.env` |
| `FileNotFoundError: credentials.json` | ใช้ sheets mode แต่ไม่มี key file | เปลี่ยนเป็น `TRANSACTION_OUTPUT_MODE=csv` หรือ ดาวน์โหลด credentials |
| `Category not found in Loyverse` | category ใน Sheet ไม่ตรงกับ Loyverse | ตรวจสอบชื่อ category ให้ตรงกัน |
| `prefix not found in Mapping Sheet` | category ไม่ได้ map prefix ใน Mapping Sheet | เพิ่ม row ใน Mapping Sheet |
| `403 Forbidden` (gspread) | Service account ไม่ได้รับ share sheet | Share sheet ให้ `client_email` เป็น Editor |
| `Row skipped` | `Process_State` ไม่ถูกต้อง | ตรวจสอบว่าแถวที่ต้องการรันมีสถานะเป็น `PENDING` (สำหรับ Step 1) หรือ `BARCODE_READY` (สำหรับ Step 2) |

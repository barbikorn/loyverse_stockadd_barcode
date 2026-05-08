# loyverseAPI

> ระบบ sync สินค้าจาก **Google Sheet → Loyverse POS** พร้อม auto-SKU, barcode generation และ transaction log

---

## File Structure

```
loyverseAPI/
│
├── .env                    ← ค่า config จริง (ห้าม commit ใน git)
├── .env.example            ← template .env สำหรับ setup
├── .gitignore
│
├── config.py               ← อ่าน .env และ export ค่า config ทั้งหมด
│                             (module นี้คือตัวกลางที่ทุก module อ่านค่าจาก)
│
├── sheets_auth.py          ← Google Service Account authentication (gspread)
├── sheets.py               ← อ่านข้อมูลจาก Input Sheet
├── sheets_writer.py        ← เขียน transaction log → CSV หรือ Google Sheet
│
├── loyverse_api.py         ← Loyverse REST API wrapper
│                             (categories, items, inventory, SKU lookup)
│
├── sku_generator.py        ← Auto-generate SKU จาก prefix + running number
├── barcode_gen.py          ← สร้าง barcode PNG จาก SKU
├── loyverse_sync.py        ← Main pipeline — รันตรงนี้
│
├── test_project.py         ← Test suite (31 tests, ไม่ต้องใช้ API จริง)
│
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
│
├── docs/
│   └── api_doc.txt         ← Loyverse API reference
│
└── output/                 ← ไฟล์ที่ generate (auto-created)
    ├── transactions.csv    ← transaction log (append ทุกครั้งที่รัน)
    ├── loyverse_sync_report_YYYYMMDD_HHMMSS.xlsx
    └── barcodes_YYYYMMDD_HHMMSS/
        └── {SKU}.png
```

---

## How It Works

```
[Google Sheet: Input]
  product_name | sku | total_number | category
        ↓
[loyverse_sync.py] per row:
  ├─ มี SKU?  → find by SKU → update stock
  ├─ มีชื่อ?  → find by name → update stock
  └─ ใหม่?   → validate category → get prefix from Mapping Sheet
              → auto-generate SKU (e.g. MM001)
              → create item in Loyverse
        ↓
[output/]
  ├─ transactions.csv (or Google Sheet)
  ├─ report .xlsx
  └─ barcodes/*.png
```

---

## Quick Setup

### 1. ติดตั้ง dependencies

```bash
pip install -r requirements.txt
```

### 2. ตั้งค่า .env

```bash
# Windows
copy .env.example .env

# Mac / Linux
cp .env.example .env
```

แก้ไข `.env`:

```env
# จำเป็นต้องใส่
LOYVERSE_TOKEN=<token จาก Loyverse Back Office → Settings → API>
INPUT_SHEET_URL=<URL ของ Google Sheet ที่เป็น Input>
MAPPING_SHEET_URL=<URL ของ Google Sheet ที่เก็บ category→prefix mapping>

# Transaction output (เลือกหนึ่งอย่าง)
TRANSACTION_OUTPUT_MODE=csv         # ← ไม่ต้องใช้ credentials (แนะนำ)
# TRANSACTION_OUTPUT_MODE=sheets    # ← ต้องใช้ credentials.json
```

### 3. Google Sheets Setup

#### 3a. Input Sheet
สร้าง Google Sheet มี header row:

| product_name | sku | total_number | category |
|---|---|---|---|
| เสื้อยืดขาว | MM001 | 10 | เสื้อผ้า |
| ข้าวผัด |  | 5 | อาหาร |

- **มี SKU** → ค้นหาใน Loyverse แล้ว update stock
- **ไม่มี SKU** → สร้างสินค้าใหม่พร้อม auto-generate SKU

#### 3b. Mapping Sheet
สร้าง Google Sheet แล้วสร้าง tab ชื่อ `Mapping`:

| category | prefix |
|---|---|
| เสื้อผ้า | MM |
| อาหาร | FD |
| เครื่องดื่ม | BV |

#### 3c. ถ้าใช้ Private Sheet (TRANSACTION_OUTPUT_MODE=sheets)

1. [Google Cloud Console](https://console.cloud.google.com) → สร้าง Project
2. เปิด **Google Sheets API** และ **Google Drive API**
3. IAM → Service Accounts → สร้าง Service Account → ดาวน์โหลด JSON key → บันทึกเป็น `credentials.json`
4. Share ทุก sheet ให้ `client_email` ใน `credentials.json` → Editor

---

## Running

### Local

```bash
python loyverse_sync.py
```

### Docker

```bash
# ครั้งแรก (หรือหลังแก้ code)
docker compose up --build

# ครั้งต่อไป
docker compose up

# ดู log
docker compose logs -f
```

### Run Tests

```bash
python test_project.py
```
> ไม่ต้องใช้ Loyverse API จริง หรือ credentials.json จริง

---

## SKU Format

- **Format**: `{prefix}{3-digit number}` เช่น `MM001`, `FD042`
- **Prefix** → มาจาก Mapping Sheet ตาม category
- **Auto-increment**: ดึง SKU ล่าสุดใน category แล้ว +1
- **First item**: เริ่มที่ `001`

```
category: "เสื้อผ้า" → prefix: "MM"
ไม่มีสินค้าก่อน → SKU = MM001
มี MM001, MM002 → SKU = MM003
```

---

## Output Files

ทุกการรันจะสร้างไฟล์ใน `output/`:

| ไฟล์ | คำอธิบาย |
|---|---|
| `transactions.csv` | log ทุก row (Success + Error) — append ทุกครั้งที่รัน |
| `loyverse_sync_report_*.xlsx` | Excel summary ของ run นั้น |
| `barcodes_*/{SKU}.png` | barcode PNG สำหรับ print |

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `LOYVERSE_TOKEN` | ✅ | — | API token จาก Loyverse Back Office |
| `INPUT_SHEET_URL` | ✅ | — | URL ของ Input Google Sheet |
| `MAPPING_SHEET_URL` | ✅ | — | URL ของ Mapping Google Sheet |
| `LOYVERSE_STORE_ID` | ❌ | `""` | Store ID (ถ้าไม่ใส่จะ apply ทุก store) |
| `TRANSACTION_OUTPUT_MODE` | ❌ | `csv` | `csv` หรือ `sheets` |
| `TRANSACTION_CSV_PATH` | ❌ | `output/transactions.csv` | path ของ CSV log |
| `TRANSACTION_SHEET_URL` | ❌ | — | URL สำหรับ sheets mode เท่านั้น |
| `GOOGLE_CREDENTIALS_FILE` | ❌ | `credentials.json` | path ของ Service Account key |
| `SKU_DIGIT_PAD` | ❌ | `3` | จำนวนหลักของ running number |
| `OUTPUT_DIR` | ❌ | `output` | folder สำหรับ output ทั้งหมด |

---

## Troubleshooting

| ปัญหา | สาเหตุ | วิธีแก้ |
|---|---|---|
| `Missing required env var: LOYVERSE_TOKEN` | ไม่มี `.env` หรือไม่ได้ใส่ token | ตรวจสอบ `.env` |
| `FileNotFoundError: credentials.json` | ใช้ sheets mode แต่ไม่มี key file | เปลี่ยนเป็น `TRANSACTION_OUTPUT_MODE=csv` หรือ ดาวน์โหลด credentials |
| `Category not found in Loyverse` | category ใน Sheet ไม่ตรงกับ Loyverse | ตรวจสอบชื่อ category ให้ตรงกัน |
| `prefix not found in Mapping Sheet` | category ไม่ได้ map prefix ใน Mapping Sheet | เพิ่ม row ใน Mapping Sheet |
| `403 Forbidden` (gspread) | Service account ไม่ได้รับ share sheet | Share sheet ให้ `client_email` เป็น Editor |

"""
sales_by_category.py — สรุปยอดขายแยกตาม Category (= เจ้าของสินค้าฝากขาย)

aggregate() เป็น pure function: รับ receipts + catalog (ไม่ยิง API) → คืน SalesReport
build_report() ทำ I/O: แปลงวันที่ท้องถิ่น → ช่วง UTC, ดึง catalog + receipts จริง แล้วเรียก aggregate()

รันจาก CLI:
    python -m loyverse.reports.sales_by_category --from 2026-07-01 --to 2026-07-30 \
           [--category "ร้านเอ" --category "ร้านบี"] [--excel out.xlsx]
"""

import argparse
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Iterable

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover — Python เก่ากว่า 3.9 ไม่มี stdlib zoneinfo
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception

from loyverse import config
from loyverse import loyverse_api as lv
from loyverse.reports.catalog_cache import Catalog, get_catalog

DELETED_ITEM_CATEGORY_NAME = "(สินค้าถูกลบ)"


def _num(x) -> float:
    return float(x or 0)


@dataclass
class ItemRow:
    sku: str
    item_name: str
    variant_name: str
    qty_sold: float = 0.0
    gross_sales: float = 0.0
    discounts: float = 0.0
    net_sales: float = 0.0
    # ราคา/หน่วย: ถ้าขายหลายบิลในราคาต่างกัน จะเป็นค่าเฉลี่ยถ่วงน้ำหนัก (gross / qty)
    unit_price: float = 0.0


@dataclass
class CategoryRow:
    category_id: str | None
    category_name: str
    qty_sold: float = 0.0
    gross_sales: float = 0.0
    discounts: float = 0.0
    net_sales: float = 0.0
    share_pct: float = 0.0
    receipts_count: int = 0
    items: list[ItemRow] = field(default_factory=list)


@dataclass
class SalesReport:
    date_from: date
    date_to: date
    tz_name: str
    category_filter: list[str]                 # [] = ทุก category
    rows: list[CategoryRow]                     # เรียง net_sales มาก→น้อย
    totals: CategoryRow
    receipts_scanned: int
    refunds_scanned: int
    cancelled_skipped: int
    generated_at: datetime


# ─── Timezone helpers ──────────────────────────────────────────

def _get_timezone(tz_name: str):
    if ZoneInfo is not None:
        try:
            return ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            pass
    # fallback: UTC+7 คงที่ (Asia/Bangkok ไม่มี DST) เผื่อเครื่อง Windows ไม่มี tz database
    return timezone(timedelta(hours=7))


def _fmt_utc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def today_in_tz(tz_name: str | None = None) -> date:
    """คืนวันที่ 'วันนี้' ตาม timezone ของรายงาน (ใช้ตั้งค่า default ช่วงวันบนหน้าเว็บ)"""
    tz = _get_timezone(tz_name or config.REPORT_TIMEZONE)
    return datetime.now(tz).date()


def utc_range(date_from: date, date_to: date, tz_name: str | None = None) -> tuple[str, str]:
    """
    แปลงช่วงวันที่ท้องถิ่น (inclusive ทั้งสองด้าน) → (created_at_min, created_at_max) UTC ISO8601
    เช่น Asia/Bangkok 2026-07-01..2026-07-01 → 2026-06-30T17:00:00.000Z .. 2026-07-01T16:59:59.999Z
    """
    tz = _get_timezone(tz_name or config.REPORT_TIMEZONE)
    start_local = datetime.combine(date_from, time.min, tz)
    end_local_exclusive = datetime.combine(date_to + timedelta(days=1), time.min, tz)

    start_utc = start_local.astimezone(timezone.utc)
    end_utc = (end_local_exclusive - timedelta(milliseconds=1)).astimezone(timezone.utc)

    return _fmt_utc(start_utc), _fmt_utc(end_utc)


# ─── Core aggregation (pure — ไม่ยิง API) ──────────────────────

def aggregate(
    receipts: Iterable[dict],
    catalog: Catalog,
    *,
    date_from: date,
    date_to: date,
    tz_name: str,
    category_ids: list[str] | None = None,
) -> SalesReport:
    """
    รวมยอดขายจาก receipts ที่ให้มา (ต้องกรองช่วงวันที่มาก่อนแล้วจากฝั่งเรียก)
    - ตัด receipt ที่ cancelled_at ออก
    - REFUND หักออกจากยอด (sign = -1)
    - join line_item.item_id กับ catalog.items เพื่อหา category
    - item_id ที่หาไม่เจอใน catalog → เข้า bucket "(สินค้าถูกลบ)"
    """
    category_filter = sorted(category_ids) if category_ids else []
    filter_set = set(category_ids) if category_ids else None

    rows_by_cat: dict[object, CategoryRow] = {}
    items_by_cat: dict[object, dict[object, ItemRow]] = {}
    receipt_ids_by_cat: dict[object, set] = {}

    receipts_scanned = 0
    refunds_scanned = 0
    cancelled_skipped = 0

    for receipt in receipts:
        if receipt.get("cancelled_at"):
            cancelled_skipped += 1
            continue

        is_refund = receipt.get("receipt_type") == "REFUND"
        sign = -1.0 if is_refund else 1.0
        receipts_scanned += 1
        if is_refund:
            refunds_scanned += 1

        receipt_number = receipt.get("receipt_number")

        for line in receipt.get("line_items", []):
            item_id = line.get("item_id")
            info = catalog.items.get(item_id)
            if info is not None:
                category_id = info.category_id
                category_name = info.category_name
                item_name = info.item_name
            else:
                category_id = None
                category_name = DELETED_ITEM_CATEGORY_NAME
                item_name = line.get("item_name", "")

            if filter_set is not None and category_id not in filter_set:
                continue

            row = rows_by_cat.get(category_id)
            if row is None:
                row = CategoryRow(category_id=category_id, category_name=category_name)
                rows_by_cat[category_id] = row
                items_by_cat[category_id] = {}
                receipt_ids_by_cat[category_id] = set()

            qty = _num(line.get("quantity")) * sign
            gross = _num(line.get("gross_total_money")) * sign
            discount = _num(line.get("total_discount")) * sign
            net = _num(line.get("total_money")) * sign

            row.qty_sold += qty
            row.gross_sales += gross
            row.discounts += discount
            row.net_sales += net

            if receipt_number:
                receipt_ids_by_cat[category_id].add(receipt_number)

            sku = line.get("sku", "") or ""
            variant_name = line.get("variant_name") or ""
            item_key = line.get("variant_id") or sku or item_id

            item_map = items_by_cat[category_id]
            item_row = item_map.get(item_key)
            if item_row is None:
                item_row = ItemRow(sku=sku, item_name=item_name, variant_name=variant_name)
                item_map[item_key] = item_row
            item_row.qty_sold += qty
            item_row.gross_sales += gross
            item_row.discounts += discount
            item_row.net_sales += net
            # เก็บราคาตั้งไว้เป็น fallback เผื่อ qty สุทธิเป็น 0 (ขายแล้วคืนหมด)
            if line.get("price") is not None:
                item_row.unit_price = _num(line.get("price"))

    for category_id, row in rows_by_cat.items():
        row.receipts_count = len(receipt_ids_by_cat[category_id])
        for item_row in items_by_cat[category_id].values():
            if item_row.qty_sold:
                item_row.unit_price = item_row.gross_sales / item_row.qty_sold
        row.items = sorted(
            items_by_cat[category_id].values(), key=lambda r: r.net_sales, reverse=True
        )

    rows = sorted(rows_by_cat.values(), key=lambda r: r.net_sales, reverse=True)

    total_net = sum(r.net_sales for r in rows)
    for row in rows:
        row.share_pct = (row.net_sales / total_net * 100) if total_net else 0.0

    all_receipt_numbers: set = set()
    for s in receipt_ids_by_cat.values():
        all_receipt_numbers |= s

    totals = CategoryRow(
        category_id=None,
        category_name="รวมทั้งหมด",
        qty_sold=sum(r.qty_sold for r in rows),
        gross_sales=sum(r.gross_sales for r in rows),
        discounts=sum(r.discounts for r in rows),
        net_sales=total_net,
        share_pct=100.0 if rows else 0.0,
        receipts_count=len(all_receipt_numbers),
    )

    return SalesReport(
        date_from=date_from,
        date_to=date_to,
        tz_name=tz_name,
        category_filter=category_filter,
        rows=rows,
        totals=totals,
        receipts_scanned=receipts_scanned,
        refunds_scanned=refunds_scanned,
        cancelled_skipped=cancelled_skipped,
        generated_at=datetime.now(timezone.utc),
    )


# ─── I/O wrapper ────────────────────────────────────────────────

def build_report(
    date_from: date,
    date_to: date,
    category_ids: list[str] | None = None,
    progress: Callable | None = None,
) -> SalesReport:
    """ทำ I/O จริง: local date → UTC range → ดึง catalog + receipts → aggregate()"""
    tz_name = config.REPORT_TIMEZONE

    if progress:
        progress({"type": "start", "message": "กำลังโหลดแคตตาล็อกสินค้า..."})
    catalog = get_catalog()

    created_at_min, created_at_max = utc_range(date_from, date_to, tz_name)

    if progress:
        progress({"type": "item", "message": "กำลังดึงข้อมูลการขาย..."})
    receipts = lv.iter_receipts(created_at_min, created_at_max)

    report = aggregate(
        receipts, catalog,
        date_from=date_from, date_to=date_to, tz_name=tz_name,
        category_ids=category_ids,
    )

    if progress:
        progress({"type": "summary", "report": report})

    return report


# ─── CLI entry point ───────────────────────────────────────────

def _print_report(report: SalesReport) -> None:
    print(f"\n📊 สรุปยอดขายตาม Category: {report.date_from} .. {report.date_to} ({report.tz_name})")
    print(f"   receipts ที่สแกน: {report.receipts_scanned} (refund: {report.refunds_scanned}, "
          f"ยกเลิกและตัดออก: {report.cancelled_skipped})\n")

    header = f"{'Category':30} {'จำนวน':>10} {'Gross':>14} {'ส่วนลด':>12} {'สุทธิ':>14} {'สัดส่วน':>8} {'บิล':>6}"
    print(header)
    print("-" * len(header))
    for row in report.rows:
        print(f"{row.category_name[:30]:30} {row.qty_sold:>10.2f} {row.gross_sales:>14,.2f} "
              f"{row.discounts:>12,.2f} {row.net_sales:>14,.2f} {row.share_pct:>7.2f}% {row.receipts_count:>6}")
    print("-" * len(header))
    t = report.totals
    print(f"{t.category_name[:30]:30} {t.qty_sold:>10.2f} {t.gross_sales:>14,.2f} "
          f"{t.discounts:>12,.2f} {t.net_sales:>14,.2f} {t.share_pct:>7.2f}% {t.receipts_count:>6}")
    print("\n✅ เสร็จสิ้น")


def main() -> None:
    parser = argparse.ArgumentParser(description="สรุปยอดขายแยกตาม Category (เจ้าของสินค้าฝากขาย)")
    parser.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
    parser.add_argument("--category", dest="categories", action="append", default=None,
                        help="ชื่อ category (ระบุซ้ำได้หลายตัว) — ไม่ระบุ = ทุก category")
    parser.add_argument("--excel", dest="excel_path", default=None, help="path ไฟล์ .xlsx ที่จะบันทึก")
    args = parser.parse_args()

    date_from = date.fromisoformat(args.date_from)
    date_to = date.fromisoformat(args.date_to)

    category_ids = None
    if args.categories:
        catalog = get_catalog()
        name_to_id = {name.lower(): cid for cid, name in catalog.categories}
        category_ids = []
        for name in args.categories:
            cid = name_to_id.get(name.strip().lower())
            if not cid:
                print(f"⚠️  ไม่พบ category ชื่อ '{name}' — ข้าม")
                continue
            category_ids.append(cid)

    report = build_report(date_from, date_to, category_ids=category_ids)
    _print_report(report)

    if args.excel_path:
        from loyverse.reports import excel_export
        wb_bytes = excel_export.build_workbook(report)
        with open(args.excel_path, "wb") as f:
            f.write(wb_bytes.getvalue())
        print(f"📄 บันทึกไฟล์ Excel: {args.excel_path}")


if __name__ == "__main__":
    main()

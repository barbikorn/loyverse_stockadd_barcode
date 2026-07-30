"""barcode_gen.py — Barcode PNG generator with Label

Layout template:
    [ Barcode Image      ]   (centered)
    (category) name          (centered, single line — font shrinks to fit)
    price                    (centered, e.g. "30.-" or "30.50.-")
"""

import re
import os
from pathlib import Path
import barcode
from barcode.writer import ImageWriter

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("⚠️  Pillow (PIL) not installed. Barcodes will be simple (no text labels).")

_FONTS_DIR = Path(__file__).resolve().parent / "assets" / "fonts"


def _resolve_helvetica() -> str:
    """Helvetica (regular weight only). Falls back to bundled fonts/Helvetica.ttf."""
    candidates = [
        _FONTS_DIR / "Helvetica.ttf",
        Path("C:/Windows/Fonts/Helvetica.ttf"),
        Path("C:/Windows/Fonts/helvetica.ttf"),
        Path("C:/Windows/Fonts/HelveticaNeue.ttf"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Windows/Fonts/Helvetica.ttf",
        Path("/System/Library/Fonts/Helvetica.ttc"),
        Path("/Library/Fonts/Helvetica.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return str(_FONTS_DIR / "Helvetica.ttf")


FONT_PATH = _resolve_helvetica()


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", str(name)).strip()


def _wrap_text(text: str, font, max_width: int, draw) -> list[str]:
    """Wrap text to fit max_width"""
    if not text:
        return []

    words = text.split(' ')
    lines: list[str] = []
    current_line = words[0]

    for word in words[1:]:
        candidate = current_line + " " + word
        bbox = draw.textbbox((0, 0), candidate, font=font)
        w = bbox[2] - bbox[0]
        if w <= max_width:
            current_line = candidate
        else:
            lines.append(current_line)
            current_line = word
    lines.append(current_line)
    return lines


def _format_price(price: float) -> str:
    """Format price like '30.-' for whole numbers, '30.50.-' otherwise."""
    try:
        value = float(price)
    except (TypeError, ValueError):
        return f"{price}.-"
    if value.is_integer():
        return f"{int(value)}.-"
    return f"{value:,.2f}.-"


def generate(
    sku: str,
    output_dir: Path,
    product_name: str = "",
    price: float = 0.0,
    variant_name: str = "",
    category: str = "",
) -> str | None:
    """
    Generate barcode PNG with label.

    Layout:
        [Barcode Image]
        (category) name
        price
    """
    if not sku:
        return None

    if not HAS_PIL:
        try:
            Code128 = barcode.get_barcode_class("code128")
            filepath = output_dir / _safe_filename(sku)
            Code128(sku, writer=ImageWriter()).save(str(filepath))
            return str(filepath) + ".png"
        except Exception as e:
            print(f"  ⚠️  สร้าง barcode ไม่สำเร็จ ({sku}): {e}")
            return None

    try:
        Code128 = barcode.get_barcode_class("code128")
        writer = ImageWriter()
        bc = Code128(sku, writer=writer)
        bc_img = bc.render(writer_options={
            "write_text": False,
            "module_height": 8.0,
            "quiet_zone": 1.0,
            "font_path": FONT_PATH,
        })

        width = bc_img.width

        try:
            font_name = ImageFont.truetype(FONT_PATH, 14)
            font_price = ImageFont.truetype(FONT_PATH, 30)
        except IOError:
            font_name = ImageFont.load_default()
            font_price = ImageFont.load_default()

        padding = 10
        padding_bottom = 24
        line_spacing = 6

        dummy_img = Image.new("RGB", (1, 1))
        dummy_draw = ImageDraw.Draw(dummy_img)

        def text_size(text: str, font) -> tuple[int, int]:
            bbox = dummy_draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]

        if category:
            name_text = f"({category}) {product_name}".strip()
        else:
            name_text = product_name or ""

        if variant_name:
            name_text = f"{name_text} {variant_name}".strip()

        # Wrap name to fit width (no font shrinking)
        max_name_width = width - 2 * padding
        name_lines = _wrap_text(name_text, font_name, max_name_width, dummy_draw)
        h_name_total = 0
        for line in name_lines:
            _, h = text_size(line, font_name)
            h_name_total += h + line_spacing

        price_text = _format_price(price)
        _, h_price = text_size(price_text, font_price)

        total_height = (
            padding
            + bc_img.height + line_spacing
            + h_name_total + line_spacing
            + h_price
            + padding_bottom
        )

        canvas = Image.new("RGB", (width, int(total_height)), "white")
        draw = ImageDraw.Draw(canvas)

        y = padding

        canvas.paste(bc_img, (0, int(y)))
        y += bc_img.height + line_spacing

        for line in name_lines:
            w_line, h_line = text_size(line, font_name)
            draw.text(((width - w_line) / 2, y), line, fill="black", font=font_name)
            y += h_line + line_spacing

        w_price, _ = text_size(price_text, font_price)
        draw.text(((width - w_price) / 2, y), price_text, fill="black", font=font_price)

        filename = _safe_filename(sku) + ".png"
        filepath = output_dir / filename
        canvas.save(filepath)

        print(f"  🖼️  barcode: {filename}")
        return str(filepath)

    except Exception as e:
        print(f"  ⚠️  สร้าง barcode ไม่สำเร็จ ({sku}): {e}")
        return None

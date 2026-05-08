"""barcode_gen.py — Barcode PNG generator with Label (Price/Name)"""

import re
import os
from pathlib import Path
import barcode
from barcode.writer import ImageWriter

# Try to import PIL
try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("⚠️  Pillow (PIL) not installed. Barcodes will be simple (no text labels).")

# Try to load Thai-compatible font
FONT_PATH = "C:/Windows/Fonts/tahoma.ttf"
if not os.path.exists(FONT_PATH):
    FONT_PATH = "C:/Windows/Fonts/leelawad.ttf"  # Leelawadee
if not os.path.exists(FONT_PATH):
    FONT_PATH = "arial.ttf" # Fallback

def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", str(name)).strip()

def _wrap_text(text: str, font, max_width: int, draw) -> list[str]:
    """Wrap text to fit max_width"""
    lines = []
    if not text:
        return lines
        
    words = text.split(' ')
    current_line = words[0]
    
    for word in words[1:]:
        # Check size
        bbox = draw.textbbox((0, 0), current_line + " " + word, font=font)
        w = bbox[2] - bbox[0]
        if w <= max_width:
            current_line += " " + word
        else:
            lines.append(current_line)
            current_line = word
    lines.append(current_line)
    return lines

def generate(
    sku: str, 
    output_dir: Path, 
    product_name: str = "", 
    price: float = 0.0, 
    variant_name: str = ""
) -> str | None:
    """
    สร้าง barcode PNG พร้อมรายละเอียดสินค้า (Label)
    Layout:
      [SKU]
      [Price]
      [Name]
      [Variant]
      [Barcode Image]
    """
    if not sku:
        return None

    # Fallback if PIL is missing
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
        # 1. Generate Barcode Image (Temporary)
        Code128 = barcode.get_barcode_class("code128")
        writer = ImageWriter()
        # Create barcode object
        bc = Code128(sku, writer=writer)
        
        # Render to PIL Image directly
        # options: write_text=False (we draw text ourselves), quiet_zone=1.0
        bc_img = bc.render(writer_options={"write_text": False, "module_height": 8.0, "quiet_zone": 1.0})
        
        # 2. Setup Canvas
        width = bc_img.width
        
        # Font setup
        try:
            # Adjust font sizes relative to barcode width if needed, but fixed size is usually okay for labels
            font_sku = ImageFont.truetype(FONT_PATH, 28)
            font_price = ImageFont.truetype(FONT_PATH, 24)
            font_name = ImageFont.truetype(FONT_PATH, 22)
            font_var = ImageFont.truetype(FONT_PATH, 20)
        except IOError:
            font_sku = ImageFont.load_default()
            font_price = ImageFont.load_default()
            font_name = ImageFont.load_default()
            font_var = ImageFont.load_default()

        padding = 10
        line_spacing = 4
        
        # Calculate text heights
        dummy_img = Image.new("RGB", (1, 1))
        dummy_draw = ImageDraw.Draw(dummy_img)
        
        def get_text_height(text, font):
            bbox = dummy_draw.textbbox((0, 0), text, font=font)
            return bbox[3] - bbox[1]

        # SKU
        sku_text = sku
        h_sku = get_text_height(sku_text, font_sku)
        
        # Price
        price_text = f"ราคา : {price:,.2f} บาท"
        h_price = get_text_height(price_text, font_price)
        
        # Name (Wrapped)
        name_text = f"ชื่อ : {product_name}"
        name_lines = _wrap_text(name_text, font_name, width - 2*padding, dummy_draw)
        h_name_total = 0
        for line in name_lines:
            h_name_total += get_text_height(line, font_name) + line_spacing
        
        # Variant (Wrapped)
        var_lines = []
        if variant_name:
            var_lines = _wrap_text(variant_name, font_var, width - 2*padding, dummy_draw)
        h_var_total = 0
        for line in var_lines:
            h_var_total += get_text_height(line, font_var) + line_spacing

        # Total Height
        # Layout: Barcode -> SKU -> Price -> Name -> Variant
        total_height = (
            padding + 
            bc_img.height + line_spacing +
            h_sku + line_spacing + 
            h_price + line_spacing + 
            h_name_total + 
            h_var_total + 
            padding
        )
        
        # Create Canvas
        canvas = Image.new("RGB", (width, int(total_height)), "white")
        draw = ImageDraw.Draw(canvas)
        
        y = padding
        
        # Draw Barcode
        canvas.paste(bc_img, (0, int(y)))
        y += bc_img.height + line_spacing

        # Draw SKU (Centered)
        w_sku = dummy_draw.textlength(sku_text, font=font_sku)
        draw.text(((width - w_sku) / 2, y), sku_text, fill="black", font=font_sku)
        y += h_sku + line_spacing
        
        # Draw Price (Left aligned)
        draw.text((padding, y), price_text, fill="black", font=font_price)
        y += h_price + line_spacing
        
        # Draw Name
        for line in name_lines:
            draw.text((padding, y), line, fill="black", font=font_name)
            y += get_text_height(line, font_name) + line_spacing
            
        # Draw Variant
        for line in var_lines:
            draw.text((padding, y), line, fill="black", font=font_var)
            y += get_text_height(line, font_var) + line_spacing
        
        # Save
        filename = _safe_filename(sku) + ".png"
        filepath = output_dir / filename
        canvas.save(filepath)
        
        print(f"  🖼️  barcode: {filename}")
        return str(filepath)
        
    except Exception as e:
        print(f"  ⚠️  สร้าง barcode ไม่สำเร็จ ({sku}): {e}")
        return None

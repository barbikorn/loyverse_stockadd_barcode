import requests
import time

# --- Configuration ---
API_TOKEN = 'xxxxxxxxxxxxxxxxxxxxxxx' # นำ token จาก Back Office มาใส่ที่นี่
BASE_URL = 'https://api.loyverse.com/v1.0'
HEADERS = {
    'Authorization': f'Bearer {API_TOKEN}',
    'Content-Type': 'application/json'
}

def get_all_products_and_skus():
    all_data = []
    cursor = None
    
    print("🚀 เริ่มการดึงข้อมูลจาก Loyverse API...")

    while True:
        # กำหนด Params สำหรับ Pagination
        params = {'limit': 250} # ดึงสูงสุดต่อรอบคือ 250 items
        if cursor:
            params['cursor'] = cursor

        try:
            response = requests.get(f"{BASE_URL}/items", headers=HEADERS, params=params)
            
            # ตรวจสอบ Rate Limit (429)
            if response.status_code == 429:
                print("⚠️ Rate limit hit! รอ 5 วินาที...")
                time.sleep(5)
                continue
                
            response.raise_for_status()
            data = response.json()
            
            items = data.get('items', [])
            for item in items:
                item_name = item.get('item_name')
                
                # สินค้า 1 อย่างใน Loyverse จะมีอย่างน้อย 1 Variant เสมอ
                for variant in item.get('variants', []):
                    sku = variant.get('sku')
                    variant_name = variant.get('option1_value') or "Default"
                    
                    all_data.append({
                        "product_name": item_name,
                        "variant_name": variant_name,
                        "sku": sku if sku else "N/A"
                    })

            # เช็คว่ามีหน้าถัดไปไหม
            cursor = data.get('cursor')
            if not cursor:
                break
                
            print(f"📦 ดึงข้อมูลแล้ว {len(all_data)} รายการ...")

        except requests.exceptions.RequestException as e:
            print(f"❌ Error: {e}")
            break

    return all_data

# --- Execution ---
products = get_all_products_and_skus()

print("\n--- สรุปรายการสินค้าและ SKU ---")
for p in products:
    print(f"Item: {p['product_name']} ({p['variant_name']}) | SKU: {p['sku']}")
print(f"\n✅ รวมทั้งหมด {len(products)} รายการ")

import json
import gspread
import config
import sheets_auth

def check():
    print("🔍 กำลังตรวจสอบสิทธิ์การเข้าถึง Google Sheets...")
    print(f"📂 Credentials file: {config.GOOGLE_CREDENTIALS_FILE}")

    try:
        # 1. หา Email ของ Service Account
        with open(config.GOOGLE_CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
            creds = json.load(f)
            email = creds.get('client_email')
        
        print(f"\n📧 Service Account Email: {email}")
        print(f"👉 กรุณานำอีเมลนี้ไปกด 'Share' (แชร์) ใน Google Sheet ที่ต้องการใช้งาน")
        print(f"👉 เลือกสิทธิ์เป็น 'Editor' (เอเดิเตอร์/ผู้มีสิทธิ์แก้ไข)")

        # 2. ทดสอบการเชื่อมต่อ
        client = sheets_auth.get_client()
        
        # 3. ตรวจสอบ Transaction Sheet
        if config.TRANSACTION_SHEET_URL:
            print(f"\n📄 กำลังตรวจสอบ Transaction Sheet URL: {config.TRANSACTION_SHEET_URL}")
            try:
                sh = client.open_by_url(config.TRANSACTION_SHEET_URL)
                print(f"✅ เข้าถึงได้สำเร็จ: {sh.title}")
            except gspread.exceptions.PermissionError:
                print(f"❌ PermissionError: เข้าถึงไม่ได้")
                print(f"   สาเหตุ: ยังไม่ได้แชร์ Sheet ให้กับ {email}")
            except gspread.exceptions.SpreadsheetNotFound:
                print(f"❌ SpreadsheetNotFound: ไม่พบ Sheet (URL อาจผิด หรือไม่ได้แชร์)")
            except Exception as e:
                print(f"❌ Error อื่นๆ: {e}")
        else:
            print("\n⚠️ ไม่ได้ตั้งค่า TRANSACTION_SHEET_URL ใน .env")

    except FileNotFoundError:
        print(f"❌ ไม่พบไฟล์ {config.GOOGLE_CREDENTIALS_FILE}")
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาด: {e}")

if __name__ == "__main__":
    check()

import os
import json
import time
import random
from datetime import datetime, date
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from playwright.sync_api import sync_playwright

# 1. Google Sheets Ulash
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.loads(os.getenv("GOOGLE_CREDENTIALS"))
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

doc = client.open_by_key(os.getenv("SPREADSHEET_ID")) # Yoki client.open("Outreach Leads")
leads_sheet = doc.get_worksheet(0)
limits_sheet = doc.get_worksheet(1)

# XABARLAR ORASIDAGI GLOBAL INTERVAL (8 - 15 daqiqa)
MIN_DELAY = 8 * 60
MAX_DELAY = 15 * 60

def parse_cookies(env_name):
    raw_data = os.getenv(env_name)
    if not raw_data:
        print(f"⚠️ LOG: {env_name} o'zgaruvchisi topilmadi yoki bo'sh!")
        return []
    parsed = json.loads(raw_data)
    return parsed if isinstance(parsed, list) else parsed.get("cookies", [])

def clean_username(user):
    return str(user).replace("@", "").strip().lower()

def check_and_update_limits():
    today_str = str(date.today())
    limits_data = limits_sheet.get_all_records()
    
    for idx, row in enumerate(limits_data, start=2):
        last_date = str(row["Last_Reset_Date"])
        if last_date != today_str:
            new_limit = int(row["Daily_Limit"]) + 1  # Har kuni +1 DM
            limits_sheet.update_cell(idx, 2, new_limit)
            limits_sheet.update_cell(idx, 3, 0)         # Today_Sent reset
            limits_sheet.update_cell(idx, 4, today_str)  # Last_Reset_Date
            print(f"🔄 LOG: {row['Platform']} uchun yangi kun limitlari yangilandi: Limit={new_limit}")

def can_send(platform):
    check_and_update_limits()
    limits_data = limits_sheet.get_all_records()
    for row in limits_data:
        if row["Platform"].upper() == platform.upper():
            sent = int(row["Today_Sent"])
            limit = int(row["Daily_Limit"])
            print(f"📊 LOG [{platform}]: Bugun yuborildi={sent}/{limit}")
            return sent < limit
    print(f"⚠️ LOG: {platform} platformasi Sheet2 da topilmadi!")
    return False

def increment_today_sent(platform):
    limits_data = limits_sheet.get_all_records()
    for idx, row in enumerate(limits_data, start=2):
        if row["Platform"].upper() == platform.upper():
            current_sent = int(row["Today_Sent"])
            limits_sheet.update_cell(idx, 3, current_sent + 1)
            print(f"📈 LOG: {platform} hisoblagichi oshirildi: {current_sent + 1}")
            break

def run_outreach_loop():
    print("\n==================================================")
    print("🚀 24/7 Outreach Engine Start Olmoqda...")
    print("==================================================\n")
    
    with sync_playwright() as p:
        proxy_url = os.getenv("PROXY_SERVER")
        print(f"🌐 LOG: Proxy server holati: {'Ulangan' if proxy_url else 'Ishlatilmayapti'}")
        
        browser = p.chromium.launch(
            headless=True,
            proxy={"server": proxy_url} if proxy_url else None
        )

        while True:
            try:
                print(f"\n🔍 LOG [{datetime.now().strftime('%H:%M:%S')}]: Google Sheets qayta tekshirilmoqda...")
                check_and_update_limits()
                records = leads_sheet.get_all_records()
                processed_in_this_pass = False

                sent_usernames = {
                    clean_username(r["username"]) 
                    for r in records 
                    if str(r["status"]).upper() == "SENT"
                }

                pending_count = sum(1 for r in records if str(r["status"]).upper() == "PENDING")
                print(f"📋 LOG: Topilgan umumiy PENDING leadlar soni: {pending_count} ta")

                for idx, row in enumerate(records, start=2):
                    if str(row["status"]).upper() == "PENDING":
                        platform = str(row["platform"]).upper().strip()
                        user = str(row["username"]).strip()
                        clean_user = clean_username(user)

                        print(f"\n👉 LOG: Qator #{idx} tekshirilmoqda: User={user} | Platform={platform}")

                        # 1. DUKLIKAT TEKSHIRUVI
                        if clean_user in sent_usernames:
                            print(f"⏭️ LOG [DUPLICATE]: {user} ga allaqachon DM yuborilgan! O'tkazib yuborildi.")
                            leads_sheet.update_cell(idx, 4, "SKIPPED_DUPLICATE")
                            leads_sheet.update_cell(idx, 5, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                            continue

                        # 2. LIMIT TEKSHIRUVI
                        if can_send(platform):
                            print(f"🚀 LOG: {user} ga {platform} orqali yuborish boshlandi...")

                            cookies = parse_cookies(f"{platform}_COOKIES")
                            context = browser.new_context()
                            if cookies:
                                context.add_cookies(cookies)
                            
                            page = context.new_page()

                            if platform == "X":
                                print(f"🌐 LOG: X.com/messages/{clean_user} sahifasi ochilmoqda...")
                                page.goto(f"https://x.com/messages/{clean_user}")
                                page.wait_for_timeout(4000)
                            elif platform == "INSTAGRAM":
                                print(f"🌐 LOG: Instagram.com/direct/t/{clean_user}/ sahifasi ochilmoqda...")
                                page.goto(f"https://www.instagram.com/direct/t/{clean_user}/")
                                page.wait_for_timeout(4000)

                            context.close()

                            # Status yangilash
                            leads_sheet.update_cell(idx, 4, "SENT")
                            leads_sheet.update_cell(idx, 5, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                            
                            sent_usernames.add(clean_user)
                            increment_today_sent(platform)
                            processed_in_this_pass = True

                            # PAUZA INTERVALI
                            wait_time = random.randint(MIN_DELAY, MAX_DELAY)
                            print(f"✅ LOG [Muvaffaqiyatli]: DM yuborildi!")
                            print(f"⏳ LOG [Pauza]: Akkaunt xavfsizligi uchun {wait_time // 60} daqiqa ({wait_time} sek) kutilmoqda...\n")
                            time.sleep(wait_time)
                        else:
                            print(f"🛑 LOG [Limit To'lgan]: Bugun {platform} platformasida boshqa DM yuborib bo'lmaydi. Skipped: {user}")

                if not processed_in_this_pass:
                    print("😴 LOG [Kutish rejimida]: Bajarilishi kerak bo'lgan PENDING leadlar qolmadi yoki kunlik limitlar to'lgan.")
                    print("⏱️ LOG: 2 daqiqadan so'ng Sheets jadvali qayta tekshiriladi...")
                    time.sleep(2 * 60)

            except Exception as e:
                print(f"❌ LOG [XATOLIK]: Sikl davomida kutilmagan xatolik: {e}")
                print("⏱️ LOG: Xatolikdan so'ng 2 daqiqa kutilmoqda...")
                time.sleep(2 * 60)

if __name__ == "__main__":
    run_outreach_loop()

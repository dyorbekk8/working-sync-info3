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

# Google Sheets faylingiz nomi
doc = client.open("Outreach Leads")
leads_sheet = doc.worksheet("Sheet1")
limits_sheet = doc.worksheet("Sheet2")

# Random Intervallar (20 - 80 daqiqa)
MIN_DELAY = 20 * 60
MAX_DELAY = 80 * 60

def parse_cookies(env_name):
    raw_data = os.getenv(env_name)
    if not raw_data:
        return []
    parsed = json.loads(raw_data)
    return parsed if isinstance(parsed, list) else parsed.get("cookies", [])

def clean_username(user):
    """Username'ni tozalash (masalan: @john_doe -> john_doe)"""
    return str(user).replace("@", "").strip().lower()

def check_and_update_limits():
    """Yangi kun kelsa limitlarni +1 ga oshirish va Today_Sent ni reset qilish"""
    today_str = str(date.today())
    limits_data = limits_sheet.get_all_records()
    
    for idx, row in enumerate(limits_data, start=2):
        last_date = str(row["Last_Reset_Date"])
        if last_date != today_str:
            new_limit = int(row["Daily_Limit"]) + 1  # Har kuni +1 DM qo'shiladi
            limits_sheet.update_cell(idx, 2, new_limit) # Daily_Limit
            limits_sheet.update_cell(idx, 3, 0)         # Today_Sent reset
            limits_sheet.update_cell(idx, 4, today_str)  # Last_Reset_Date

def can_send(platform):
    """Platforma limitini va bugungi yuborilganlar sonini tekshirish"""
    check_and_update_limits()
    limits_data = limits_sheet.get_all_records()
    for row in limits_data:
        if row["Platform"].upper() == platform.upper():
            return int(row["Today_Sent"]) < int(row["Daily_Limit"])
    return False

def increment_today_sent(platform):
    """Yuborilgan DM lar sonini +1 ga oshirish"""
    limits_data = limits_sheet.get_all_records()
    for idx, row in enumerate(limits_data, start=2):
        if row["Platform"].upper() == platform.upper():
            current_sent = int(row["Today_Sent"])
            limits_sheet.update_cell(idx, 3, current_sent + 1)
            break

def run_outreach_loop():
    print("🚀 24/7 Outreach Engine Started (with Anti-Duplicate Check)...")
    
    with sync_playwright() as p:
        proxy_url = os.getenv("PROXY_SERVER")
        browser = p.chromium.launch(
            headless=True,
            proxy={"server": proxy_url} if proxy_url else None
        )

        while True: # 24/7 Cheksiz Sikl
            try:
                check_and_update_limits()
                records = leads_sheet.get_all_records()
                processed_in_this_pass = False

                # Allaqachon yozib bo'lingan BARCHA foydalanuvchilar ro'yxati (3 ta platforma bo'yicha)
                sent_usernames = {
                    clean_username(r["username"]) 
                    for r in records 
                    if str(r["status"]).upper() == "SENT"
                }

                for idx, row in enumerate(records, start=2):
                    if str(row["status"]).upper() == "PENDING":
                        platform = str(row["platform"]).upper().strip()
                        user = str(row["username"]).strip()
                        msg = str(row["message"]).strip()
                        clean_user = clean_username(user)

                        # 🛑 DUKLIKAT TEKSHIRUVI: Agar bu insonga bitta platformada yozilgan bo'lsa, o'tkazib yuboradi
                        if clean_user in sent_usernames:
                            print(f"⚠️ {user} ga allaqachon DM yuborilgan! Dublikat bo'lgani uchun o'tkazib yuborildi.")
                            leads_sheet.update_cell(idx, 4, "SKIPPED_DUPLICATE")
                            leads_sheet.update_cell(idx, 5, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                            continue

                        # Kunlik limit tekshiruvi
                        if can_send(platform):
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] Processing {user} on {platform}...")

                            cookie_env = f"{platform}_COOKIES"
                            cookies = parse_cookies(cookie_env)
                            
                            context = browser.new_context()
                            if cookies:
                                context.add_cookies(cookies)
                            
                            page = context.new_page()

                            # DM yuborish interaksiyasi
                            if platform == "X":
                                page.goto(f"https://x.com/messages/{clean_user}")
                                page.wait_for_timeout(5000)
                                # UI harakatlari...
                            
                            elif platform == "INSTAGRAM":
                                page.goto(f"https://www.instagram.com/direct/t/{clean_user}/")
                                page.wait_for_timeout(5000)
                                # UI harakatlari...

                            context.close()

                            # Statusni yangilash
                            leads_sheet.update_cell(idx, 4, "SENT")
                            leads_sheet.update_cell(idx, 5, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                            
                            # Dublikatlar bazasiga yangi foydalanuvchini qo'shish
                            sent_usernames.add(clean_user)

                            # Limit va hisoblagichlarni yangilash
                            increment_today_sent(platform)
                            processed_in_this_pass = True

                            # Random 20 - 80 daqiqa PAUZA
                            wait_time = random.randint(MIN_DELAY, MAX_DELAY)
                            print(f"✅ Sent! Sleeping for {wait_time // 60} minutes...\n")
                            time.sleep(wait_time)
                        else:
                            print(f"⚠️ Limit reached for {platform} today. Skipping {user}.")

                if not processed_in_this_pass:
                    print("😴 No pending leads or daily limit reached. Re-checking in 15 minutes...")
                    time.sleep(15 * 60)

            except Exception as e:
                print(f"❌ Error in main loop: {e}")
                time.sleep(5 * 60)

if __name__ == "__main__":
    run_outreach_loop()

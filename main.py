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

# Varaqlarni ulash (Fayl nomi: Outreach Leads)
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

def check_and_update_limits():
    """Yangi kun kelsa limitlarni +1 ga oshirish va Today_Sent ni reset qilish"""
    today_str = str(date.today())
    limits_data = limits_sheet.get_all_records()
    
    for idx, row in enumerate(limits_data, start=2):
        last_date = str(row["Last_Reset_Date"])
        if last_date != today_str:
            new_limit = int(row["Daily_Limit"]) + 1 # Harkuni +1 DM qo'shiladi
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
    print("🚀 24/7 Outreach Engine Started...")
    
    with sync_playwright() as p:
        proxy_url = os.getenv("PROXY_SERVER")
        browser = p.chromium.launch(
            headless=True,
            proxy={"server": proxy_url} if proxy_url else None
        )

        while True: # 24/7 To'xtovsiz Cheksiz Sikl
            try:
                check_and_update_limits()
                records = leads_sheet.get_all_records()
                processed_in_this_pass = False

                for idx, row in enumerate(records, start=2):
                    if row["status"] == "PENDING":
                        platform = str(row["platform"]).upper().strip()
                        user = str(row["username"]).strip()
                        msg = str(row["message"]).strip()

                        # Kunlik limit to'lmagan bo'lsa ishlaydi
                        if can_send(platform):
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] Processing {user} on {platform}...")

                            cookie_env = f"{platform}_COOKIES"
                            cookies = parse_cookies(cookie_env)
                            
                            context = browser.new_context()
                            if cookies:
                                context.add_cookies(cookies)
                            
                            page = context.new_page()

                            # DM yuborish mantiqlari
                            if platform == "X":
                                clean_user = user.replace("@", "")
                                page.goto(f"https://x.com/messages/{clean_user}")
                                page.wait_for_timeout(5000)
                                # UI harakatlari...
                            
                            elif platform == "INSTAGRAM":
                                clean_user = user.replace("@", "")
                                page.goto(f"https://www.instagram.com/direct/t/{clean_user}/")
                                page.wait_for_timeout(5000)
                                # UI harakatlari...

                            context.close()

                            # Status va taymerlarni yangilash
                            leads_sheet.update_cell(idx, 4, "SENT")
                            leads_sheet.update_cell(idx, 5, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                            
                            # Limitlar balansini oshirish
                            increment_today_sent(platform)
                            processed_in_this_pass = True

                            # 20 - 80 daqiqa RANDOM PAUZA
                            wait_time = random.randint(MIN_DELAY, MAX_DELAY)
                            print(f"✅ Sent! Sleeping for {wait_time // 60} minutes...\n")
                            time.sleep(wait_time)
                        else:
                            print(f"⚠️ Limit reached for {platform} today. Skipping {user}.")

                # Agar barcha pending leadlar tugagan bo'lsa yoki limitlar yopilgan bo'lsa 15 min kutib tekshiradi
                if not processed_in_this_pass:
                    print("😴 No pending leads or all platform limits reached. Waiting 15 minutes before re-checking...")
                    time.sleep(15 * 60)

            except Exception as e:
                print(f"❌ Error in main loop: {e}")
                time.sleep(5 * 60) # Xatolik bo'lsa 5 minut kutib qayta urinadi

if __name__ == "__main__":
    run_outreach_loop()

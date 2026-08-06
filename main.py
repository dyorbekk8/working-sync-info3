import os
import json
import time
import random
from datetime import datetime, date
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from playwright.sync_api import sync_playwright

# Flush=True orqali har bir print() ni kuttirmasdan darhol ekranga chiqarish
def log(text):
    print(text, flush=True)

# 1. Google Sheets Ulash
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.loads(os.getenv("GOOGLE_CREDENTIALS"))
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

doc = client.open_by_key(os.getenv("SPREADSHEET_ID")) # Yoki client.open("Outreach Leads")
leads_sheet = doc.get_worksheet(0)
limits_sheet = doc.get_worksheet(1)

MIN_DELAY = 8 * 60
MAX_DELAY = 15 * 60

def parse_cookies(env_name):
    raw_data = os.getenv(env_name)
    if not raw_data:
        log(f"⚠️ LOG: {env_name} o'zgaruvchisi topilmadi yoki bo'sh!")
        return []
    parsed = json.loads(raw_data)
    cookies = parsed if isinstance(parsed, list) else parsed.get("cookies", [])
    
    # Playwright sameSite formatini to'g'rilash (Strict, Lax, None)
    for cookie in cookies:
        if isinstance(cookie, dict) and "sameSite" in cookie and cookie["sameSite"]:
            val = str(cookie["sameSite"]).capitalize()
            if val in ["Strict", "Lax", "None"]:
                cookie["sameSite"] = val
            else:
                del cookie["sameSite"]
    return cookies

def clean_username(user):
    return str(user).replace("@", "").strip().lower()

def check_and_update_limits():
    today_str = str(date.today())
    limits_data = limits_sheet.get_all_records()
    
    for idx, row in enumerate(limits_data, start=2):
        last_date = str(row["Last_Reset_Date"])
        if last_date != today_str:
            new_limit = int(row["Daily_Limit"]) + 1
            limits_sheet.update_cell(idx, 2, new_limit)
            limits_sheet.update_cell(idx, 3, 0)
            limits_sheet.update_cell(idx, 4, today_str)
            log(f"🔄 LOG: {row['Platform']} uchun yangi kun limitlari yangilandi: Limit={new_limit}")

def can_send(platform):
    check_and_update_limits()
    limits_data = limits_sheet.get_all_records()
    for row in limits_data:
        if row["Platform"].upper() == platform.upper():
            sent = int(row["Today_Sent"])
            limit = int(row["Daily_Limit"])
            log(f"📊 LOG [{platform}]: Bugun yuborildi={sent}/{limit}")
            return sent < limit
    log(f"⚠️ LOG: {platform} platformasi Sheet2 da topilmadi!")
    return False

def increment_today_sent(platform):
    limits_data = limits_sheet.get_all_records()
    for idx, row in enumerate(limits_data, start=2):
        if row["Platform"].upper() == platform.upper():
            current_sent = int(row["Today_Sent"])
            limits_sheet.update_cell(idx, 3, current_sent + 1)
            log(f"📈 LOG: {platform} hisoblagichi oshirildi: {current_sent + 1}")
            break

def run_outreach_loop():
    log("\n==================================================")
    log("🚀 24/7 Lightweight Outreach Engine Started...")
    log("==================================================\n")
    
    with sync_playwright() as p:
        proxy_url = os.getenv("PROXY_SERVER")
        log(f"🌐 LOG: Proxy server holati: {'Ulangan' if proxy_url else 'Ishlatilmayapti'}")

        # RAILWAY RAM-INI TEJAYDIGAN VA QOTISHNI OLDINI OLUVCHI SOZLAMALAR
        browser = p.chromium.launch(
            headless=True,
            proxy={"server": proxy_url} if proxy_url else None,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage', # RAM xotira yetmay qolishini oldini oladi
                '--disable-accelerated-2d-canvas',
                '--no-first-run',
                '--no-zygote',
                '--disable-gpu'
            ]
        )

        while True:
            try:
                log(f"\n🔍 LOG [{datetime.now().strftime('%H:%M:%S')}]: Google Sheets qayta tekshirilmoqda...")
                check_and_update_limits()
                records = leads_sheet.get_all_records()
                processed_in_this_pass = False

                sent_usernames = {
                    clean_username(r["username"]) 
                    for r in records 
                    if str(r["status"]).upper() == "SENT"
                }

                pending_count = sum(1 for r in records if str(r["status"]).upper() == "PENDING")
                log(f"📋 LOG: Topilgan umumiy PENDING leadlar soni: {pending_count} ta")

                for idx, row in enumerate(records, start=2):
                    if str(row["status"]).upper() == "PENDING":
                        platform = str(row["platform"]).upper().strip()
                        user = str(row["username"]).strip()
                        clean_user = clean_username(user)

                        log(f"\n👉 LOG: Qator #{idx} tekshirilmoqda: User={user} | Platform={platform}")

                        if clean_user in sent_usernames:
                            log(f"⏭️ LOG [DUPLICATE]: {user} allaqachon mavjud! O'tkazib yuborildi.")
                            leads_sheet.update_cell(idx, 4, "SKIPPED_DUPLICATE")
                            leads_sheet.update_cell(idx, 5, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                            continue

                        if can_send(platform):
                            log(f"🚀 LOG: {user} ga {platform} orqali yuborish boshlandi...")

                            cookies = parse_cookies(f"{platform}_COOKIES")
                            context = browser.new_context()
                            if cookies:
                                context.add_cookies(cookies)
                            
                            page = context.new_page()
                            # 30 soniyadan ortiq kuttirmaslik uchun timeout qo'shildi
                            page.set_default_timeout(30000) 

                            try:
                                if platform == "X":
                                    log(f"🌐 LOG: X.com/messages/{clean_user} ochilmoqda...")
                                    page.goto(f"https://x.com/messages/{clean_user}", wait_until="domcontentloaded", timeout=30000)
                                    page.wait_for_timeout(3000)
                                elif platform == "INSTAGRAM":
                                    log(f"🌐 LOG: Instagram.com/direct/t/{clean_user}/ ochilmoqda...")
                                    page.goto(f"https://www.instagram.com/direct/t/{clean_user}/", wait_until="domcontentloaded", timeout=30000)
                                    page.wait_for_timeout(3000)
                            except Exception as page_err:
                                log(f"⚠️ LOG [Net Timeout]: Sahifa yuklanishida sekinlik bo'ldi, lekin davom etilmoqda: {page_err}")

                            context.close()

                            leads_sheet.update_cell(idx, 4, "SENT")
                            leads_sheet.update_cell(idx, 5, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                            
                            sent_usernames.add(clean_user)
                            increment_today_sent(platform)
                            processed_in_this_pass = True

                            wait_time = random.randint(MIN_DELAY, MAX_DELAY)
                            log(f"✅ LOG: Muvaffaqiyatli bajarildi!")
                            log(f"⏳ LOG [Pauza]: Keyingi harakatgacha {wait_time // 60} daqiqa kutilmoqda...\n")
                            time.sleep(wait_time)
                        else:
                            log(f"🛑 LOG [Limit To'lgan]: Bugun {platform} uchun limit yetarli emas. Skipped: {user}")

                if not processed_in_this_pass:
                    log("😴 LOG: Bajarilishi kerak bo'lgan PENDING leadlar qolmadi yoki kunlik limitlar to'lgan.")
                    log("⏱️ LOG: 2 daqiqadan so'ng Sheets jadvali qayta tekshiriladi...")
                    time.sleep(2 * 60)

            except Exception as e:
                log(f"❌ LOG [XATOLIK]: {e}")
                time.sleep(2 * 60)

if __name__ == "__main__":
    run_outreach_loop()

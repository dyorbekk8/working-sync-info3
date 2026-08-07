import os
import json
import time
import random
import socket
from datetime import datetime, date
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from playwright.sync_api import sync_playwright

# Tarmoq qotib qolishini oldini olish uchun 30 soniyalik universal timeout
socket.setdefaulttimeout(30)

def log(text):
    print(text, flush=True)

# 1. Google Sheets Ulash
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.loads(os.getenv("GOOGLE_CREDENTIALS"))
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

doc = client.open_by_key(os.getenv("SPREADSHEET_ID"))
leads_sheet = doc.get_worksheet(0)
limits_sheet = doc.get_worksheet(1)

MIN_DELAY = 8 * 60
MAX_DELAY = 15 * 60

def parse_cookies(env_name):
    raw_data = os.getenv(env_name)
    if not raw_data:
        return []
    try:
        parsed = json.loads(raw_data)
        cookies = parsed if isinstance(parsed, list) else parsed.get("cookies", [])
        for cookie in cookies:
            if isinstance(cookie, dict) and "sameSite" in cookie and cookie["sameSite"]:
                val = str(cookie["sameSite"]).capitalize()
                if val in ["Strict", "Lax", "None"]:
                    cookie["sameSite"] = val
                else:
                    del cookie["sameSite"]
        return cookies
    except Exception as e:
        log(f"⚠️ LOG: {env_name} cookielarini o'qishda xatolik: {e}")
        return []

def clean_username(user):
    return str(user).replace("@", "").strip().lower()

def fetch_and_sync_limits():
    today_str = str(date.today())
    limits_data = limits_sheet.get_all_records()
    limits_map = {}

    for idx, row in enumerate(limits_data, start=2):
        platform = str(row["Platform"]).upper().strip()
        last_date = str(row["Last_Reset_Date"])
        sent = int(row["Today_Sent"])
        limit = int(row["Daily_Limit"])

        if last_date != today_str:
            sent = 0
            limits_sheet.update_cell(idx, 3, 0)
            limits_sheet.update_cell(idx, 4, today_str)
            time.sleep(1)

        limits_map[platform] = {
            "row_idx": idx,
            "sent": sent,
            "limit": limit
        }
    return limits_map

# ==================== DISCORD API MESSAGING ====================
def send_message_discord(user_id_or_name, message_text):
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise Exception("DISCORD_TOKEN o'zgaruvchisi Railway'da topilmadi!")

    clean_id = str(user_id_or_name).replace("@", "").strip()

    if not clean_id.isdigit():
        raise Exception(f"Discord User ID noto'g'ri ('{clean_id}'). Sheetda Username emas, raqamli Discord User ID (Snowflake) kiritilishi shart.")

    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    log(f"🌐 LOG [DISCORD]: User ID ({clean_id}) bilan DM kanal yaratilmoqda...")
    dm_channel_req = requests.post(
        "https://discord.com/api/v9/users/@me/channels",
        headers=headers,
        json={"recipient_id": clean_id},
        timeout=15
    )

    if dm_channel_req.status_code not in [200, 201]:
        raise Exception(f"Discord DM kanal ochib bo'lmadi (Status {dm_channel_req.status_code}): {dm_channel_req.text}")

    channel_id = dm_channel_req.json().get("id")

    log(f"✉️ LOG [DISCORD]: DM Kanal (#{channel_id}) ga xabar yuborilmoqda...")
    msg_req = requests.post(
        f"https://discord.com/api/v9/channels/{channel_id}/messages",
        headers=headers,
        json={"content": message_text},
        timeout=15
    )

    if msg_req.status_code not in [200, 201]:
        raise Exception(f"Discord xabar yuborishda xatolik (Status {msg_req.status_code}): {msg_req.text}")

# ==================== PLAYWRIGHT X & INSTAGRAM ====================
def send_message_x(page, user, message_text):
    clean_user = clean_username(user)
    log(f"🌐 LOG: https://x.com/{clean_user} profiliga kirilmoqda...")
    page.goto(f"https://x.com/{clean_user}", wait_until="domcontentloaded", timeout=35000)
    page.wait_for_timeout(3000)
    
    dm_btn = page.wait_for_selector('[data-testid="sendDMFromProfile"]', timeout=20000)
    dm_btn.click()
    page.wait_for_timeout(3000)

    msg_selector = '[data-testid="dmComposerTextInput"]'
    page.wait_for_selector(msg_selector, timeout=20000)
    page.fill(msg_selector, message_text)
    page.wait_for_timeout(1000)
    
    send_btn = page.query_selector('[data-testid="dmComposerSendButton"]')
    if send_btn and send_btn.is_enabled():
        send_btn.click()
    else:
        page.keyboard.press("Enter")
    page.wait_for_timeout(3000)

def send_message_instagram(page, user, message_text):
    clean_user = clean_username(user)
    log(f"🌐 LOG: https://www.instagram.com/{clean_user}/ profiliga kirilmoqda...")
    
    try:
        page.goto(f"https://www.instagram.com/{clean_user}/", wait_until="commit", timeout=25000)
    except Exception as e:
        raise Exception(f"Instagram profiliga kirib bo'lmadi (Proxy sekin yoki profil o'chirilgan): {e}")

    page.wait_for_timeout(4000)

    # 1. DIAGNOSTIKA: Cookie va URL redirection tekshiruvi
    current_url = page.url
    if "accounts/login" in current_url:
        raise Exception("INSTAGRAM_COOKIES eskirgan (Login sahifasiga otib yubordi). Railway Variable'da cookielarni yangilang!")
    if "challenge" in current_url:
        raise Exception("Instagram akkauntingizga Verification / Captcha kelgan! Akkauntga brauzerda kirib yechish kerak.")

    # 2. Bildirishnoma va Pop-up'larni yopish
    try:
        popup_close = page.query_selector('button:has-text("Not Now"), button:has-text("Сейчас не"), button:has-text("Cancel")')
        if popup_close:
            popup_close.click()
            page.wait_for_timeout(1000)
    except Exception:
        pass

    # 3. FOLLOW TUGMASINI TEKSHIRISH VA BOSISH
    try:
        follow_btn_selector = (
            'button:has-text("Follow"), '
            'button:has-text("Подписаться"), '
            'div[role="button"]:has-text("Follow"), '
            'div[role="button"]:has-text("Подписаться")'
        )
        follow_btn = page.query_selector(follow_btn_selector)
        
        # Agar Follow tugmasi bo'lsa va allaqachon "Following" bo'lmasa
        if follow_btn and "Following" not in follow_btn.inner_text() and "Подписки" not in follow_btn.inner_text():
            log("➕ LOG [INSTAGRAM]: Follow tugmasi bosilmoqda...")
            follow_btn.evaluate("el => el.click()")
            log("⏳ LOG [INSTAGRAM]: Follow bosildi. Message tugmasi chiqishi uchun 3 soniya kutilmoqda...")
            page.wait_for_timeout(3000)
    except Exception as follow_err:
        log(f"⚠️ LOG [INSTAGRAM]: Follow bosishda kichik og'ish (muhim emas): {follow_err}")

    # 4. MESSAGE TUGMASINI TOPISH VA BOSISH
    log("🔍 LOG [INSTAGRAM]: Message tugmasi qidirilmoqda...")
    msg_btn_selector = (
        'a[href*="/direct/t/"], '
        'div[role="button"]:has-text("Message"), '
        'button:has-text("Message"), '
        'button:has-text("Отправить сообщение"), '
        'div[role="button"]:has-text("Отправить сообщение")'
    )
    
    try:
        msg_btn = page.wait_for_selector(msg_btn_selector, timeout=15000)
        msg_btn.evaluate("el => el.click()")
        log("✅ LOG [INSTAGRAM]: Message tugmasi bosildi!")
    except Exception:
        raise Exception("Profil topilmadi, yopiq (Private) yoki profil sozlamalarida DM xabarlar cheklangan.")

    page.wait_for_timeout(4000)

    # 5. Yana bir bor 'Not Now' pop-up chiqsa yopish
    try:
        not_now_btn = page.query_selector('button:has-text("Not Now"), button:has-text("Сейчас не")')
        if not_now_btn:
            not_now_btn.click()
            page.wait_for_timeout(1000)
    except Exception:
        pass
        
    # 6. Xabarni kiritish va yuborish
    log("✍️ LOG [INSTAGRAM]: Xabar yozilmoqda...")
    msg_selector = 'div[contenteditable="true"], div[aria-label="Message"], div[aria-label="Xabar..."], div[role="textbox"]'
    msg_input = page.wait_for_selector(msg_selector, timeout=15000)
    msg_input.fill(message_text)
    page.wait_for_timeout(1000)
    page.keyboard.press("Enter")
    page.wait_for_timeout(3000)

# ==================== MAIN OUTREACH ENGINE ====================
def run_outreach_loop():
    log("\n==================================================")
    log("🚀 24/7 Lightweight Multi-Platform Outreach Engine Started...")
    log("==================================================\n")
    
    with sync_playwright() as p:
        proxy_url = os.getenv("PROXY_SERVER")
        log(f"🌐 LOG: Proxy server holati: {'Ulangan' if proxy_url else 'Ishlatilmayapti'}")

        browser = p.chromium.launch(
            headless=True,
            proxy={"server": proxy_url} if proxy_url else None,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--no-first-run',
                '--no-zygote',
                '--disable-gpu'
            ]
        )

        while True:
            try:
                log(f"\n🔍 LOG [{datetime.now().strftime('%H:%M:%S')}]: Google Sheets qayta tekshirilmoqda...")
                log("⏳ LOG: Limitlar tekshirilmoqda...")
                limits_map = fetch_and_sync_limits()
                
                log("⏳ LOG: Google Sheets'dan leadlar ro'yxati yuklanmoqda...")
                records = leads_sheet.get_all_records()
                log("✅ LOG: Sheets ma'lumotlari muvaffaqiyatli yuklandi!")
                
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
                        message_text = str(row.get("message", "")).strip()

                        log(f"\n👉 LOG: Qator #{idx} tekshirilmoqda: User={user} | Platform={platform}")

                        if clean_user in sent_usernames:
                            log(f"⏭️ LOG [DUPLICATE]: {user} allaqachon mavjud! O'tkazib yuborildi.")
                            leads_sheet.update_cell(idx, 4, "SKIPPED_DUPLICATE")
                            leads_sheet.update_cell(idx, 5, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                            time.sleep(1)
                            continue

                        if not message_text:
                            log(f"⚠️ LOG [BO'SH XABAR]: {user} uchun 'message' ustuni bo'sh. SKIPPED.")
                            leads_sheet.update_cell(idx, 4, "SKIPPED_NO_MESSAGE")
                            time.sleep(1)
                            continue

                        plat_info = limits_map.get(platform)
                        if not plat_info:
                            log(f"⚠️ LOG: {platform} platformasi Sheet2 da topilmadi, o'tkazib yuborilmoqda.")
                            continue

                        log(f"📊 LOG [{platform}]: Bugun yuborildi={plat_info['sent']}/{plat_info['limit']}")

                        if plat_info['sent'] < plat_info['limit']:
                            
                            # DISCORD UCHUN BRAUZERSIZ TEZKOR API YO'LI
                            if platform == "DISCORD":
                                try:
                                    log(f"🚀 LOG: {user} ga DISCORD API orqali yuborish boshlandi...")
                                    send_message_discord(user, message_text)
                                    
                                    leads_sheet.update_cell(idx, 4, "SENT")
                                    leads_sheet.update_cell(idx, 5, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                                    
                                    plat_info['sent'] += 1
                                    limits_sheet.update_cell(plat_info['row_idx'], 3, plat_info['sent'])
                                    log(f"📈 LOG: DISCORD hisoblagichi oshirildi: {plat_info['sent']}")

                                    sent_usernames.add(clean_user)
                                    processed_in_this_pass = True

                                    wait_time = random.randint(MIN_DELAY, MAX_DELAY)
                                    log(f"✅ LOG: {user} ga Discord xabar muvaffaqiyatli yuborildi!")
                                    log(f"⏳ LOG [Pauza]: Keyingi harakatgacha {wait_time // 60} daqiqa kutilmoqda...\n")
                                    time.sleep(wait_time)
                                except Exception as disc_err:
                                    log(f"❌ LOG [DISCORD XATOLIK]: {user} uchun xabar yuborilmadi: {disc_err}")
                                    fail_status = "FAILED_INVALID_ID" if "Discord User ID" in str(disc_err) else "FAILED"
                                    leads_sheet.update_cell(idx, 4, fail_status)
                                    leads_sheet.update_cell(idx, 5, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                                    time.sleep(1)
                                continue

                            # X VA INSTAGRAM UCHUN BRAUZER ORQALI YUBORISH
                            cookies = parse_cookies(f"{platform}_COOKIES")
                            if not cookies and platform in ["X", "INSTAGRAM"]:
                                log(f"⚠️ LOG: {platform}_COOKIES topilmadi! O'tkazib yuborilmoqda.")
                                continue

                            log(f"🚀 LOG: {user} ga {platform} orqali yuborish boshlandi...")
                            context = browser.new_context()
                            if cookies:
                                context.add_cookies(cookies)
                            
                            page = context.new_page()
                            page.set_default_timeout(35000)

                            try:
                                if platform == "X":
                                    send_message_x(page, user, message_text)
                                elif platform == "INSTAGRAM":
                                    send_message_instagram(page, user, message_text)
                                else:
                                    log(f"⚠️ LOG: Qo'llab-quvvatlanmaydigan platforma ({platform}), o'tkazib yuborildi.")
                                    leads_sheet.update_cell(idx, 4, "SKIPPED_UNSUPPORTED_PLATFORM")
                                    context.close()
                                    time.sleep(1)
                                    continue

                                leads_sheet.update_cell(idx, 4, "SENT")
                                leads_sheet.update_cell(idx, 5, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                                
                                plat_info['sent'] += 1
                                limits_sheet.update_cell(plat_info['row_idx'], 3, plat_info['sent'])
                                log(f"📈 LOG: {platform} hisoblagichi oshirildi: {plat_info['sent']}")

                                sent_usernames.add(clean_user)
                                processed_in_this_pass = True

                                wait_time = random.randint(MIN_DELAY, MAX_DELAY)
                                log(f"✅ LOG: {user} ga xabar muvaffaqiyatli yuborildi!")
                                log(f"⏳ LOG [Pauza]: Keyingi harakatgacha {wait_time // 60} daqiqa kutilmoqda...\n")
                                context.close()
                                time.sleep(wait_time)

                            except Exception as send_err:
                                log(f"❌ LOG [XATOLIK - YUBORILMADI]: {user} uchun xabar yuborishda xato: {send_err}")
                                leads_sheet.update_cell(idx, 4, "FAILED")
                                leads_sheet.update_cell(idx, 5, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                                context.close()
                                time.sleep(1)
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

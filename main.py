import os
import asyncio
import requests
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# SETTINGS
OK_COOKIES_JSON = os.getenv("OK_COOKIES")
TOKEN = os.getenv("TELEGRAM_TOKEN")

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK.ru Universal Bot is Running")

def run_health_server():
    server = HTTPServer(('0.0.0.0', 8000), HealthCheckHandler)
    server.serve_forever()

def fix_cookies(cookies_list):
    valid_samesite = ["Strict", "Lax", "None"]
    for cookie in cookies_list:
        if 'sameSite' in cookie:
            if cookie['sameSite'] == "no_restriction" or cookie['sameSite'] not in valid_samesite:
                cookie['sameSite'] = "None"
    return cookies_list

async def upload_to_ok(update, video_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        
        raw_cookies = json.loads(OK_COOKIES_JSON)
        clean_cookies = fix_cookies(raw_cookies)
        await context.add_cookies(clean_cookies)
        
        page = await context.new_page()

        try:
            print("Tagaya Video Manager...")
            await page.goto("https://ok.ru/video/manager", wait_until="load", timeout=60000)
            await asyncio.sleep(5)

            # 1. Isku day batoonka weyn ee dhexda (Empty State)
            big_button = page.locator('div.it_i.upload-video_it, .upload-video_it')
            if await big_button.is_visible():
                print("Waxaan helay batoonka weyn ee dhexda...")
                async with page.expect_file_chooser() as fc_info:
                    await big_button.click()
                file_chooser = await fc_info.value
                await file_chooser.set_files(video_path)
            
            # 2. Haddii kale isku day batoonka "Add" ee kore
            else:
                print("Batoonka dhexda lama arko, isku dayaya batoonka 'Add'...")
                add_button = page.locator('button:has-text("Add"), .button-pro, [data-l="t,addVideo"]')
                await add_button.first.click(timeout=30000)
                await asyncio.sleep(2)
                
                async with page.expect_file_chooser() as fc_info:
                    await page.click('text="Upload file"', timeout=20000)
                file_chooser = await fc_info.value
                await file_chooser.set_files(video_path)

            print("✅ Upload-ku waa bilaawday. Sug 60 ilbiriqsi...")
            await asyncio.sleep(60) 
            return True

        except Exception as e:
            await page.screenshot(path="debug.png")
            await update.message.reply_photo(photo=open("debug.png", 'rb'), caption=f"❌ Qalad: {e}")
            return False
        finally:
            await browser.close()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    if not url.startswith("http"): return

    msg = await update.message.reply_text("⏳ Server-ka ayaa soo dejinaya muqaalka...")
    file_path = f"video_{update.message.message_id}.mp4"
    
    try:
        r = requests.get(url, stream=True)
        with open(file_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                f.write(chunk)
        
        await msg.edit_text("🚀 Upload-ka OK.ru ayaa bilaawday...")
        success = await upload_to_ok(update, file_path)
        if success:
            await msg.edit_text("✅ Guul! Muqaalkii waa la upload gareeyay.")
    except Exception as e:
        await msg.edit_text(f"❌ Qalad: {str(e)}")
    finally:
        if os.path.exists(file_path): os.remove(file_path)

def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()

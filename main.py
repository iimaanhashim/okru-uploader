import os
import asyncio
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
        self.wfile.write(b"OK.ru Remote Uploader is Running")

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

async def remote_upload_ok(update, video_url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        
        raw_cookies = json.loads(OK_COOKIES_JSON)
        clean_cookies = fix_cookies(raw_cookies)
        await context.add_cookies(clean_cookies)
        
        page = await context.new_page()

        try:
            print("Gelaya OK.ru Video Manager...")
            await page.goto("https://ok.ru/video/manager", wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(5)

            # 1. Guji batoonka "Add a video using the link"
            print("Guji 'Add video via link'...")
            await page.click('button:has-text("Add a video using the link")')
            await asyncio.sleep(2)

            # 2. Geli URL-ka muqaalka
            print("Gelinaya URL-ka...")
            await page.fill('input[placeholder="Paste the link to the video"]', video_url)
            await asyncio.sleep(2)

            # 3. Guji batoonka Add (Batoonka liinta ah)
            await page.click('input[value="Add"]')
            print("Muqaalka waa lagu daray OK.ru!")
            
            await asyncio.sleep(5)
            return True

        except Exception as e:
            await page.screenshot(path="error.png")
            await update.message.reply_photo(photo=open("error.png", 'rb'), caption=f"❌ Khalad: {e}")
            return False
        finally:
            await browser.close()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    if not url.startswith("http"): return

    msg = await update.message.reply_text("🚀 OK.ru ayaa loo dirayaa Link-ga si ay u upload-gareeyaan...")
    
    success = await remote_upload_ok(update, url)
    if success:
        await msg.edit_text("✅ Guul! OK.ru ayaa hadda soo dejisanaysa muqaalkaaga. Waxaad ka heli doontaa qaybta 'My Videos'.")
    else:
        await msg.edit_text("❌ Upload-ku wuu fashilmay. Eeg sawirka kore.")

def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()

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
        self.wfile.write(b"OK.ru Direct Uploader is Running")

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
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        
        raw_cookies = json.loads(OK_COOKIES_JSON)
        clean_cookies = fix_cookies(raw_cookies)
        await context.add_cookies(clean_cookies)
        
        page = await context.new_page()

        try:
            # 1. TAG HOME PAGE HORTA (Warm-up)
            print("Tagaya Home Page...")
            await page.goto("https://ok.ru/", wait_until="load")
            await asyncio.sleep(5)

            # 2. TOOS U TAG BOGGA VIDEO-GA (Manager)
            print("Tagaya Video Manager...")
            await page.goto("https://ok.ru/video/manager", wait_until="load")
            await asyncio.sleep(5)

            # 3. GUJI BATOONKA "Add" (Batoonka liinta ah ee dhanka midig)
            print("Raadinaya batoonka Add Video...")
            await page.click('button:has-text("Add")')
            await asyncio.sleep(2)

            # 4. DOORO "Upload video" (Kani waa kan muqaalka tooska ah looga soo dooranayo computer-ka)
            # Mararka qaarkood batoonkani wuxuu ka muuqdaa isla markaaba
            print("Gelinaya muqaalka...")
            async with page.expect_file_chooser() as fc_info:
                # Waxaan raadinaynaa batoonka 'Choose a file for upload'
                await page.click('div.it_i.upload-video_it')
            
            file_chooser = await fc_info.value
            await file_chooser.set_files(video_path)
            
            print("Faylka waa la gelinayaa, fadlan sug...")
            # Sug inta upload-ku ka dhammanayo (Waqti sii)
            await asyncio.sleep(60) 
            return True

        except Exception as e:
            await page.screenshot(path="final_error.png")
            await update.message.reply_photo(photo=open("final_error.png", 'rb'), caption=f"❌ Upload Failed: {e}")
            return False
        finally:
            await browser.close()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    if not url.startswith("http"): return

    msg = await update.message.reply_text("⏳ Server-ka ayaa soo dejinaya muqaalka (hf.space link)...")
    file_path = f"video_{update.message.message_id}.mp4"
    
    try:
        r = requests.get(url, stream=True)
        with open(file_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                f.write(chunk)
        
        await msg.edit_text("🚀 Soo dejintii waa dhammaatay. Hadda ayaa loo upload-gareynayaa OK.ru...")
        success = await upload_to_ok(update, file_path)
        if success:
            await msg.edit_text("✅ Guul! Muqaalkii waa la upload gareeyay. Ka hubi 'My Videos' ee OK.ru-gaaga.")
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

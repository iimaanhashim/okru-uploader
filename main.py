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
        self.wfile.write(b"OK.ru Bot is Running")

def run_health_server():
    server = HTTPServer(('0.0.0.0', 8000), HealthCheckHandler)
    server.serve_forever()

# SHAQADAN AYAA SAXAYSA COOKIES-KA QALADKA AH
def fix_cookies(cookies_list):
    valid_samesite = ["Strict", "Lax", "None"]
    for cookie in cookies_list:
        if 'sameSite' in cookie:
            # Haddii ay tahay 'no_restriction' u beddel 'None'
            if cookie['sameSite'] == "no_restriction" or cookie['sameSite'] not in valid_samesite:
                cookie['sameSite'] = "None"
    return cookies_list

async def upload_to_ok(video_path, title):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
        
        # Soo qaado cookies-ka oo sax
        raw_cookies = json.loads(OK_COOKIES_JSON)
        clean_cookies = fix_cookies(raw_cookies)
        await context.add_cookies(clean_cookies)
        
        page = await context.new_page()

        try:
            print("Gelaya OK.ru adoo isticmaalaya Cookies saxan...")
            await page.goto("https://ok.ru/video/upload", wait_until="domcontentloaded", timeout=60000)
            
            # Hubi haddii uu jiro batoonka upload-ka
            await page.wait_for_selector('div.it_i.upload-video_it', timeout=60000)
            
            async with page.expect_file_chooser() as fc_info:
                await page.click('div.it_i.upload-video_it')
            
            file_chooser = await fc_info.value
            await file_chooser.set_files(video_path)
            
            print("Faylka waa la gelinayaa, sug 30 ilbiriqsi...")
            await asyncio.sleep(30) 
            print("✅ Upload Successful!")

        except Exception as e:
            print(f"❌ Error: {e}")
            raise e
        finally:
            await browser.close()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    if not url.startswith("http"): return

    msg = await update.message.reply_text("⏳ Muqaalka waa la soo dejinayaa...")
    file_path = f"video_{update.message.message_id}.mp4"
    
    try:
        r = requests.get(url, stream=True)
        with open(file_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                f.write(chunk)
        
        await msg.edit_text("🚀 Waxaa bilaawday Upload-ka OK.ru. Fadlan sug...")
        await upload_to_ok(file_path, "Muuqaal Cusub")
        await msg.edit_text("✅ Guul! Muqaalkii waa la upload gareeyay.")
    except Exception as e:
        await msg.edit_text(f"❌ Khalad: {str(e)}")
    finally:
        if os.path.exists(file_path): os.remove(file_path)

def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()

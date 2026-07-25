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
OK_COOKIES_JSON = os.getenv("OK_COOKIES") # Cookies-ka JSON-ka ah
TOKEN = os.getenv("TELEGRAM_TOKEN")

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK.ru Bot with Cookies is Running")

def run_health_server():
    server = HTTPServer(('0.0.0.0', 8000), HealthCheckHandler)
    server.serve_forever()

async def upload_to_ok(video_path, title):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
        
        # 1. Halkan waxaan ku dhisaynaa Session-ka adoo isticmaalaya Cookies
        cookies = json.loads(OK_COOKIES_JSON)
        await context.add_cookies(cookies)
        
        page = await context.new_page()

        try:
            print("Isagoo isticmaalaya Cookies ayuu gelayaa OK.ru...")
            await page.goto("https://ok.ru/video/upload", wait_until="networkidle")
            
            # Haddii cookies-ku shaqeeyaan, halkan wuxuu toos u arki doonaa batoonka upload-ka
            print("Gelinaya muqaalka...")
            async with page.expect_file_chooser() as fc_info:
                await page.click('div.it_i.upload-video_it')
            
            file_chooser = await fc_info.value
            await file_chooser.set_files(video_path)
            
            await asyncio.sleep(15) 
            print("✅ Upload Successful via Cookies!")

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
        
        await msg.edit_text("🚀 Waxaa bilaawday Upload-ka OK.ru (Cookies Mode)...")
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

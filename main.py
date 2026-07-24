import os
import asyncio
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# SETTINGS
RUMBLE_EMAIL = os.getenv("RUMBLE_EMAIL")
RUMBLE_PASS = os.getenv("RUMBLE_PASS")
TOKEN = os.getenv("TELEGRAM_TOKEN")

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is Running")

def run_health_server():
    server = HTTPServer(('0.0.0.0', 8000), HealthCheckHandler)
    server.serve_forever()

async def upload_to_rumble(video_path, title):
    async with async_playwright() as p:
        # Launching with more human-like settings
        browser = await p.chromium.launch(headless=True)
        # Isticmaal User-Agent dhab ah si aan naloo xannibin
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 720}
        )
        page = await context.new_page()

        try:
            print("Tagaya bogga Login-ka...")
            await page.goto("https://rumble.com/register/login/", wait_until="networkidle", timeout=90000)
            
            # Hubi haddii uu jiro sanduuqa login-ka (Sug 60 ilbiriqsi)
            await page.wait_for_selector('input[name="luser"]', timeout=60000)
            
            await page.fill('input[name="luser"]', RUMBLE_EMAIL)
            await page.fill('input[name="lpass"]', RUMBLE_PASS)
            
            # Guji Login
            await page.click('button[type="submit"]')
            print("Login la gujiyay, sugaya 10 ilbiriqsi...")
            await asyncio.sleep(10)

            # Haddii uu jiro Captcha halkan ayuu ku dhimanayaa, laakiin haddii kale wuu gudbiyaa
            await page.goto("https://rumble.com/upload.php", wait_until="networkidle", timeout=90000)
            
            # Uploading
            print("Faylka ayaa la gelinayaa Rumble...")
            await page.set_input_files('input[type="file"]', video_path)
            
            # Sugitaan dheeraad ah si uu Rumble u aqbalo faylka
            await page.wait_for_selector('input[name="title"]', timeout=60000)
            await page.fill('input[name="title"]', title)
            await page.fill('textarea[name="description"]', "Uploaded via Telegram Bot")
            
            await asyncio.sleep(5)
            # Batoonka u dambeeya ee Upload
            await page.get_by_role("button", name="Upload").click()
            print("Guul! Upload-kii waa dhammaaday.")
            await asyncio.sleep(5)

        except Exception as e:
            # Qaad Screenshot haddii uu qalad dhaco si aad u aragto waxa bogga ku yaalla (Logs-ka ayay ku soo baxaysaa haddii la u habeeyo)
            print(f"Qalad ayaa dhacay: {e}")
            raise e
        finally:
            await browser.close()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    if not url.startswith("http"):
        return

    msg = await update.message.reply_text("⏳ Muqaalka waa la soo dejinayaa...")
    file_path = "video_temp.mp4"
    
    try:
        r = requests.get(url, stream=True)
        with open(file_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                f.write(chunk)
        
        await msg.edit_text("🚀 Waxaa bilaawday Upload-ka Rumble. Fadlan sug...")
        await upload_to_rumble(file_path, "Muuqaal Cusub")
        await msg.edit_text("✅ Guul! Muqaalkii waa la upload gareeyay.")
    
    except Exception as e:
        await msg.edit_text(f"❌ Khalad ayaa dhacay: {str(e)}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()

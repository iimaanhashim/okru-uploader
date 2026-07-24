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
        browser = await p.chromium.launch(headless=True)
        # Context leh User-Agent aad u dhab ah
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            print("Isku dayaya Login-ka...")
            # Toos u tag bogga login-ka ee aad sawirka iiga soo dirtay
            login_url = "https://auth.rumble.com/login?redirect_uri=https%3A%2F%2Frumble.com%2Fupload.php"
            await page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
            
            # Buuxi Email/Username
            await page.wait_for_selector('input[name="username"]', timeout=30000)
            await page.fill('input[name="username"]', RUMBLE_EMAIL)
            
            # Buuxi Password
            await page.fill('input[name="password"]', RUMBLE_PASS)
            
            # Guji Sign In
            await page.click('button[type="submit"]')
            print("Login la gujiyay...")

            # Sug inta uu bogga upload-ka ka furmayo (Kaliya sug batoonka upload-ka)
            await page.wait_for_selector('input[type="file"]', timeout=60000)
            print("Hadda waxaan joognaa bogga Upload-ka!")

            # Geli Muqaalka
            await page.set_input_files('input[type="file"]', video_path)
            
            # Buuxi Title (Sug inta sanduuqu ka soo muuqanayo)
            await page.wait_for_selector('input[name="title"]', timeout=30000)
            await page.fill('input[name="title"]', title)
            await page.fill('textarea[name="description"]', "Uploaded via Telegram Automation")
            
            # Sug 5 ilbiriqsi ka dibna guji Upload
            await asyncio.sleep(5)
            await page.locator('button:has-text("Upload")').first.click()
            print("Upload-ka waa la diray!")
            await asyncio.sleep(5)

        except Exception as e:
            print(f"❌ Qalad: {e}")
            raise e
        finally:
            await browser.close()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    if not url.startswith("http"):
        return

    msg = await update.message.reply_text("⏳ Server-ka ayaa soo dejinaya muqaalka...")
    file_path = "video_temp.mp4"
    
    try:
        r = requests.get(url, stream=True)
        with open(file_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                f.write(chunk)
        
        await msg.edit_text("🚀 Waxaa bilaawday Upload-ka Rumble (Automation)...")
        await upload_to_rumble(file_path, "Muuqaal Cusub")
        await msg.edit_text("✅ Guul! Muqaalkii waa la upload gareeyay.")
    
    except Exception as e:
        await msg.edit_text(f"❌ Khalad: {str(e)}")
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

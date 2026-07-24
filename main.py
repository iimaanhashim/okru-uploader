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
        # Isticmaal muuqaal weyn si uu u arko batoonada oo dhan
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
        page = await context.new_page()

        try:
            print("Tagaya bogga Rumble Upload (Redirecting to Login)...")
            # Waxaan toos u tegaynaa bogga upload-ka, isagaa noo geynaya Login-ka cusub
            await page.goto("https://rumble.com/upload.php", wait_until="networkidle", timeout=90000)
            
            # 1. LOGIN CUSUB (Selectors-ka sawirkaaga ka muuqda)
            print("Filling Login Info...")
            # Sug sanduuqa Email-ka (Bogga cusub wuxuu isticmaalaa 'username')
            await page.wait_for_selector('input[name="username"]', timeout=60000)
            await page.fill('input[name="username"]', RUMBLE_EMAIL)
            
            # Sug sanduuqa Password-ka
            await page.fill('input[name="password"]', RUMBLE_PASS)
            
            # Guji batoonka "Sign In"
            await page.click('button[type="submit"]')
            print("Login Clicked...")
            
            # Sug inta uu bogga upload-ka dib ugu noqonayo
            await page.wait_for_url("https://rumble.com/upload.php", timeout=60000)
            print("Hadda waxaan joognaa bogga Upload-ka!")

            # 2. UPLOAD PROCESS
            print("Gelinaya faylka muqaalka...")
            await page.set_input_files('input[type="file"]', video_path)
            
            # Sug sanduuqyada Title-ka iyo Description-ka
            await page.wait_for_selector('input[name="title"]', timeout=60000)
            await page.fill('input[name="title"]', title)
            await page.fill('textarea[name="description"]', "Uploaded via Telegram Bot Automation")
            
            # Sug inta muqaalku boqolkiiba boqol gaarayo (Processing)
            await asyncio.sleep(10)
            
            # Guji batoonka Upload-ka u dambeeya
            # Rumble wuxuu leeyahay dhowr batoon, waxaan raadinaynaa kan leh qoraalka "Upload"
            await page.locator('button:has-text("Upload")').first.click()
            
            print("✅ Guul! Upload-kii waa dhammaaday.")
            await asyncio.sleep(5)

        except Exception as e:
            print(f"❌ Qalad ayaa dhacay: {e}")
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
        # Soo dejinta muqaalka
        r = requests.get(url, stream=True)
        with open(file_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                f.write(chunk)
        
        await msg.edit_text("🚀 Waxaa bilaawday Login-ka iyo Upload-ka Rumble...")
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
    print("Bot-ka waa diyaar...")
    app.run_polling()

if __name__ == "__main__":
    main()

import os
import asyncio
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# 1. SETTINGS (Environment Variables)
RUMBLE_EMAIL = os.getenv("RUMBLE_EMAIL")
RUMBLE_PASS = os.getenv("RUMBLE_PASS")
TOKEN = os.getenv("TELEGRAM_TOKEN")

# 2. KOYEB HEALTH CHECK (Port 8000)
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is Running")

def run_health_server():
    server = HTTPServer(('0.0.0.0', 8000), HealthCheckHandler)
    server.serve_forever()

# 3. RUMBLE UPLOAD LOGIC
async def upload_to_rumble(video_path, title):
    async with async_playwright() as p:
        # Launching Browser
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36")
        page = await context.new_page()

        try:
            # Login
            print("Logging into Rumble...")
            await page.goto("https://rumble.com/register/login/", timeout=60000)
            await page.fill('input[name="luser"]', RUMBLE_EMAIL)
            await page.fill('input[name="lpass"]', RUMBLE_PASS)
            await page.click('button[type="submit"]')
            await asyncio.sleep(5)

            # Upload Page
            print("Going to Upload Page...")
            await page.goto("https://rumble.com/upload.php", timeout=60000)
            
            # Set Files
            await page.set_input_files('input[type="file"]', video_path)
            print("File uploaded to browser, filling info...")

            # Fill Title & Description
            await page.fill('input[name="title"]', title)
            await page.fill('textarea[name="description"]', "Uploaded via Telegram Automation Bot")
            
            # Wait for upload to complete (Look for the button to become active)
            # Fiiro gaar ah: Rumble wuxuu u baahan yahay waqti inuu muqaalka u shaqeeyo
            await asyncio.sleep(15) 
            
            # Click Next/Submit (Magaca batoonka waa in la hubiyaa hadba sidiuu isku beddelo)
            await page.get_by_text("Upload").first.click()
            print("Upload Clicked!")
            await asyncio.sleep(5)

        except Exception as e:
            print(f"Error during upload: {e}")
            raise e
        finally:
            await browser.close()

# 4. TELEGRAM HANDLER
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    if not url.startswith("http"):
        await update.message.reply_text("Fadlan soo dir Link-ga muqaalka oo sax ah.")
        return

    msg = await update.message.reply_text("⏳ Muqaalka waa la soo dejinayaa server-ka...")
    
    file_path = "video_temp.mp4"
    try:
        # Download video from link
        r = requests.get(url, stream=True)
        with open(file_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                f.write(chunk)
        
        await msg.edit_text("🚀 Muqaalka waxaa loo dirayaa Rumble (Automation)...")
        
        # Start Rumble Upload
        await upload_to_rumble(file_path, "Muuqaal Cusub")
        
        await msg.edit_text("✅ Guul! Muqaalkii waa la upload gareeyay.")
    
    except Exception as e:
        await msg.edit_text(f"❌ Khalad ayaa dhacay: {str(e)}")
    
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

# 5. MAIN FUNCTION
def main():
    # Start Health Check in Background
    threading.Thread(target=run_health_server, daemon=True).start()

    # Start Telegram Bot
    print("Bot is starting...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()

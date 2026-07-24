import os
import asyncio
import requests
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# Macluumaadka deegaanka (Koyeb ayaan ka gelin doonaa)
RUMBLE_EMAIL = os.getenv("RUMBLE_EMAIL")
RUMBLE_PASS = os.getenv("RUMBLE_PASS")
TOKEN = os.getenv("TELEGRAM_TOKEN")

async def upload_to_rumble(video_path, title):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Login
        await page.goto("https://rumble.com/register/login/")
        await page.fill('input[name="luser"]', RUMBLE_EMAIL)
        await page.fill('input[name="lpass"]', RUMBLE_PASS)
        await page.click('button[type="submit"]')
        await asyncio.sleep(5) # Sugitaanka login-ka

        # Upload Page
        await page.goto("https://rumble.com/upload.php")
        
        # Uploading the file
        async with page.expect_file_chooser() as fc_info:
            await page.click(".upload-file-placeholder")
        file_chooser = await fc_info.value
        await file_chooser.set_files(video_path)

        # Buuxi Title-ka
        await page.fill('#title', title)
        await page.fill('#description', "Uploaded via Telegram Bot")
        
        # Sug inta upload-ku dhamaanayo (Tani waxay u baahan tahay in la sugo batoonka submit)
        await asyncio.sleep(10) 
        # Halkan waxaad ku dari kartaa batoonka 'Submit' haddii uu diyaar yahay
        
        await browser.close()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    video_url = update.message.text
    if not video_url.startswith("http"):
        return

    await update.message.reply_text("Muqaalka waa la bilaabay, fadlan sug...")
    
    file_name = "video.mp4"
    # Soo deji muqaalka
    response = requests.get(video_url, stream=True)
    with open(file_name, 'wb') as f:
        for chunk in response.iter_content(chunk_size=1024):
            f.write(chunk)

    try:
        await upload_to_rumble(file_name, "Muuqaal Cusub")
        await update.message.reply_text("✅ Muqaalkii waa la upload gareeyay!")
    except Exception as e:
        await update.message.reply_text(f"❌ Khalad: {str(e)}")
    finally:
        if os.path.exists(file_name):
            os.remove(file_name)

def main():
    # Ku dar port macmal ah si uusan Koyeb u dhiman
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import threading
    
    def run_server():
        server = HTTPServer(('0.0.0.0', 8080), BaseHTTPRequestHandler)
        server.serve_forever()
    
    threading.Thread(target=run_server, daemon=True).start()

    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()

import os
import re
import urllib.parse
from dotenv import load_dotenv
load_dotenv()
import time
import asyncio
import requests
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ----------------------------------------------------------------------
# SETTINGS
# ----------------------------------------------------------------------
OK_COOKIES_JSON = os.getenv("OK_COOKIES")
TOKEN = os.getenv("TELEGRAM_TOKEN")

# Default wait time for OK.ru processing
UPLOAD_MAX_WAIT_SECONDS = int(os.getenv("UPLOAD_MAX_WAIT_SECONDS", "2700"))

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

VALID_VIDEO_EXTENSIONS = (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".3gp", ".ts")

def sanitize_filename(name, fallback):
    if not name: return fallback
    name = urllib.parse.unquote(name)
    name = os.path.basename(name)
    name = re.sub(r'[\\/:*?"<>|]+', "", name).strip()
    name = re.sub(r"\s+", " ", name)
    if not name: return fallback
    root, ext = os.path.splitext(name)
    if ext.lower() not in VALID_VIDEO_EXTENSIONS:
        name = f"{name}.mp4"
    if len(name) > 150:
        root, ext = os.path.splitext(name)
        name = root[:150 - len(ext)] + ext
    return name

def filename_from_url(url, fallback):
    parsed = urllib.parse.urlparse(url)
    base = os.path.basename(parsed.path)
    return sanitize_filename(base, fallback)

async def safe_edit(msg, text):
    try:
        await msg.edit_text(text)
    except Exception as e:
        if "not modified" not in str(e).lower():
            print(f"Error editing message: {e}")

# ----------------------------------------------------------------------
# DOWNLOAD (URL -> local disk) WITH PROGRESS
# ----------------------------------------------------------------------
async def download_with_progress(url, file_path, msg):
    def _download():
        r = requests.get(url, stream=True, timeout=60)
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(file_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if not chunk: continue
                f.write(chunk)
                downloaded += len(chunk)
                percent = int(downloaded * 100 / total) if total > 0 else None
                yield downloaded, total, percent

    loop = asyncio.get_event_loop()
    last_reported = -1
    last_update_time = 0
    gen = _download()

    while True:
        result = await loop.run_in_executor(None, lambda: next(gen, None))
        if result is None: break
        downloaded, total, percent = result
        now = time.time()
        if now - last_update_time >= 4:
            last_update_time = now
            if percent is not None and percent != last_reported:
                last_reported = percent
                await safe_edit(msg, f"⏳ Soo dejinta muqaalka: {percent}%\n({downloaded/(1024*1024):.1f}MB / {total/(1024*1024):.1f}MB)")

    await safe_edit(msg, "✅ Soo dejinta way dhammaatay. Diyaar u ah upload-ka OK.ru...")

# ----------------------------------------------------------------------
# UPLOAD (local file -> OK.ru)
# ----------------------------------------------------------------------
async def poll_upload_progress(page, msg, stop_event):
    start = time.time()
    while not stop_event.is_set():
        elapsed = int(time.time() - start)
        if elapsed > UPLOAD_MAX_WAIT_SECONDS: break
        try:
            await safe_edit(msg, f"🚀 Upload-ka OK.ru ayaa socda... ({elapsed}s)")
        except: pass
        await asyncio.sleep(10)

VIDEO_LIST_PAGES = ("https://ok.ru/video/myVideo", "https://ok.ru/video/myUnpublished")

async def get_existing_video_ids(page):
    all_ids = set()
    for url in VIDEO_LIST_PAGES:
        await page.goto(url, wait_until="load", timeout=60000)
        await asyncio.sleep(2)
        hrefs = await page.eval_on_selector_all("a[href*='/video/']", "elements => elements.map(e => e.href)")
        for href in hrefs:
            match = re.search(r"/video/(\d+)", href)
            if match: all_ids.add(match.group(1))
    return all_ids

async def upload_to_ok(update, video_path, msg):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        await context.add_cookies(fix_cookies(json.loads(OK_COOKIES_JSON)))
        page = await context.new_page()
        
        try:
            existing_ids = await get_existing_video_ids(page)
            await page.goto("https://ok.ru/video/manager", wait_until="load")
            
            upload_btn = page.get_by_text("Choose a file for upload", exact=False)
            async with page.expect_file_chooser() as fc_info:
                await upload_btn.click()
            await (await fc_info.value).set_files(video_path)

            stop_event = asyncio.Event()
            progress_task = asyncio.create_task(poll_upload_progress(page, msg, stop_event))
            
            # Wait for upload to complete and appear in list
            video_link = None
            for _ in range(60): # Poll for 10 mins max
                await asyncio.sleep(10)
                new_ids = await get_existing_video_ids(page)
                diff = new_ids - existing_ids
                if diff:
                    video_link = f"https://ok.ru/video/{list(diff)[0]}"
                    break
            
            stop_event.set()
            await progress_task
            return True, video_link
        except Exception as e:
            return False, str(e)
        finally:
            await browser.close()

# ----------------------------------------------------------------------
# TELEGRAM HANDLERS
# ----------------------------------------------------------------------
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Salaan! I soo dir Link (URL) muqaal ah si aan ugu upload gareeyo OK.ru.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    if not url or not url.startswith("http"): return

    msg = await update.message.reply_text("⏳ Baadhaya link-ga...")
    file_name = filename_from_url(url, f"video_{update.message.message_id}.mp4")
    file_path = f"./{file_name}"

    try:
        await download_with_progress(url, file_path, msg)
        success, result = await upload_to_ok(update, file_path, msg)
        if success:
            await safe_edit(msg, f"✅ Guul! Muqaalkii waa la upload gareeyay.\n\n🔗 {result}")
        else:
            await safe_edit(msg, f"❌ Upload-ka waa fashilmay: {result}")
    except Exception as e:
        await safe_edit(msg, f"❌ Qalad: {e}")
    finally:
        if os.path.exists(file_path): os.remove(file_path)

async def main_async():
    threading.Thread(target=run_health_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Bot is starting...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main_async())

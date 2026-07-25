import os
import re
import time
import asyncio
import requests
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# SETTINGS
OK_COOKIES_JSON = os.getenv("OK_COOKIES")
TOKEN = os.getenv("TELEGRAM_TOKEN")

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


async def safe_edit(msg, text):
    """Edit a Telegram message but ignore 'message is not modified' errors."""
    try:
        await msg.edit_text(text)
    except Exception as e:
        if "not modified" not in str(e).lower():
            print(f"Khalad la edit gareynayo fariinta: {e}")


# ----------------------------------------------------------------------
# DOWNLOAD (URL -> local disk) WITH PROGRESS
# ----------------------------------------------------------------------
async def download_with_progress(url, file_path, msg):
    def _download():
        r = requests.get(url, stream=True, timeout=60)
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        last_percent_reported = -1
        with open(file_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    percent = int(downloaded * 100 / total)
                else:
                    percent = None
                yield downloaded, total, percent

    loop = asyncio.get_event_loop()
    last_reported = -1
    last_update_time = 0

    # Run the blocking requests download in a thread, but poll it via a queue
    gen = _download()

    def next_chunk():
        try:
            return next(gen)
        except StopIteration:
            return None

    while True:
        result = await loop.run_in_executor(None, next_chunk)
        if result is None:
            break
        downloaded, total, percent = result
        now = time.time()
        if now - last_update_time >= 3:  # Telegram-friendly throttle
            last_update_time = now
            if percent is not None and percent != last_reported:
                last_reported = percent
                mb_done = downloaded / (1024 * 1024)
                mb_total = total / (1024 * 1024)
                await safe_edit(
                    msg,
                    f"⏳ Soo dejinta muqaalka: {percent}%\n"
                    f"({mb_done:.1f}MB / {mb_total:.1f}MB)"
                )
            elif percent is None:
                mb_done = downloaded / (1024 * 1024)
                await safe_edit(msg, f"⏳ Soo dejinta muqaalka: {mb_done:.1f}MB la soo dejiyay...")

    await safe_edit(msg, "✅ Soo dejinta way dhammaatay. Diyaar u ah upload-ka OK.ru...")


# ----------------------------------------------------------------------
# UPLOAD (local file -> OK.ru) WITH PROGRESS + RETURN VIDEO LINK
# ----------------------------------------------------------------------
async def poll_upload_progress(page, msg, stop_event, max_seconds=1200):
    """
    Best-effort progress poller. OK.ru's upload UI shows a progress
    indicator while the file is uploading/processing. Selectors here are
    broad/generic since the exact markup can change - if this stops
    matching, the heartbeat fallback still keeps the user informed.
    """
    start = time.time()
    last_text = None
    last_update_time = 0

    progress_selectors = [
        "[role='progressbar']",
        ".progress-bar",
        ".upload-progress",
        "[class*='progress']",
    ]

    while not stop_event.is_set():
        if time.time() - start > max_seconds:
            break

        found_text = None
        for sel in progress_selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    # Try common attributes/text that carry percentage info
                    aria_val = await loc.get_attribute("aria-valuenow")
                    inner_text = (await loc.inner_text()).strip()
                    if aria_val:
                        found_text = f"{aria_val}%"
                    elif inner_text and re.search(r"\d", inner_text):
                        found_text = inner_text
                    if found_text:
                        break
            except Exception:
                continue

        now = time.time()
        if now - last_update_time >= 5:
            last_update_time = now
            elapsed = int(now - start)
            if found_text and found_text != last_text:
                last_text = found_text
                await safe_edit(msg, f"🚀 Upload-ka OK.ru: {found_text}")
            else:
                await safe_edit(msg, f"🚀 Upload-ka OK.ru ayaa socda... ({elapsed}s)")

        await asyncio.sleep(2)


async def get_latest_video_link(page):
    """
    Navigate to 'My Videos' and grab the link of the most recently
    added video (shown first in the grid, as seen in the account).
    """
    await page.goto("https://ok.ru/video/myVideo", wait_until="load", timeout=60000)
    await asyncio.sleep(3)

    # The first video card/thumbnail link in the "Мои видео" grid
    first_video_link = page.locator("a[href*='/video/']").first
    href = await first_video_link.get_attribute("href")

    if href is None:
        return None

    if href.startswith("http"):
        return href
    return f"https://ok.ru{href}"


async def upload_to_ok(update, video_path, msg):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )

        raw_cookies = json.loads(OK_COOKIES_JSON)
        clean_cookies = fix_cookies(raw_cookies)
        await context.add_cookies(clean_cookies)

        page = await context.new_page()
        stop_event = asyncio.Event()
        progress_task = None

        try:
            print("Tagaya Video Manager...")
            await page.goto("https://ok.ru/video/manager", wait_until="load", timeout=60000)
            await asyncio.sleep(5)

            upload_btn = page.get_by_text("Choose a file for upload", exact=False)
            await upload_btn.wait_for(state="visible", timeout=30000)

            async with page.expect_file_chooser() as fc_info:
                await upload_btn.click()
            file_chooser = await fc_info.value
            await file_chooser.set_files(video_path)

            # Start live progress polling in the background
            progress_task = asyncio.create_task(
                poll_upload_progress(page, msg, stop_event)
            )

            # Give OK.ru time to actually upload + process the file.
            # We still wait a fixed ceiling as a safety net in case the
            # progress indicator never resolves to a clear "done" state.
            await asyncio.sleep(60)

            stop_event.set()
            if progress_task:
                await progress_task

            await safe_edit(msg, "🔗 Ka soo qaadaya link-ga muqaalka cusub...")
            video_link = await get_latest_video_link(page)
            return True, video_link

        except Exception as e:
            stop_event.set()
            if progress_task:
                await progress_task

            # Always surface the REAL error first, before attempting
            # anything else that could itself fail (e.g. a closed page).
            await safe_edit(msg, f"❌ Qalad: {e}")

            # Best-effort screenshot - if the page/browser already
            # crashed or closed, this will fail too, but we don't let
            # that mask the original error above.
            try:
                if not page.is_closed():
                    await page.screenshot(path="debug.png")
                    await update.message.reply_photo(
                        photo=open("debug.png", 'rb'),
                        caption="📸 Sawirka bogga wakhtiga khaladku dhacay"
                    )
            except Exception as screenshot_error:
                print(f"Screenshot-ka lama qaadi karin: {screenshot_error}")

            return False, None
        finally:
            try:
                await browser.close()
            except Exception:
                pass


# ----------------------------------------------------------------------
# TELEGRAM HANDLERS
# ----------------------------------------------------------------------
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message when the user sends /start."""
    welcome_text = (
        "👋 Salaan! Waxaan ahay OK.ru Upload Bot.\n\n"
        "Waxaan kuu upload gareyn karaa muqaallo si toos ah OK.ru account-kaaga.\n\n"
        "📌 Sida loo isticmaalo:\n"
        "1️⃣ I soo dir link (URL) muqaal ah — waan soo dejin doonaa oo upload gareyn doonaa.\n"
        "2️⃣ Ama i soo dir muqaal toos ah (video file) — waan qaadan doonaa oo upload gareyn doonaa.\n\n"
        "Marka ay dhammaato, waxaan ku soo celin doonaa link-ga muqaalka cusub ee OK.ru. 🔗"
    )
    await update.message.reply_text(welcome_text)


async def handle_link_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle a plain text message containing a direct video URL."""
    url = update.message.text
    if not url.startswith("http"):
        return

    msg = await update.message.reply_text("⏳ Soo dejinta muqaalka: 0%")
    file_path = f"video_{update.message.message_id}.mp4"

    try:
        await download_with_progress(url, file_path, msg)

        success, video_link = await upload_to_ok(update, file_path, msg)
        if success:
            if video_link:
                await safe_edit(
                    msg,
                    f"✅ Guul! Muqaalkii waa la upload gareeyay.\n🔗 {video_link}"
                )
            else:
                await safe_edit(
                    msg,
                    "✅ Guul! Muqaalkii waa la upload gareeyay.\n"
                    "(Lama helin link-ga - fadlan hubi 'My Videos' ee OK.ru)"
                )
    except Exception as e:
        await safe_edit(msg, f"❌ Qalad: {str(e)}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


async def handle_video_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle a video/document sent directly in Telegram (no link needed)."""
    tg_file = update.message.video or update.message.document
    if tg_file is None:
        return

    msg = await update.message.reply_text("⏳ Soo dejinta muqaalka ee Telegram...")
    file_path = f"video_{update.message.message_id}.mp4"

    try:
        # Telegram Bot API has a 20MB download limit for regular bots.
        # For bigger files you need a local Bot API server (see chat notes).
        new_file = await context.bot.get_file(tg_file.file_id)
        await new_file.download_to_drive(file_path)
        await safe_edit(msg, "✅ Soo dejinta way dhammaatay. Diyaar u ah upload-ka OK.ru...")

        success, video_link = await upload_to_ok(update, file_path, msg)
        if success:
            if video_link:
                await safe_edit(
                    msg,
                    f"✅ Guul! Muqaalkii waa la upload gareeyay.\n🔗 {video_link}"
                )
            else:
                await safe_edit(
                    msg,
                    "✅ Guul! Muqaalkii waa la upload gareeyay.\n"
                    "(Lama helin link-ga - fadlan hubi 'My Videos' ee OK.ru)"
                )
    except Exception as e:
        await safe_edit(msg, f"❌ Qalad: {str(e)}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link_message))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video_message))
    app.run_polling()

if __name__ == "__main__":
    main()

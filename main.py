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

# ----------------------------------------------------------------------
# SETTINGS
# ----------------------------------------------------------------------
OK_COOKIES_JSON = os.getenv("OK_COOKIES")
TOKEN = os.getenv("TELEGRAM_TOKEN")

# Large files (700MB-1GB+) can take a long time for OK.ru to process
# after the upload itself finishes. Default: 45 minutes. Override by
# setting the UPLOAD_MAX_WAIT_SECONDS environment variable if needed.
UPLOAD_MAX_WAIT_SECONDS = int(os.getenv("UPLOAD_MAX_WAIT_SECONDS", "2700"))

# --- Large-file Telegram downloads (bypasses the 20MB Bot API limit) ---
# Get API_ID / API_HASH from https://my.telegram.org (log in with the
# SAME phone number/account that will be sending videos to the bot).
# SESSION_STRING is generated once - see generate_session.py further
# down in the chat instructions.
TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")
TELEGRAM_SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING")

LARGE_FILE_MODE = bool(TELEGRAM_API_ID and TELEGRAM_API_HASH and TELEGRAM_SESSION_STRING)

pyro_client = None
if LARGE_FILE_MODE:
    from pyrogram import Client as PyroClient
    pyro_client = PyroClient(
        "large_file_downloader",
        api_id=int(TELEGRAM_API_ID),
        api_hash=TELEGRAM_API_HASH,
        session_string=TELEGRAM_SESSION_STRING,
        in_memory=True,
    )


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


async def download_telegram_file_with_progress(chat_id, message_id, file_path, msg):
    """
    Download a large Telegram video/document using the Pyrogram user
    session (bypasses the 20MB Bot API download limit; supports up to
    2GB, or 4GB with Telegram Premium).
    """
    last_update_time = 0

    async def progress(current, total):
        nonlocal last_update_time
        now = time.time()
        if now - last_update_time >= 3:
            last_update_time = now
            percent = int(current * 100 / total) if total else 0
            mb_done = current / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            await safe_edit(
                msg,
                f"⏳ Soo dejinta muqaalka (Telegram): {percent}%\n"
                f"({mb_done:.1f}MB / {mb_total:.1f}MB)"
            )

    tg_message = await pyro_client.get_messages(chat_id, message_ids=message_id)

    has_media = any([
        tg_message.video,
        tg_message.document,
        tg_message.animation,
        tg_message.video_note,
    ])

    if not has_media:
        # Give a clearer, more actionable error than the raw Pyrogram one.
        raise Exception(
            "Fariintan lama soo dejin karo (session-ka userbot-ku ma arko "
            "file dhab ah). Marka inta badan waxaa sababa in fariinta laga "
            "soo diray (forward) bot kale oo 'protected content' dhigay. "
            "Fadlan soo dejiso file-ka gudaha device-kaaga, kadibna u soo "
            "dir bot-kan sida upload cusub (ma aha forward)."
        )

    await pyro_client.download_media(tg_message, file_name=file_path, progress=progress)
    await safe_edit(msg, "✅ Soo dejinta way dhammaatay. Diyaar u ah upload-ka OK.ru...")


# ----------------------------------------------------------------------
# UPLOAD (local file -> OK.ru) WITH PROGRESS + RETURN VIDEO LINK
# ----------------------------------------------------------------------
async def poll_upload_progress(page, msg, stop_event, max_seconds=UPLOAD_MAX_WAIT_SECONDS):
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


# Links that are part of OK.ru's own UI/navigation, never an actual
# uploaded video - if we ever match one of these, it's the wrong link.
NON_VIDEO_PATH_KEYWORDS = (
    "/video/showcase",
    "/video/manager",
    "/video/myVideo",
    "/video/myUnpublished",
    "/video/edit",
    "/video/search",
)

# A real OK.ru video link looks like /video/<numeric-id> (or /video/c<...>)
VIDEO_ID_PATTERN = re.compile(r"/video/(c?\d{5,})")

# OK.ru puts fresh/large uploads here first, before (or instead of)
# 'My Videos', until processing/publishing finishes.
VIDEO_LIST_PAGES = (
    "https://ok.ru/video/myVideo",
    "https://ok.ru/video/myUnpublished",
)


async def _get_video_ids_on_page(page, url):
    """Return the set of real OK.ru video IDs currently listed on a page."""
    await page.goto(url, wait_until="load", timeout=60000)
    await asyncio.sleep(3)

    ids = set()
    candidates = page.locator("a[href*='/video/']")
    count = await candidates.count()

    for i in range(count):
        href = await candidates.nth(i).get_attribute("href")
        if not href:
            continue
        if any(bad in href for bad in NON_VIDEO_PATH_KEYWORDS):
            continue
        match = VIDEO_ID_PATTERN.search(href)
        if match:
            ids.add(match.group(1))

    return ids


async def get_existing_video_ids(page):
    """
    Snapshot of every video ID already present (in both 'My Videos' and
    'Unpublished') BEFORE a new upload starts. Used so we only ever
    report a genuinely NEW video afterward, never a stale/old one.
    """
    all_ids = set()
    for list_url in VIDEO_LIST_PAGES:
        ids = await _get_video_ids_on_page(page, list_url)
        all_ids |= ids
    return all_ids


async def wait_for_new_video_link(page, msg, existing_ids, max_seconds=UPLOAD_MAX_WAIT_SECONDS, poll_every=10):
    """
    Poll both 'My Videos' and 'Unpublished' until a video ID shows up
    that WASN'T in the pre-upload baseline (existing_ids). This is the
    only reliable way to avoid re-reporting an old/stale video when the
    new upload is still processing or has silently failed.
    """
    start = time.time()

    while time.time() - start < max_seconds:
        for list_url in VIDEO_LIST_PAGES:
            ids = await _get_video_ids_on_page(page, list_url)
            new_ids = ids - existing_ids
            if new_ids:
                new_id = next(iter(new_ids))
                return f"https://ok.ru/video/{new_id}"

        elapsed = int(time.time() - start)
        await safe_edit(msg, f"⏳ Muqaalka wali waa la processing gareynayaa... ({elapsed}s)")
        await asyncio.sleep(poll_every)

    return None


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
            print("Diiwaan gelinta muqaallada hore u jira...")
            existing_ids = await get_existing_video_ids(page)
            print(f"Muqaallo hore u jira: {len(existing_ids)}")

            print("Tagaya Video Manager...")
            await page.goto("https://ok.ru/video/manager", wait_until="load", timeout=60000)
            await asyncio.sleep(5)

            upload_btn = page.get_by_text("Choose a file for upload", exact=False)
            await upload_btn.wait_for(state="visible", timeout=30000)

            async with page.expect_file_chooser() as fc_info:
                await upload_btn.click()
            file_chooser = await fc_info.value
            await file_chooser.set_files(video_path)

            progress_task = asyncio.create_task(
                poll_upload_progress(page, msg, stop_event)
            )

            await asyncio.sleep(60)

            stop_event.set()
            if progress_task:
                await progress_task

            await safe_edit(msg, "🔗 Sugaya ilaa muqaalka la processing gareeyo oo link-ga la helo...")
            video_link = await wait_for_new_video_link(page, msg, existing_ids)
            return True, video_link

        except Exception as e:
            stop_event.set()
            if progress_task:
                await progress_task

            await safe_edit(msg, f"❌ Qalad: {e}")

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
    large_file_note = (
        "✅ Faylal waaweyn (>20MB) waa la taageerayaa toos ah.\n\n"
        if LARGE_FILE_MODE else
        "⚠️ Faylal ka weyn 20MB ee toos loo diro Telegram lagama aqbali karo "
        "(u dir link halkii).\n\n"
    )
    welcome_text = (
        "👋 Salaan! Waxaan ahay OK.ru Upload Bot.\n\n"
        "Waxaan kuu upload gareyn karaa muqaallo si toos ah OK.ru account-kaaga.\n\n"
        f"{large_file_note}"
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
                    "(Lama helin link-ga - fadlan hubi 'My Videos'/'Unpublished' ee OK.ru)"
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

    file_path = f"video_{update.message.message_id}.mp4"

    # Bot API download cap is 20MB. Route large files through the
    # Pyrogram user session instead, if it's configured.
    file_size = tg_file.file_size or 0
    twenty_mb = 20 * 1024 * 1024

    if file_size > twenty_mb and not LARGE_FILE_MODE:
        await update.message.reply_text(
            "⚠️ Faylkani wuu ka weynyahay 20MB oo Telegram Bot API si toos "
            "ah uma soo dejin karo.\n\n"
            "Fadlan i soo dir link (URL) muqaalka halkii aad u soo diri lahayd "
            "file-ka toos ah, ama waydii admin-ka bot-ka inuu dejiyo "
            "'large file mode' (TELEGRAM_API_ID / API_HASH / SESSION_STRING)."
        )
        return

    msg = await update.message.reply_text("⏳ Soo dejinta muqaalka ee Telegram...")

    try:
        if file_size > twenty_mb:
            # IMPORTANT: from the userbot's own perspective, this private
            # chat is identified by the BOT's id/username - not the
            # human user's own id (which is what the Bot API's
            # effective_chat.id gives us in a private chat).
            bot_username = context.bot.username
            await download_telegram_file_with_progress(
                bot_username, update.message.message_id, file_path, msg
            )
        else:
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
                    "(Lama helin link-ga - fadlan hubi 'My Videos'/'Unpublished' ee OK.ru)"
                )
    except Exception as e:
        await safe_edit(msg, f"❌ Qalad: {str(e)}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


# ----------------------------------------------------------------------
# ENTRYPOINT
# ----------------------------------------------------------------------
async def main_async():
    threading.Thread(target=run_health_server, daemon=True).start()

    if LARGE_FILE_MODE:
        await pyro_client.start()
        print("✅ Large-file mode (Pyrogram) is ACTIVE.")
    else:
        print("⚠️ Large-file mode is OFF - set TELEGRAM_API_ID, TELEGRAM_API_HASH, "
              "and TELEGRAM_SESSION_STRING to enable >20MB direct uploads.")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link_message))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video_message))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    try:
        # Keep running until interrupted
        stop_signal = asyncio.Event()
        await stop_signal.wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        if LARGE_FILE_MODE:
            await pyro_client.stop()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()

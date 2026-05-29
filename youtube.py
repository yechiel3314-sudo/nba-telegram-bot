import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, time as datetime_time, timedelta
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None


# ==============================
# Telegram
# ==============================
TELEGRAM_TOKEN = "8996455073:AAHXYXjy2T12CzBi-IqramkUSWQ4rDSI6ss"
CHAT_ID = "-1003808107418"

# ==============================
# YouTube settings
# ==============================
YOUTUBE_HANDLE = "@motionstation4342"
STATE_FILE = "youtube_daily_recaps_with_shabbat_state.json"
TIMEZONE = ZoneInfo("Asia/Jerusalem")
SEND_AT = datetime_time(hour=9, minute=15)
CHECK_EVERY_SECONDS = 30

# Keep True only for testing. It sends the latest regular video when the bot starts.
SEND_LATEST_ON_START_FOR_TEST = True

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

sent_video_ids = set()
completed_run_keys = set()
title_cache = {}


def build_session():
    session = requests.Session()
    session.headers.update(HEADERS)

    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )

    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


SESSION = build_session()


# ==============================
# State
# ==============================
def load_state():
    global sent_video_ids, completed_run_keys, title_cache

    if not os.path.exists(STATE_FILE):
        sent_video_ids = set()
        completed_run_keys = set()
        title_cache = {}
        return

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        sent_video_ids = set(data.get("sent_video_ids", []))
        completed_run_keys = set(data.get("completed_run_keys", []))
        title_cache = data.get("title_cache", {}) or {}
    except (OSError, ValueError, TypeError) as e:
        print(f"State load error: {e}")
        sent_video_ids = set()
        completed_run_keys = set()
        title_cache = {}


def save_state():
    try:
        tmp_file = STATE_FILE + ".tmp"

        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "sent_video_ids": sorted(sent_video_ids),
                    "completed_run_keys": sorted(completed_run_keys),
                    "title_cache": title_cache,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_file, STATE_FILE)
    except OSError as e:
        print(f"State save error: {e}")


# ==============================
# Telegram
# ==============================
def send_telegram_message(message):
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "PUT_YOUR_TOKEN_HERE":
        print("Missing TELEGRAM_TOKEN")
        return False

    if not CHAT_ID:
        print("Missing TELEGRAM_CHAT_ID")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message[:4096],
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    try:
        response = SESSION.post(url, json=payload, timeout=20)

        if response.status_code == 200:
            print("Sent to Telegram")
            return True

        print(f"Telegram error {response.status_code}: {response.text}")
        return False
    except requests.RequestException as e:
        print(f"Telegram request error: {e}")
        return False


# ==============================
# Shabbat / Yom Tov
# ==============================
ISRAEL_LAT = 31.778
ISRAEL_LON = 35.235
ISRAEL_TZID = "Asia/Jerusalem"


def is_shabbat_or_yom_tov():
    try:
        url = (
            "https://www.hebcal.com/zmanim"
            f"?cfg=json&im=1&latitude={ISRAEL_LAT}&longitude={ISRAEL_LON}&tzid={ISRAEL_TZID}"
        )

        response = SESSION.get(url, timeout=15)

        if response.status_code != 200:
            print(f"Hebcal status error: {response.status_code}")
            return True

        data = response.json()
        return bool((data.get("status") or {}).get("isAssurBemlacha"))
    except (requests.RequestException, ValueError, TypeError) as e:
        print(f"Hebcal check error: {e}")
        return True


# ==============================
# Translation
# ==============================
def translate_title(title):
    if not title:
        return ""

    if title in title_cache:
        return title_cache[title]

    if GoogleTranslator is None:
        title_cache[title] = title
        save_state()
        return title

    try:
        translated = GoogleTranslator(source="auto", target="iw").translate(title)
        translated = translated or title
    except Exception as e:
        print(f"Title translation error: {e}")
        translated = title

    title_cache[title] = translated
    save_state()
    return translated


# ==============================
# YouTube
# ==============================
def get_channel_id_from_handle(handle):
    url = f"https://www.youtube.com/{handle}"

    try:
        response = SESSION.get(url, timeout=20)
        response.raise_for_status()
        page = response.text

        patterns = [
            r'"channelId":"(UC[^"]+)"',
            r'"externalId":"(UC[^"]+)"',
            r'<meta itemprop="channelId" content="(UC[^"]+)">',
        ]

        for pattern in patterns:
            match = re.search(pattern, page)
            if match:
                return match.group(1)

        print("Could not find channel id")
        return None
    except requests.RequestException as e:
        print(f"YouTube channel request error: {e}")
        return None


def parse_youtube_time(value):
    if not value:
        return None

    try:
        fixed = value.replace("Z", "+00:00")
        return datetime.fromisoformat(fixed).astimezone(TIMEZONE)
    except ValueError:
        return None


def get_channel_videos(channel_id):
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

    try:
        response = SESSION.get(rss_url, timeout=20)
        response.raise_for_status()
        root = ET.fromstring(response.text)
    except requests.RequestException as e:
        print(f"YouTube RSS request error: {e}")
        return []
    except ET.ParseError as e:
        print(f"YouTube RSS parse error: {e}")
        return []

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
    }

    videos = []
    for entry in root.findall("atom:entry", ns):
        video_id_el = entry.find("yt:videoId", ns)
        title_el = entry.find("atom:title", ns)
        published_el = entry.find("atom:published", ns)

        if video_id_el is None or title_el is None or published_el is None:
            continue

        video_id = video_id_el.text or ""
        title = title_el.text or "סרטון חדש"
        published = parse_youtube_time(published_el.text)

        if not video_id or not published:
            continue

        videos.append(
            {
                "id": video_id,
                "title": title,
                "published": published,
                "url": f"https://www.youtube.com/watch?v={video_id}",
            }
        )

    return videos


def is_short_video(video_id):
    watch_url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        response = SESSION.get(watch_url, timeout=20)
        response.raise_for_status()
        page = response.text
    except requests.RequestException as e:
        print(f"Could not inspect video {video_id}: {e}")
        return False

    short_signals = [
        f"https://www.youtube.com/shorts/{video_id}",
        f'"/shorts/{video_id}"',
        '"isShortsEligible":true',
        '"reelWatchEndpoint"',
    ]

    return any(signal in page for signal in short_signals)


# ==============================
# Daily logic
# ==============================
def get_current_window(now=None):
    now = now or datetime.now(TIMEZONE)
    today_at_send_time = datetime.combine(now.date(), SEND_AT, tzinfo=TIMEZONE)

    if now >= today_at_send_time:
        end = today_at_send_time
    else:
        end = today_at_send_time - timedelta(days=1)

    start = end - timedelta(days=1)
    return start, end


def get_run_key(now=None):
    _, end = get_current_window(now)
    return end.strftime("%Y-%m-%d_%H-%M")


def should_run_now():
    now = datetime.now(TIMEZONE)
    today_at_send_time = datetime.combine(now.date(), SEND_AT, tzinfo=TIMEZONE)

    if now < today_at_send_time:
        return False

    return get_run_key(now) not in completed_run_keys


def build_daily_message(videos, start, end):
    if len(videos) == 1:
        header = "🏀 <b>תקציר NBA חדש עלה!</b>"
    else:
        header = f"🏀 <b>{len(videos)} תקצירי NBA חדשים עלו!</b>"

    lines = [
        header,
        "",
        f"חלון בדיקה: {start.strftime('%d/%m/%Y %H:%M')} עד {end.strftime('%d/%m/%Y %H:%M')}",
        "",
    ]

    for index, video in enumerate(videos, start=1):
        original_title = video["title"]
        translated_title = translate_title(original_title)
        published = video["published"].strftime("%d/%m/%Y %H:%M")

        lines.append(f"{index}. <b>{html.escape(translated_title)}</b>")
        if translated_title != original_title:
            lines.append(f"מקור: {html.escape(original_title)}")
        lines.append(f"עלה: {published}")
        lines.append(f"▶️ {html.escape(video['url'])}")
        lines.append("")

    return "\n".join(lines).strip()


def find_new_daily_videos(channel_id):
    start, end = get_current_window()
    videos = get_channel_videos(channel_id)
    selected = []

    for video in videos:
        if video["id"] in sent_video_ids:
            continue

        if not (start <= video["published"] < end):
            continue

        if is_short_video(video["id"]):
            print(f"Skipping short: {video['title']}")
            sent_video_ids.add(video["id"])
            continue

        selected.append(video)

    selected.sort(key=lambda item: item["published"])
    return selected, start, end


def mark_daily_run_completed(videos):
    for video in videos:
        sent_video_ids.add(video["id"])

    completed_run_keys.add(get_run_key())
    save_state()


def run_daily_send(channel_id):
    videos, start, end = find_new_daily_videos(channel_id)

    if is_shabbat_or_yom_tov():
        print("Shabbat/Yom Tov active. Daily send skipped and marked completed.")
        mark_daily_run_completed(videos)
        return True

    if not videos:
        print("No new non-short videos for this daily window")
        completed_run_keys.add(get_run_key())
        save_state()
        return True

    message = build_daily_message(videos, start, end)
    ok = send_telegram_message(message)

    if ok:
        mark_daily_run_completed(videos)

    return ok


def send_latest_video_for_test(channel_id):
    if is_shabbat_or_yom_tov():
        print("Startup test skipped because Shabbat/Yom Tov is active.")
        return

    videos = get_channel_videos(channel_id)

    if not videos:
        print("No videos found for startup test")
        return

    for video in videos:
        if is_short_video(video["id"]):
            continue

        translated_title = translate_title(video["title"])
        message = (
            "🧪 <b>בדיקת בוט יוטיוב</b>\n\n"
            "זה הסרטון האחרון שאינו Short שמצאתי בערוץ:\n\n"
            f"🎬 <b>{html.escape(translated_title)}</b>\n"
        )

        if translated_title != video["title"]:
            message += f"מקור: {html.escape(video['title'])}\n"

        message += (
            f"עלה: {video['published'].strftime('%d/%m/%Y %H:%M')}\n\n"
            f"▶️ {html.escape(video['url'])}"
        )

        if send_telegram_message(message):
            print("Startup test video sent")
        return

    print("Only Shorts were found for startup test")


# ==============================
# Main
# ==============================
if __name__ == "__main__":
    print("YouTube daily recaps bot with Shabbat guard started")
    load_state()

    channel_id = get_channel_id_from_handle(YOUTUBE_HANDLE)
    if not channel_id:
        raise SystemExit("Could not resolve YouTube channel id")

    print(f"Channel id: {channel_id}")

    if SEND_LATEST_ON_START_FOR_TEST:
        send_latest_video_for_test(channel_id)

    while True:
        try:
            if should_run_now():
                run_daily_send(channel_id)

            time.sleep(CHECK_EVERY_SECONDS)
        except Exception as e:
            print(f"Main loop error: {e}")
            time.sleep(CHECK_EVERY_SECONDS)

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
import yt_dlp


# ==============================
# Telegram
# ==============================
TELEGRAM_TOKEN = "8996455073:AAHXYXjy2T12CzBi-IqramkUSWQ4rDSI6ss"
CHAT_ID = "-1003808107418"


# ==============================
# YouTube settings
# ==============================
YOUTUBE_HANDLE = "@motionstation4342"
STATE_FILE = "youtube_video_bot_state.json"
TIMEZONE = ZoneInfo("Asia/Jerusalem")
SEND_AT = datetime_time(hour=9, minute=15)
CHECK_EVERY_SECONDS = 30

# שימי True רק לבדיקה ראשונה
SEND_LATEST_ON_START_FOR_TEST = False

DOWNLOAD_DIR = "downloaded_videos"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

sent_video_ids = set()
completed_run_keys = set()


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
    global sent_video_ids, completed_run_keys

    if not os.path.exists(STATE_FILE):
        sent_video_ids = set()
        completed_run_keys = set()
        return

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        sent_video_ids = set(data.get("sent_video_ids", []))
        completed_run_keys = set(data.get("completed_run_keys", []))

    except Exception as e:
        print(f"State load error: {e}")
        sent_video_ids = set()
        completed_run_keys = set()


def save_state():
    try:
        tmp_file = STATE_FILE + ".tmp"

        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "sent_video_ids": sorted(sent_video_ids),
                    "completed_run_keys": sorted(completed_run_keys),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_file, STATE_FILE)

    except Exception as e:
        print(f"State save error: {e}")


# ==============================
# Telegram
# ==============================
def send_telegram_video(video_path, title):
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "PUT_YOUR_TOKEN_HERE":
        print("Missing TELEGRAM_TOKEN")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"

    try:
        with open(video_path, "rb") as video_file:
            files = {
                "video": video_file
            }

            data = {
                "chat_id": CHAT_ID,
                "caption": html.escape(title)[:1024],
                "parse_mode": "HTML",
                "supports_streaming": "true",
            }

            response = SESSION.post(url, data=data, files=files, timeout=300)

        if response.status_code == 200:
            print("Video sent to Telegram")
            return True

        print(f"Telegram error {response.status_code}: {response.text}")
        return False

    except Exception as e:
        print(f"Telegram send video error: {e}")
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

    except Exception as e:
        print(f"Hebcal check error: {e}")
        return True


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

    except Exception as e:
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

    except Exception as e:
        print(f"YouTube RSS error: {e}")
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

    except Exception as e:
        print(f"Could not inspect video {video_id}: {e}")
        return False

    short_signals = [
        f"https://www.youtube.com/shorts/{video_id}",
        f'"/shorts/{video_id}"',
        '"isShortsEligible":true',
        '"reelWatchEndpoint"',
    ]

    return any(signal in page for signal in short_signals)


def download_youtube_video(video):
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    output_template = os.path.join(DOWNLOAD_DIR, f"{video['id']}.%(ext)s")

    ydl_opts = {
        "outtmpl": output_template,
        "format": "best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video["url"], download=True)
            downloaded_path = ydl.prepare_filename(info)

            if not downloaded_path.endswith(".mp4"):
                mp4_path = os.path.splitext(downloaded_path)[0] + ".mp4"
                if os.path.exists(mp4_path):
                    downloaded_path = mp4_path

            return downloaded_path

    except Exception as e:
        print(f"Download error: {e}")
        return None


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
    return selected


def mark_video_sent(video_id):
    sent_video_ids.add(video_id)
    save_state()


def mark_daily_run_completed():
    completed_run_keys.add(get_run_key())
    save_state()


def run_daily_send(channel_id):
    if is_shabbat_or_yom_tov():
        print("Shabbat/Yom Tov active. Daily send skipped.")
        mark_daily_run_completed()
        return True

    videos = find_new_daily_videos(channel_id)

    if not videos:
        print("No new non-short videos for this daily window")
        mark_daily_run_completed()
        return True

    for video in videos:
        print(f"Downloading: {video['title']}")

        video_path = download_youtube_video(video)

        if not video_path or not os.path.exists(video_path):
            print("Video download failed")
            continue

        ok = send_telegram_video(video_path, video["title"])

        if ok:
            mark_video_sent(video["id"])

        try:
            os.remove(video_path)
        except Exception as e:
            print(f"Could not delete video file: {e}")

    mark_daily_run_completed()
    return True


def send_latest_video_for_test(channel_id):
    if is_shabbat_or_yom_tov():
        print("Startup test skipped because Shabbat/Yom Tov is active.")
        return

    videos = get_channel_videos(channel_id)

    if not videos:
        print("No videos found")
        return

    for video in videos:
        if is_short_video(video["id"]):
            continue

        print(f"Downloading latest video: {video['title']}")

        video_path = download_youtube_video(video)

        if not video_path or not os.path.exists(video_path):
            print("Video download failed")
            return

        ok = send_telegram_video(video_path, video["title"])

        if ok:
            mark_video_sent(video["id"])

        try:
            os.remove(video_path)
        except Exception as e:
            print(f"Could not delete video file: {e}")

        return

    print("Only Shorts were found")


# ==============================
# Main
# ==============================
if __name__ == "__main__":
    print("YouTube video bot started")
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

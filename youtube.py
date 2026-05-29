import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, time as datetime_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yt_dlp
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ==============================
# Proxy bypass
# ==============================
# Forces direct connections even when Windows, Python, or the hosting panel
# has HTTP_PROXY / HTTPS_PROXY / ALL_PROXY configured.
FORCE_DIRECT_CONNECTION = True
YOUTUBE_PROXY = os.getenv("YOUTUBE_PROXY", "").strip()
YOUTUBE_GEO_BYPASS_COUNTRY = os.getenv("YOUTUBE_GEO_BYPASS_COUNTRY", "US").strip()


def disable_proxy_environment():
    if not FORCE_DIRECT_CONNECTION:
        return

    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    ):
        os.environ.pop(key, None)


disable_proxy_environment()


# ==============================
# Telegram
# ==============================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-1003808107418").strip()
SEND_LINK_WHEN_DOWNLOAD_BLOCKED = os.getenv("SEND_LINK_WHEN_DOWNLOAD_BLOCKED", "false").lower() == "true"


# ==============================
# YouTube settings
# ==============================
YOUTUBE_HANDLE = "@motionstation4342"
STATE_FILE = Path("youtube_video_bot_state.json")
TIMEZONE = ZoneInfo("Asia/Jerusalem")
SEND_AT = datetime_time(hour=9, minute=15)
CHECK_EVERY_SECONDS = 30

# שימי True רק לבדיקה ראשונה, ואז להחזיר ל-False
SEND_LATEST_ON_START_FOR_TEST = False

DOWNLOAD_DIR = Path("downloaded_videos")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    )
}

sent_video_ids = set()
completed_run_keys = set()


def build_session():
    session = requests.Session()
    session.headers.update(HEADERS)

    if FORCE_DIRECT_CONNECTION:
        session.trust_env = False
        session.proxies = {}

    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
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

    if not STATE_FILE.exists():
        sent_video_ids = set()
        completed_run_keys = set()
        return

    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)

        sent_video_ids = set(data.get("sent_video_ids", []))
        completed_run_keys = set(data.get("completed_run_keys", []))

    except Exception as e:
        print(f"State load error: {e}")
        sent_video_ids = set()
        completed_run_keys = set()


def save_state():
    try:
        tmp_file = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")

        with tmp_file.open("w", encoding="utf-8") as f:
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
    if not TELEGRAM_TOKEN:
        print("Missing TELEGRAM_TOKEN environment variable")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"

    try:
        with open(video_path, "rb") as video_file:
            response = SESSION.post(
                url,
                data={
                    "chat_id": CHAT_ID,
                    "caption": html.escape(title)[:1024],
                    "parse_mode": "HTML",
                    "supports_streaming": "true",
                },
                files={"video": video_file},
                timeout=300,
            )

        if response.status_code == 200:
            print("Video sent to Telegram")
            return True

        print(f"Telegram error {response.status_code}: {response.text}")
        return False

    except Exception as e:
        print(f"Telegram send video error: {e}")
        return False


def send_telegram_message(text):
    if not TELEGRAM_TOKEN:
        print("Missing TELEGRAM_TOKEN environment variable")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        response = SESSION.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": text[:4096],
                "disable_web_page_preview": "false",
            },
            timeout=60,
        )

        if response.status_code == 200:
            print("Message sent to Telegram")
            return True

        print(f"Telegram message error {response.status_code}: {response.text}")
        return False

    except Exception as e:
        print(f"Telegram send message error: {e}")
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


def is_permanent_youtube_error(error):
    text = str(error).lower()
    permanent_signals = [
        "not made this video available in your country",
        "video unavailable",
        "private video",
        "this video has been removed",
        "this video is no longer available",
    ]
    return any(signal in text for signal in permanent_signals)


def download_youtube_video(video):
    DOWNLOAD_DIR.mkdir(exist_ok=True)

    output_template = str(DOWNLOAD_DIR / f"{video['id']}.%(ext)s")

    ydl_opts = {
        "outtmpl": output_template,
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": False,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
        "http_headers": HEADERS,
        "geo_bypass": True,
        "geo_bypass_country": YOUTUBE_GEO_BYPASS_COUNTRY,
    }

    if YOUTUBE_PROXY:
        ydl_opts["proxy"] = YOUTUBE_PROXY
    elif FORCE_DIRECT_CONNECTION:
        ydl_opts["proxy"] = ""

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
        if is_permanent_youtube_error(e):
            return "SKIP_PERMANENT_YOUTUBE_ERROR"
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
            save_state()
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

    all_sent = True

    for video in videos:
        print(f"Downloading: {video['title']}")

        video_path = download_youtube_video(video)

        if video_path == "SKIP_PERMANENT_YOUTUBE_ERROR":
            print("Skipping video because YouTube says it is unavailable from this server/location")
            if SEND_LINK_WHEN_DOWNLOAD_BLOCKED:
                ok = send_telegram_message(f"{video['title']}\n{video['url']}")
                if ok:
                    mark_video_sent(video["id"])
                else:
                    all_sent = False
            else:
                mark_video_sent(video["id"])
            continue

        if not video_path or not os.path.exists(video_path):
            print("Video download failed")
            all_sent = False
            continue

        ok = send_telegram_video(video_path, video["title"])

        if ok:
            mark_video_sent(video["id"])
        else:
            all_sent = False

        try:
            os.remove(video_path)
        except Exception as e:
            print(f"Could not delete video file: {e}")

    if all_sent:
        mark_daily_run_completed()
    else:
        print("Some videos failed. The bot will retry on the next check.")

    return all_sent


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

        if video_path == "SKIP_PERMANENT_YOUTUBE_ERROR":
            print("Latest video is unavailable from this server/location")
            if SEND_LINK_WHEN_DOWNLOAD_BLOCKED:
                ok = send_telegram_message(f"{video['title']}\n{video['url']}")
                if ok:
                    mark_video_sent(video["id"])
            else:
                mark_video_sent(video["id"])
            return

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

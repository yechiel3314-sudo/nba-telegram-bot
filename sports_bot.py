import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Tuple

import requests

# =========================================================
# הגדרות
# =========================================================
BOT_TAG = os.getenv("BOT_TAG", "motionstation_api_bot")

CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "UC0v-tlzsn0QZwJnkiaUSJVQ")
API_KEY = os.getenv("YOUTUBE_API_KEY", "AIzaSyAHEN7hSaTejSUH53CACsM5dzDANrvsR6U")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE")
CHAT_ID = os.getenv("CHAT_ID", "-1003808107418")

LOCAL_TZ_NAME = os.getenv("LOCAL_TZ_NAME", "Asia/Jerusalem")
RUN_HOUR = int(os.getenv("RUN_HOUR", "9"))
RUN_MINUTE = int(os.getenv("RUN_MINUTE", "30"))

STATE_FILE = os.getenv("STATE_FILE", f"{BOT_TAG}_state.json")
LOCK_FILE = os.getenv("LOCK_FILE", f"{BOT_TAG}.lock")

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
SLEEP_BETWEEN_SENDS = int(os.getenv("SLEEP_BETWEEN_SENDS", "20"))
SCAN_PAGE_SIZE = int(os.getenv("SCAN_PAGE_SIZE", "50"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "3"))

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

TEAM_TRANSLATIONS = {
    "Hawks": "אטלנטה הוקס",
    "Celtics": "בוסטון סלטיקס",
    "Nets": "ברוקלין נטס",
    "Hornets": "שארלוט הורנטס",
    "Bulls": "שיקגו בולס",
    "Cavaliers": "קליבלנד קאבלירס",
    "Mavericks": "דאלאס מאבריקס",
    "Nuggets": "דנבר נאגטס",
    "Pistons": "דטרויט פיסטונס",
    "Warriors": "גולדן סטייט ווריורס",
    "Rockets": "יוסטון רוקטס",
    "Pacers": "אינדיאנה פייסרס",
    "Clippers": "לוס אנג'לס קליפרס",
    "Lakers": "לוס אנג'לס לייקרס",
    "Grizzlies": "ממפיס גריזליס",
    "Heat": "מיאמי היט",
    "Bucks": "מילווקי באקס",
    "Timberwolves": "מינסוטה טימברוולבס",
    "Pelicans": "ניו אורלינס פליקנס",
    "Knicks": "ניו יורק ניקס",
    "Thunder": "אוקלהומה סיטי ת'אנדר",
    "Magic": "אורלנדו מג'יק",
    "76ers": "פילדלפיה 76",
    "Sixers": "פילדלפיה 76",
    "Suns": "פיניקס סאנס",
    "Blazers": "פורטלנד טרייל בלייזרס",
    "Kings": "סקרמנטו קינגס",
    "Spurs": "סן אנטוניו ספרס",
    "Raptors": "טורונטו ראפטורס",
    "Jazz": "יוטה ג'אז",
    "Wizards": "וושינגטון וויזארדס",
}

# =========================================================
# לוגים וכלי זמן
# =========================================================
def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def now_local() -> datetime:
    return datetime.now(ZoneInfo(LOCAL_TZ_NAME))

# =========================================================
# בדיקות התחלה
# =========================================================
def validate_settings() -> None:
    missing = []
    if not API_KEY:
        missing.append("YOUTUBE_API_KEY")
    if not TELEGRAM_TOKEN:
        missing.append("TELEGRAM_TOKEN")
    if not CHAT_ID:
        missing.append("CHAT_ID")
    if not CHANNEL_ID:
        missing.append("YOUTUBE_CHANNEL_ID")

    if missing:
        raise SystemExit(f"Missing env vars: {', '.join(missing)}")

# =========================================================
# Lock כדי שלא ירוצו שתי אינסטנסים של הבוט הזה
# =========================================================
def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def acquire_lock() -> bool:
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r", encoding="utf-8") as f:
                old_pid = int(f.read().strip() or "0")
            if old_pid and _pid_alive(old_pid):
                log(f"Another instance is already running (pid={old_pid}).")
                return False
        except Exception:
            pass

        try:
            os.remove(LOCK_FILE)
        except Exception:
            pass

    with open(LOCK_FILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    return True

def release_lock() -> None:
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass

# =========================================================
# State
# =========================================================
def default_state() -> Dict:
    return {
        "first_run_done": False,
        "last_daily_run": None,
        "sent_ids": []
    }

def load_state() -> Dict:
    if not os.path.exists(STATE_FILE):
        return default_state()

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        state = default_state()
        state.update(data if isinstance(data, dict) else {})
        if not isinstance(state.get("sent_ids"), list):
            state["sent_ids"] = []
        return state
    except Exception:
        return default_state()

def save_state(state: Dict) -> None:
    temp_file = f"{STATE_FILE}.tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(temp_file, STATE_FILE)

def get_sent_set(state: Dict) -> set:
    return set(state.get("sent_ids", []))

def remember_sent(state: Dict, video_id: str) -> None:
    sent = get_sent_set(state)
    sent.add(video_id)
    state["sent_ids"] = sorted(sent)

# =========================================================
# YouTube API הרשמי
# =========================================================
def youtube_api(endpoint: str, params: Dict) -> Dict:
    url = f"{YOUTUBE_API_BASE}/{endpoint}"
    query = dict(params)
    query["key"] = API_KEY

    response = requests.get(url, params=query, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    data = response.json()
    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(str(data["error"]))
    return data

def get_uploads_playlist_id() -> str:
    data = youtube_api(
        "channels",
        {
            "part": "contentDetails",
            "id": CHANNEL_ID
        }
    )

    items = data.get("items", [])
    if not items:
        raise RuntimeError("Channel not found or no contentDetails available.")

    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

# =========================================================
# פרסור Duration
# =========================================================
def parse_iso8601_duration(duration: str) -> int:
    """
    Converts values like PT1H2M3S to total seconds.
    """
    if not duration:
        return 0

    pattern = re.compile(
        r"PT"
        r"(?:(?P<hours>\d+)H)?"
        r"(?:(?P<minutes>\d+)M)?"
        r"(?:(?P<seconds>\d+)S)?"
    )
    match = pattern.fullmatch(duration)
    if not match:
        return 0

    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return hours * 3600 + minutes * 60 + seconds

def chunked(values: List[str], size: int = 50) -> List[List[str]]:
    return [values[i:i + size] for i in range(0, len(values), size)]

# =========================================================
# שליפת סרטונים אחרונים דרך API רשמי
# =========================================================
def fetch_recent_uploads(cutoff_utc: datetime) -> List[Dict]:
    uploads_playlist_id = get_uploads_playlist_id()
    videos: List[Dict] = []

    page_token: Optional[str] = None
    pages_seen = 0

    while True:
        pages_seen += 1
        if pages_seen > MAX_PAGES:
            break

        params = {
            "part": "snippet,contentDetails",
            "playlistId": uploads_playlist_id,
            "maxResults": SCAN_PAGE_SIZE
        }
        if page_token:
            params["pageToken"] = page_token

        data = youtube_api("playlistItems", params)
        items = data.get("items", [])

        if not items:
            break

        stop_early = False

        for item in items:
            snippet = item.get("snippet", {})
            resource_id = snippet.get("resourceId", {})
            video_id = resource_id.get("videoId")

            if not video_id:
                continue

            title = snippet.get("title", "").strip()
            published_at = snippet.get("publishedAt")
            if not published_at:
                continue

            published_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))

            if published_dt < cutoff_utc:
                stop_early = True
                break

            videos.append(
                {
                    "id": video_id,
                    "title": title,
                    "published_at": published_dt,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                }
            )

        if stop_early:
            break

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return videos

def fetch_durations(video_ids: List[str]) -> Dict[str, int]:
    durations: Dict[str, int] = {}

    for group in chunked(video_ids, 50):
        data = youtube_api(
            "videos",
            {
                "part": "contentDetails",
                "id": ",".join(group),
            }
        )

        for item in data.get("items", []):
            vid = item.get("id")
            content_details = item.get("contentDetails", {})
            duration_raw = content_details.get("duration", "")
            durations[vid] = parse_iso8601_duration(duration_raw)

    return durations

# =========================================================
# פילטרים
# =========================================================
def is_short_title(title: str) -> bool:
    lower = title.lower()
    return (
        "short" in lower
        or "#shorts" in lower
        or "shorts" in lower
    )

def looks_like_game(title: str) -> bool:
    lower = title.lower()
    include_keywords = [
        "recap",
        "highlight",
        "highlights",
        "full game",
        "game recap",
        "game highlights",
        "full-game",
    ]
    return any(keyword in lower for keyword in include_keywords)

def is_short_duration(duration_seconds: Optional[int]) -> bool:
    if duration_seconds is None:
        return False
    return duration_seconds < 70

# =========================================================
# תרגום קבוצות והודעה
# =========================================================
def extract_teams(title: str) -> Tuple[Optional[str], Optional[str]]:
    match = re.search(r":\s*(.*?)\s*\d+,\s*(.*?)\s*\d+", title)

    if match:
        t1 = TEAM_TRANSLATIONS.get(match.group(1).strip())
        t2 = TEAM_TRANSLATIONS.get(match.group(2).strip())
        if t1 and t2:
            return t1, t2

    return None, None

def build_message(title: str) -> str:
    t1, t2 = extract_teams(title)
    if t1 and t2:
        return f"{t1} 🆚 {t2}"
    return f"🏀 {title}"

# =========================================================
# טלגרם
# =========================================================
def send_telegram_message(text: str, url: str) -> bool:
    try:
        payload = {
            "chat_id": CHAT_ID,
            "text": f"{text}\n{url}",
            "disable_web_page_preview": False,
        }

        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data=payload,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 200:
            log(f"Sent: {text}")
            return True

        log(f"Telegram error: {response.text}")
        return False

    except Exception as e:
        log(f"Telegram crash: {e}")
        return False

# =========================================================
# עיבוד רשימת סרטונים
# =========================================================
def filter_videos(videos: List[Dict], state: Dict) -> List[Dict]:
    sent_ids = get_sent_set(state)
    filtered: List[Dict] = []

    ids_for_duration = [v["id"] for v in videos]
    duration_map = fetch_durations(ids_for_duration) if ids_for_duration else {}

    for video in videos:
        video_id = video["id"]
        title = video["title"]
        duration = duration_map.get(video_id)

        if video_id in sent_ids:
            continue

        if is_short_title(title):
            continue

        if not looks_like_game(title):
            continue

        if is_short_duration(duration):
            continue

        video["duration"] = duration
        filtered.append(video)

    return filtered

def send_video_batch(videos: List[Dict], state: Dict, label: str) -> None:
    if not videos:
        log(f"No videos to send for {label}.")
        return

    for index, video in enumerate(videos, start=1):
        title = video["title"]
        url = video["url"]
        video_id = video["id"]

        message = build_message(title)
        log(f"{label} [{index}/{len(videos)}] {message}")

        ok = send_telegram_message(message, url)

        if ok:
            remember_sent(state, video_id)
            save_state(state)

        time.sleep(SLEEP_BETWEEN_SENDS)

# =========================================================
# ריצה ראשונה: כל 24 השעות האחרונות
# =========================================================
def first_run(state: Dict) -> None:
    log("FIRST RUN started: sending last 24 hours")
    cutoff_utc = now_utc() - timedelta(hours=24)

    videos = fetch_recent_uploads(cutoff_utc)
    log(f"Found {len(videos)} videos in the last 24h before filtering")

    filtered = filter_videos(videos, state)
    log(f"{len(filtered)} videos remain after filtering")

    send_video_batch(filtered, state, "FIRST RUN")

    state["first_run_done"] = True
    save_state(state)
    log("FIRST RUN completed")

# =========================================================
# ריצה יומית ב-09:30
# =========================================================
def daily_run(state: Dict) -> None:
    log("DAILY RUN started: sending last 24 hours")
    cutoff_utc = now_utc() - timedelta(hours=24)

    videos = fetch_recent_uploads(cutoff_utc)
    log(f"Found {len(videos)} videos in the last 24h before filtering")

    filtered = filter_videos(videos, state)
    log(f"{len(filtered)} videos remain after filtering")

    send_video_batch(filtered, state, "DAILY RUN")

    state["last_daily_run"] = now_local().date().isoformat()
    save_state(state)
    log("DAILY RUN completed")

# =========================================================
# לולאת המתנה רק ל-09:30
# =========================================================
def should_run_now(last_run_date: Optional[str]) -> bool:
    local = now_local()
    return (
        local.hour == RUN_HOUR
        and local.minute == RUN_MINUTE
        and last_run_date != local.date().isoformat()
    )

def sleep_with_ticks(total_seconds: int = 20) -> None:
    time.sleep(total_seconds)

def main_loop() -> None:
    log("BOT STARTED")
    state = load_state()

    if not state.get("first_run_done", False):
        first_run(state)
        state = load_state()

    log(f"Waiting for {RUN_HOUR:02d}:{RUN_MINUTE:02d} local time ({LOCAL_TZ_NAME})")

    while True:
        try:
            state = load_state()
            last_daily_run = state.get("last_daily_run")

            if should_run_now(last_daily_run):
                daily_run(state)
                sleep_with_ticks(60)

        except Exception as e:
            log(f"LOOP ERROR: {e}")

        sleep_with_ticks(20)

# =========================================================
# START
# =========================================================
if __name__ == "__main__":
    validate_settings()

    if not acquire_lock():
        raise SystemExit(0)

    try:
        main_loop()
    finally:
        release_lock()

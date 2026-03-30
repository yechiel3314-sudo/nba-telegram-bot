import requests
import time
import pytz
import logging
import json
import os
from datetime import datetime, timedelta

# ==============================================================================
# --- הגדרות מערכת וקונפיגורציה ---
# ==============================================================================

TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# שעת התחלת ניסיון שליחת לוח המשחקים
SCHEDULE_TIME_STR = "18:00"

# כל כמה שניות הלולאה הראשית בודקת
CHECK_INTERVAL = 30

# אם לא נשלח - כל כמה דקות לנסות שוב
RETRY_EVERY_MINUTES = 15

# קובץ שמירת מצב כדי למנוע כפילויות גם אחרי restart
STATE_FILE = "schedule_state.json"

ESPN_API_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
RTL_MARK = "\u200f"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ==============================================================================
# --- מילון תרגום קבוצות NBA ---
# ==============================================================================

NBA_HEBREW_MAP = {
    "Atlanta Hawks": "אטלנטה הוקס",
    "Boston Celtics": "בוסטון סלטיקס",
    "Brooklyn Nets": "ברוקלין נטס",
    "Charlotte Hornets": "שארלוט הורנטס",
    "Chicago Bulls": "שיקגו בולס",
    "Cleveland Cavaliers": "קליבלנד קאבלירס",
    "Dallas Mavericks": "דאלאס מאבריקס",
    "Denver Nuggets": "דנבר נאגטס",
    "Detroit Pistons": "דטרויט פיסטונס",
    "Golden State Warriors": "גולדן סטייט ווריורס",
    "Houston Rockets": "יוסטון רוקטס",
    "Indiana Pacers": "אינדיאנה פייסרס",
    "LA Clippers": "לוס אנג'לס קליפרס",
    "Los Angeles Lakers": "לוס אנג'לס לייקרס",
    "Memphis Grizzlies": "ממפיס גריזליס",
    "Miami Heat": "מיאמי היט",
    "Milwaukee Bucks": "מילווקי באקס",
    "Minnesota Timberwolves": "מינסוטה טימברוולבס",
    "New Orleans Pelicans": "ניו אורלינס פליקנס",
    "New York Knicks": "ניו יורק ניקס",
    "Oklahoma City Thunder": "אוקלהומה סיטי ת'אנדר",
    "Orlando Magic": "אורלנדו מג'יק",
    "Philadelphia 76ers": "פילדלפיה 76",
    "Phoenix Suns": "פיניקס סאנס",
    "Portland Trail Blazers": "פורטלנד טרייל בלייזרס",
    "Sacramento Kings": "סקרמנטו קינגס",
    "San Antonio Spurs": "סן אנטוניו ספרס",
    "Toronto Raptors": "טורונטו ראפטורס",
    "Utah Jazz": "יוטה ג'אז",
    "Washington Wizards": "וושינגטון וויזארדס"
}

# ==============================================================================
# --- ניהול מצב (State) ---
# ==============================================================================

def load_state():
    default_state = {
        "last_sent_date": None,
        "last_try_time": None,
        "last_successful_message_hash": None
    }

    if not os.path.exists(STATE_FILE):
        logger.info("State file not found. Creating fresh state.")
        return default_state

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        for key in default_state:
            if key not in data:
                data[key] = default_state[key]

        return data

    except Exception as e:
        logger.error(f"Failed to load state file: {e}")
        return default_state

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to save state file: {e}")

# ==============================================================================
# --- פונקציות עזר ---
# ==============================================================================

def get_israeli_flag(name_en):
    if any(x in name_en for x in ["Brooklyn", "Portland"]):
        return " 🇮🇱"
    return ""

def format_team(name_en):
    heb = NBA_HEBREW_MAP.get(name_en, name_en)
    flag = get_israeli_flag(name_en)
    return f"{heb}{flag}"

def parse_iso_datetime(raw_time):
    try:
        return datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
    except Exception:
        return None

def get_date_strings_for_fetch():
    """
    מושך היום + מחר + מחרתיים
    כדי לא לפספס משחקי לילה לפי UTC
    """
    isr_tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(isr_tz)

    dates = []
    for i in range(3):
        d = now + timedelta(days=i)
        dates.append(d.strftime("%Y%m%d"))

    return dates

def get_message_hash(text):
    return str(hash(text.strip()))

# ==============================================================================
# --- שליפת לו"ז NBA ---
# ==============================================================================

def get_nba_schedule():
    schedule = []
    seen_ids = set()

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www.espn.com/",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache"
    }

    date_list = get_date_strings_for_fetch()
    logger.info(f"Fetching schedule for dates: {date_list}")

    for date_str in date_list:
        try:
            url = f"{ESPN_API_URL}?dates={date_str}&_={int(time.time())}"
            logger.info(f"Fetching ESPN schedule: {url}")

            r = requests.get(url, headers=headers, timeout=20)
            r.raise_for_status()

            payload = r.json()
            events = payload.get("events", [])

            logger.info(f"Date {date_str}: ESPN returned {len(events)} events")

            for ev in events:
                try:
                    event_uid = ev.get("uid") or ev.get("id")
                    if not event_uid or event_uid in seen_ids:
                        continue

                    competitions = ev.get("competitions", [])
                    if not competitions:
                        continue

                    comp = competitions[0]
                    competitors = comp.get("competitors", [])

                    home = next((t for t in competitors if t.get("homeAway") == "home"), None)
                    away = next((t for t in competitors if t.get("homeAway") == "away"), None)

                    if not home or not away:
                        continue

                    raw_time = ev.get("date")
                    if not raw_time:
                        continue

                    utc_dt = parse_iso_datetime(raw_time)
                    if not utc_dt:
                        continue

                    status_obj = ev.get("status", {}).get("type", {})
                    status_id = str(status_obj.get("id", ""))
                    status_name = status_obj.get("name", "")
                    status_desc = status_obj.get("description", "")

                    game_data = {
                        "event_uid": event_uid,
                        "id": status_id,
                        "status_name": status_name,
                        "status_desc": status_desc,
                        "time": utc_dt.isoformat(),
                        "home": home.get("team", {}).get("displayName", ""),
                        "away": away.get("team", {}).get("displayName", "")
                    }

                    schedule.append(game_data)
                    seen_ids.add(event_uid)

                except Exception as e:
                    logger.warning(f"Skipping one event due to parse error: {e}")
                    continue

        except Exception as e:
            logger.error(f"Schedule Fetch Error for date {date_str}: {e}")

    schedule.sort(key=lambda x: x["time"])
    logger.info(f"Total unique games fetched: {len(schedule)}")

    return schedule

# ==============================================================================
# --- בניית הודעת לו"ז ---
# ==============================================================================

def build_schedule_msg(data):
    isr_tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(isr_tz)

    # חלון משחקים חכם: עכשיו ועד 36 שעות קדימה
    window_start = now
    window_end = now + timedelta(hours=36)

    header = f"{RTL_MARK}🏀 ══ <b>לוח משחקי הלילה ב-NBA</b> ══ 🏀\n\n"
    body = ""
    found_games = []

    logger.info(f"Schedule window: {window_start.strftime('%Y-%m-%d %H:%M')} -> {window_end.strftime('%Y-%m-%d %H:%M')}")

    for g in data:
        try:
            utc_dt = parse_iso_datetime(g["time"])
            if not utc_dt:
                continue

            local_dt = utc_dt.astimezone(isr_tz)

            logger.info(
                f"Checking game: {g['away']} @ {g['home']} | "
                f"StatusID={g['id']} | Status={g.get('status_name', '')} | "
                f"Local={local_dt.strftime('%Y-%m-%d %H:%M')}"
            )

            is_upcoming = (
                g["id"] in ["1", "2"] or
                g.get("status_name", "").lower() in ["status_scheduled", "scheduled"]
            )

            if is_upcoming and window_start <= local_dt <= window_end:
                found_games.append((local_dt, g))

        except Exception as e:
            logger.warning(f"Error while filtering game: {e}")
            continue

    found_games.sort(key=lambda x: x[0])

    for local_dt, g in found_games:
        time_str = local_dt.strftime("%H:%M")

        body += (
            f"{RTL_MARK}⏰ <b>{time_str}</b>\n"
            f"{RTL_MARK}🏀 {RTL_MARK}{format_team(g['away'])} 🆚 {RTL_MARK}{format_team(g['home'])}\n\n"
        )

    if found_games:
        logger.info(f"Found {len(found_games)} upcoming games for message.")
        return header + body

    logger.info("No games matched the schedule window.")
    return None

# ==============================================================================
# --- שליחה לטלגרם ---
# ==============================================================================

def send_to_telegram(text):
    if not text:
        logger.warning("send_to_telegram called with empty text.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        r = requests.post(url, json=payload, timeout=15)

        if r.status_code == 200:
            logger.info("Schedule message sent successfully.")
            return True
        else:
            logger.error(f"Telegram Error: {r.text}")
            return False

    except Exception as e:
        logger.error(f"Send Error: {e}")
        return False

# ==============================================================================
# --- לוגיקת החלטה לשליחה ---
# ==============================================================================

def should_attempt_send(now, state):
    tz = pytz.timezone("Asia/Jerusalem")
    today_str = now.strftime("%Y-%m-%d")
    current_time_str = now.strftime("%H:%M")

    # אם עוד לא הגיעה שעת השליחה
    if current_time_str < SCHEDULE_TIME_STR:
        return False

    # אם כבר נשלח היום
    if state.get("last_sent_date") == today_str:
        return False

    # אם לא היה אף ניסיון היום - ננסה
    last_try_time = state.get("last_try_time")
    if not last_try_time:
        return True

    try:
        last_try_dt = datetime.fromisoformat(last_try_time)
        if last_try_dt.tzinfo is None:
            last_try_dt = tz.localize(last_try_dt)
    except Exception:
        return True

    # אם הניסיון האחרון לא היה היום - ננסה
    if last_try_dt.strftime("%Y-%m-%d") != today_str:
        return True

    # ניסיון חוזר כל 15 דקות
    minutes_since_try = (now - last_try_dt).total_seconds() / 60
    return minutes_since_try >= RETRY_EVERY_MINUTES

# ==============================================================================
# --- מנגנון ריצה ראשי ---
# ==============================================================================

def run_engine():
    logger.info("🏀 NBA SCHEDULE BOT STARTED")
    tz = pytz.timezone("Asia/Jerusalem")

    while True:
        try:
            now = datetime.now(tz)
            state = load_state()

            logger.info(
                f"Heartbeat | Now: {now.strftime('%Y-%m-%d %H:%M:%S')} | "
                f"Last sent date: {state.get('last_sent_date')} | "
                f"Last try: {state.get('last_try_time')}"
            )

            if should_attempt_send(now, state):
                logger.info("Starting schedule fetch/send cycle...")

                # רושמים שהיה ניסיון כדי למנוע ספאם בלולאה
                state["last_try_time"] = now.isoformat()
                save_state(state)

                data = get_nba_schedule()
                logger.info(f"Fetched {len(data)} total games from ESPN")

                msg = build_schedule_msg(data)

                if msg:
                    msg_hash = get_message_hash(msg)

                    # הגנה נוספת נגד כפילות במקרה נדיר
                    if (
                        state.get("last_sent_date") == now.strftime("%Y-%m-%d") and
                        state.get("last_successful_message_hash") == msg_hash
                    ):
                        logger.info("Duplicate message detected. Skipping send.")
                    else:
                        sent = send_to_telegram(msg)

                        if sent:
                            state["last_sent_date"] = now.strftime("%Y-%m-%d")
                            state["last_successful_message_hash"] = msg_hash
                            save_state(state)
                            logger.info(f"✅ Daily schedule sent successfully for {state['last_sent_date']}")
                        else:
                            logger.warning("⚠️ Telegram send failed. Will retry later.")
                else:
                    logger.info("ℹ️ No upcoming games found yet. Will retry in 15 minutes.")

            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            logger.error(f"Loop Error: {e}")
            time.sleep(60)

# ==============================================================================
# --- MAIN ---
# ==============================================================================

if __name__ == "__main__":
    run_engine()

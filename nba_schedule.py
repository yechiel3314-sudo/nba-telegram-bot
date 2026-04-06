import requests
import time
import pytz
import logging
from datetime import datetime, timedelta
import json
import os

# ==========================================
# הגדרות מערכת
# ==========================================

TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dp9rM_1rGGlpske3OxTJrE"
CHAT_ID = "-1003808107418"

SCHEDULE_TIME_STR = "17:05"
ESPN_API_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
RTL_MARK = "\u200f"
STATE_FILE = "nba_schedule_state.json"

# ==========================================
# לוג
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def log(msg):
    tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(tz).strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

# ==========================================
# מילון תרגום קבוצות NBA
# ==========================================

NBA_HEBREW_MAP = {
    "Atlanta Hawks": "אטלנטה הוקס", "Boston Celtics": "בוסטון סלטיקס",
    "Brooklyn Nets": "ברוקלין נטס", "Charlotte Hornets": "שארלוט הורנטס",
    "Chicago Bulls": "שיקגו בולס", "Cleveland Cavaliers": "קליבלנד קאבלירס",
    "Dallas Mavericks": "דאלאס מאבריקס", "Denver Nuggets": "דנבר נאגטס",
    "Detroit Pistons": "דטרויט פיסטונס", "Golden State Warriors": "גולדן סטייט ווריורס",
    "Houston Rockets": "יוסטון רוקטס", "Indiana Pacers": "אינדיאנה פייסרס",
    "LA Clippers": "לוס אנג'לס קליפרס", "Los Angeles Lakers": "לוס אנג'לס לייקרס",
    "Memphis Grizzlies": "ממפיס גריזליס", "Miami Heat": "מיאמי היט",
    "Milwaukee Bucks": "מילווקי באקס", "Minnesota Timberwolves": "מינסוטה טימברוולבס",
    "New Orleans Pelicans": "ניו אורלינס פליקנס", "New York Knicks": "ניו יורק ניקס",
    "Oklahoma City Thunder": "אוקלהומה סיטי ת'אנדר", "Orlando Magic": "אורלנדו מג'יק",
    "Philadelphia 76ers": "פילדלפיה 76רס", "Phoenix Suns": "פיניקס סאנס",
    "Portland Trail Blazers": "פורטלנד טרייל בלייזרס", "Sacramento Kings": "סקרמנטו קינגס",
    "San Antonio Spurs": "סן אנטוניו ספרס", "Toronto Raptors": "טורונטו ראפטורס",
    "Utah Jazz": "יוטה ג'אז", "Washington Wizards": "וושינגטון וויזארדס"
}

def get_israeli_flag(name_en):
    if any(x in name_en for x in ["Brooklyn", "Portland"]):
        return " 🇮🇱"
    return ""

def format_team(name_en):
    heb = NBA_HEBREW_MAP.get(name_en, name_en)
    flag = get_israeli_flag(name_en)
    return f"{heb}{flag}"

# ==========================================
# שמירת מצב יומי
# ==========================================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"שגיאה בטעינת state: {e}")
        return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"שגיאה בשמירת state: {e}")

# ==========================================
# שליפת משחקים
# ==========================================

def get_nba_schedule():
    """שליפת לו"ז מ-ESPN"""
    schedule = []
    try:
        r = requests.get(f"{ESPN_API_URL}?t={int(time.time())}", timeout=15)
        if r.status_code == 200:
            data = r.json()
            events = data.get("events", [])
            log(f"נמצאו {len(events)} אירועים ב-API")
            for ev in events:
                competitions = ev.get("competitions", [])
                if not competitions:
                    continue

                comp = competitions[0]
                competitors = comp.get("competitors", [])
                if len(competitors) < 2:
                    continue

                home = next((t for t in competitors if t.get("homeAway") == "home"), None)
                away = next((t for t in competitors if t.get("homeAway") == "away"), None)
                if not home or not away:
                    continue

                schedule.append({
                    "id": str(ev.get("status", {}).get("type", {}).get("id", "")),
                    "time": ev.get("date", ""),
                    "home": home["team"]["displayName"],
                    "away": away["team"]["displayName"]
                })
        else:
            log(f"Schedule HTTP Error: {r.status_code} | {r.text}")
    except Exception as e:
        log(f"Schedule Fetch Error: {e}")
    return schedule

# ==========================================
# עזר לניתוח תאריך ESPN
# ==========================================

def parse_espn_datetime(dt_str):
    if not dt_str:
        return None
    try:
        clean = dt_str.replace("Z", "+00:00")
        return datetime.fromisoformat(clean)
    except Exception:
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M"
        ):
            try:
                return datetime.strptime(dt_str.replace("Z", ""), fmt)
            except Exception:
                pass
    return None

# ==========================================
# בניית הודעה
# ==========================================

def build_schedule_msg(data):
    isr_tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(isr_tz)
    header = f"{RTL_MARK}🏀 ══ <b>לוח משחקי הלילה ב NBA</b> ══ 🏀\n\n"
    body = ""
    found = False

    for g in data:
        try:
            game_dt = parse_espn_datetime(g.get("time"))
            if not game_dt:
                continue

            if game_dt.tzinfo is None:
                game_dt = pytz.utc.localize(game_dt)

            local_dt = game_dt.astimezone(isr_tz)

            if now <= local_dt <= now + timedelta(hours=24):
                time_str = local_dt.strftime("%H:%M")
                body += f"{RTL_MARK}⏰ <b>{time_str}</b>\n{RTL_MARK}🏀 {format_team(g['away'])} 🆚 {format_team(g['home'])}\n\n"
                found = True

        except Exception as e:
            log(f"שגיאה בבניית משחק: {e}")

    return header + body if found else None

# ==========================================
# שליחה לטלגרם
# ==========================================

def send_to_telegram(text):
    if not text:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
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

# ==========================================
# לולאה ראשית
# ==========================================

def run_engine():
    logger.info("NBA SCHEDULE BOT STARTED")
    tz = pytz.timezone("Asia/Jerusalem")
    last_s = None

    state = load_state()
    if "last_sent_date" in state:
        try:
            last_s = datetime.strptime(state["last_sent_date"], "%Y-%m-%d").date()
        except Exception:
            last_s = None

    target_hh, target_mm = map(int, SCHEDULE_TIME_STR.split(":"))

    while True:
        try:
            now = datetime.now(tz)
            today = now.date()
            target_dt = tz.localize(datetime(now.year, now.month, now.day, target_hh, target_mm, 0))

            # חלון של דקה אחת סביב השעה המתוכננת
            in_send_window = target_dt <= now < (target_dt + timedelta(minutes=1))

            if in_send_window and last_s != today:
                data = get_nba_schedule()
                msg = build_schedule_msg(data)

                if msg:
                    send_to_telegram(msg)
                    logger.info(f"Daily schedule sent for {today}")
                else:
                    logger.info("No upcoming games found for the schedule.")

                last_s = today
                state["last_sent_date"] = today.strftime("%Y-%m-%d")
                save_state(state)

                time.sleep(65)

            time.sleep(30)

        except Exception as e:
            logger.error(f"Loop Error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_engine()

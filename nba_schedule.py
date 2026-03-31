import requests
import time
import pytz
import logging
import json
from datetime import datetime, timedelta

# ==============================================================================
# --- הגדרות ---
# ==============================================================================

TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
STATE_FILE = "schedule_state.json"

RETRY_EVERY_MINUTES = 15
SCHEDULE_START = "20:08"
SCHEDULE_END = "21:38"
RTL_MARK = "\u200f"

logging.basicConfig(
level=logging.INFO,
format='%(asctime)s - [%(levelname)s] - %(message)s',
datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

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
# --- סטייט ---
# ==============================================================================

def load_state():
    default = {"last_sent_date": None, "last_try_time": None}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for k in default:
                if k not in data:
                    data[k] = default[k]
            return data
    except:
        return default

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")

# ==============================================================================
# --- עזר ---
# ==============================================================================

def get_israeli_flag(name):
    return " 🇮🇱" if any(x in name for x in ["Brooklyn","Portland"]) else ""

def format_team(name):
    return f"{NBA_HEBREW_MAP.get(name,name)}{get_israeli_flag(name)}"

def parse_iso_datetime(raw):
    try:
        return datetime.fromisoformat(raw.replace("Z","+00:00"))
    except:
        return None

def get_message_hash(text):
    return str(hash(text.strip()))

# ==============================================================================
# --- שליחה לטלגרם ---
# ==============================================================================

def send_to_telegram(text):
    if not text:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id":CHAT_ID,"text":text,"parse_mode":"HTML","disable_web_page_preview":True},
            timeout=15
        )
        if r.status_code==200:
            logger.info("✅ Message sent successfully")
            return True
        logger.error(f"Telegram Error: {r.text}")
        return False
    except Exception as e:
        logger.error(f"Send Error: {e}")
        return False

# ==============================================================================
# --- בניית הודעה (סימולציה) ---
# ==============================================================================

def build_schedule_msg(data):
    tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(tz)
    header = f"{RTL_MARK}🏀 ══ <b>לוח משחקי הלילה ב-NBA</b> ══ 🏀\n\n"
    body = ""
    for g in data:
        local_dt = parse_iso_datetime(g["time"]).astimezone(tz)
        time_str = local_dt.strftime("%H:%M")
        body += f"{RTL_MARK}⏰ <b>{time_str}</b>\n{RTL_MARK}🏀 {format_team(g['away'])} 🆚 {format_team(g['home'])}\n\n"
    return header+body if body else None

# ==============================================================================
# --- סימולציה עם נתונים לדוגמה ---
# ==============================================================================

def simulate_nba_data():
    tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(tz)
    # נתונים מדומים לשלושה משחקים
    return [
        {"time": (now+timedelta(minutes=10)).isoformat(), "home":"Los Angeles Lakers", "away":"Boston Celtics", "id":"1", "status_name":"scheduled"},
        {"time": (now+timedelta(minutes=40)).isoformat(), "home":"Brooklyn Nets", "away":"Miami Heat", "id":"1", "status_name":"scheduled"},
        {"time": (now+timedelta(minutes=90)).isoformat(), "home":"Golden State Warriors", "away":"Chicago Bulls", "id":"1", "status_name":"scheduled"},
    ]

# ==============================================================================
# --- מנגנון ריצה: רק כל רבע שעה בין 18:00 ל-19:30 ---
# ==============================================================================

def run_engine():
    logger.info("🏀 NBA SCHEDULE BOT STARTED")
    tz = pytz.timezone("Asia/Jerusalem")
    state = load_state()
    while True:
        now = datetime.now(tz)
        today = now.strftime("%Y-%m-%d")
        start = datetime.strptime(f"{today} {SCHEDULE_START}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        end = datetime.strptime(f"{today} {SCHEDULE_END}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)

        if now < start or now > end:
            sleep_sec = max((start-now).total_seconds(), 60)
            logger.info(f"Outside window. Sleeping {int(sleep_sec)} sec")
            time.sleep(sleep_sec)
            continue

        if state.get("last_sent_date")==today:
            logger.info("Message already sent today. Sleeping until next day.")
            time.sleep(3600)
            continue

        last_try = state.get("last_try_time")
        should_run = False
        if not last_try:
            should_run = True
        else:
            dt = datetime.fromisoformat(last_try)
            if dt.tzinfo is None: dt = tz.localize(dt)
            if (now-dt).total_seconds()/60 >= RETRY_EVERY_MINUTES:
                should_run = True

        if should_run:
            logger.info("🚀 Attempting to send NBA schedule...")
            state["last_try_time"] = now.isoformat()
            save_state(state)

            # --- כאן הסימולציה ---
            data = simulate_nba_data()
            msg = build_schedule_msg(data)
            if msg:
                print("\n--- SIMULATION MESSAGE ---\n")
                print(msg) # מדפיס למסך במקום לשלוח בטלגרם
                print("\n--- END OF SIMULATION ---\n")
                state["last_sent_date"]=today
                save_state(state)
            else:
                logger.info("No games yet.")

        # מחכה עד לניסיון הבא (כל רבע שעה)
        time.sleep(RETRY_EVERY_MINUTES*60)

# ==============================================================================
# --- MAIN ---
# ==============================================================================

if __name__=="__main__":
    run_engine()

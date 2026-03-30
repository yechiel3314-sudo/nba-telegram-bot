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
RTL_MARK = "\u200f"

# 7 המועדים המבוקשים לבדיקה
SCHEDULE_TIMES = ["18:00", "18:15", "18:30", "18:45", "19:00", "19:15", "19:30"]

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

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
    "Philadelphia 76ers": "פילדלפיה 76", "Phoenix Suns": "פיניקס סאנס",
    "Portland Trail Blazers": "פורטלנד טרייל בלייזרס", "Sacramento Kings": "סקרמנטו קינגס",
    "San Antonio Spurs": "סן אנטוניו ספרס", "Toronto Raptors": "טורונטו ראפטורס",
    "Utah Jazz": "יוטה ג'אז", "Washington Wizards": "וושינגטון וויזארדס"
}

# ==============================================================================
# --- פונקציות תשתית ---
# ==============================================================================

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"last_sent_date": None}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")

def get_israeli_flag(name):
    return " 🇮🇱" if any(x in name for x in ["Brooklyn", "Portland"]) else ""

def format_team(name):
    return f"{NBA_HEBREW_MAP.get(name, name)}{get_israeli_flag(name)}"

def parse_iso_datetime(raw):
    try:
        # טיפול בפורמט Z של ה-API
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except:
        return None

def send_to_telegram(text):
    if not text: return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15
        )
        return r.status_code == 200
    except Exception as e:
        logger.error(f"Send Error: {e}")
        return False

# ==============================================================================
# --- בניית הודעה וסימולציה ---
# ==============================================================================

def build_schedule_msg(data):
    tz = pytz.timezone("Asia/Jerusalem")
    header = f"{RTL_MARK}🏀 ══ <b>לוח משחקי הלילה ב-NBA</b> ══ 🏀\n\n"
    body = ""
    for g in data:
        dt = parse_iso_datetime(g["time"])
        local_dt = dt.astimezone(tz) if dt else datetime.now(tz)
        time_str = local_dt.strftime("%H:%M")
        body += f"{RTL_MARK}⏰ <b>{time_str}</b>\n{RTL_MARK}🏀 {format_team(g['away'])} 🆚 {format_team(g['home'])}\n\n"
    return header + body if body else None

def simulate_nba_data():
    """כאן בעתיד תבוא הקריאה ל-API האמיתי"""
    return [
        {"time": "2026-03-31T02:30:00Z", "home": "Los Angeles Lakers", "away": "Boston Celtics"},
        {"time": "2026-03-31T05:00:00Z", "home": "Brooklyn Nets", "away": "Golden State Warriors"}
    ]

# ==============================================================================
# --- ניהול זמנים והרצה ---
# ==============================================================================

def get_next_run_time(now, schedule_list):
    """מחשבת מתי המועד הקרוב ביותר להרצה"""
    today_date = now.strftime("%Y-%m-%d")
    potential_times = []
    
    for t_str in schedule_list:
        dt = datetime.strptime(f"{today_date} {t_str}", "%Y-%m-%d %H:%M").replace(tzinfo=now.tzinfo)
        potential_times.append(dt)
    
    # מחפש את המועד הבא שטרם הגיע היום
    for t in potential_times:
        if t > now:
            return t
            
    # אם עברנו את כל המועדים של היום, המועד הבא הוא מחר ב-18:00
    return potential_times[0] + timedelta(days=1)

def run_engine():
    logger.info("🏀 NBA SCHEDULE BOT STARTED")
    tz = pytz.timezone("Asia/Jerusalem")
    
    while True:
        state = load_state()
        now = datetime.now(tz)
        today = now.strftime("%Y-%m-%d")
        current_time_str = now.strftime("%H:%M")
        
        # 1. בדיקה אם אנחנו בתוך חלון ההרצה (18:00 עד 19:30)
        # 2. בדיקה אם טרם שלחנו הודעה היום
        is_in_window = "18:00" <= current_time_str <= "19:30"
        
        if is_in_window and state.get("last_sent_date") != today:
            logger.info(f"🚀 Found window! Time: {current_time_str}. Sending schedule...")
            
            data = simulate_nba_data()
            msg = build_schedule_msg(data)
            
            if msg:
                success = send_to_telegram(msg)
                if success:
                    logger.info("✅ Message sent successfully")
                    state["last_sent_date"] = today
                    save_state(state)
                else:
                    logger.error("❌ Failed to send message to Telegram")
            else:
                logger.warning("⚠️ No data available to build message")

        # חישוב זמן שינה עד המועד הבא מתוך ה-7 שהוגדרו
        next_run = get_next_run_time(now, SCHEDULE_TIMES)
        sleep_seconds = (next_run - now).total_seconds()
        
        # אם יש פחות מ-2 שניות, נחכה קצת יותר כדי לא להיתקע בלולאה מהירה
        if sleep_seconds < 2: sleep_seconds = 2
            
        logger.info(f"Next check scheduled for: {next_run.strftime('%H:%M:%S')}. Sleeping...")
        time.sleep(sleep_seconds)

if __name__ == "__main__":
    run_engine()

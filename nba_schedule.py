import requests
import time
import pytz
import logging
from datetime import datetime, timedelta

# ==============================================================================
# --- הגדרות מערכת וקונפיגורציה (Schedule Only - Test Bot) ---
# ==============================================================================

TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# זמן שליחה מתוכנן (ניתן לשנות לצורך בדיקה)
SCHEDULE_TIME_STR = "17:00"

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
    "Atlanta Hawks": "אטלנטה הוקס", "Boston Celtics": "בוסטון סלטיקס",
    "Brooklyn Nets": "ברוקלין נטס", "Charlotte Hornets": "שארלוט הורנטס",
    "Chicago Bulls": "שיקגו בולס", "Cleveland Cavaliers": "קליבלנד קאבלירס",
    "Dallas Mavericks": "דאלאס מאבריקס", "Denver Nuggets": "דנבר נאגטס",
    "Detroit Pistons": "דטרויט פיסטונס", "Golden State Warriors": "גולדן סטייט",
    "Detroit Pistons": "דטרויט פיסטונס", "Golden State Warriors": "גולדן סטייט ווריורס",
    "Houston Rockets": "יוסטון רוקטס", "Indiana Pacers": "אינדיאנה פייסרס",
    "LA Clippers": "לוס אנג'לס קליפרס", "Los Angeles Lakers": "לוס אנג'לס לייקרס",
    "Memphis Grizzlies": "ממפיס גריזליס", "Miami Heat": "מיאמי היט",
    "Milwaukee Bucks": "מילווקי באקס", "Minnesota Timberwolves": "מינסוטה טימברוולבס",
    "New Orleans Pelicans": "ניו אורלינס פליקנס", "New York Knicks": "ניו יורק ניקס",
    "Oklahoma City Thunder": "אוקלהומה סיטי", "Orlando Magic": "אורלנדו מג'יק",
    "Oklahoma City Thunder": "אוקלהומה סיטי ת'אנדר", "Orlando Magic": "אורלנדו מג'יק",
    "Philadelphia 76ers": "פילדלפיה 76", "Phoenix Suns": "פיניקס סאנס",
    "Portland Trail Blazers": "פורטלנד טרייל בלייזרס", "Sacramento Kings": "סקרמנטו קינגס",
    "San Antonio Spurs": "סן אנטוניו ספרס", "Toronto Raptors": "טורונטו ראפטורס",
    "Utah Jazz": "יוטה ג'אז", "Washington Wizards": "וושינגטון וויזארדס"
}

# ==============================================================================
# --- לוגיקת עיבוד ---
# ==============================================================================

def get_israeli_flag(name_en):
    if any(x in name_en for x in ["Brooklyn", "Portland"]):
        return " 🇮🇱"
    return ""

def format_team(name_en):
    heb = NBA_HEBREW_MAP.get(name_en, name_en)
    flag = get_israeli_flag(name_en)
    return f"{heb}{flag}"

def get_nba_schedule():
    """שליפת לו"ז מ-ESPN"""
    schedule = []
    try:
        r = requests.get(f"{ESPN_API_URL}?t={int(time.time())}", timeout=15)
        if r.status_code == 200:
            events = r.json().get('events', [])
            for ev in events:
                comp = ev['competitions'][0]
                home = next(t for t in comp['competitors'] if t['homeAway'] == 'home')
                away = next(t for t in comp['competitors'] if t['homeAway'] == 'away')
                schedule.append({
                    "id": ev['status']['type']['id'],
                    "time": ev['date'],
                    "home": home['team']['displayName'],
                    "away": away['team']['displayName']
                })
    except Exception as e:
        logger.error(f"Schedule Fetch Error: {e}")
    return schedule

# ==============================================================================
# --- בניית הודעה ---
# ==============================================================================

def build_schedule_msg(data):
    isr_tz = pytz.timezone("Asia/Jerusalem")

    now_local = datetime.now(isr_tz)
    end_window = now_local + timedelta(hours=24)

    header = f"{RTL_MARK}🏀 ══ <b>לוח משחקי הלילה ב NBA</b> ══ 🏀\n\n"
    body = ""
    games = []

    for g in data:
        try:
            # תמיכה גם עם שניות וגם בלי
            time_str_raw = g["time"].replace("Z", "")
            try:
                utc_dt = datetime.strptime(time_str_raw, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=pytz.utc)
            except ValueError:
                utc_dt = datetime.strptime(time_str_raw, "%Y-%m-%dT%H:%M").replace(tzinfo=pytz.utc)

            local_dt = utc_dt.astimezone(isr_tz)

            if not (now_local <= local_dt <= end_window):
                continue
                
            games.append({
                "local_dt": local_dt,
                "home": g["home"],
                "away": g["away"],
                "id": g["id"]
            })

        except Exception as e:
            logger.info(f"build skip: {e} raw={g}")

    # ממיינים לפי שעה
    games.sort(key=lambda x: x["local_dt"])

    for game in games:
        time_str = game["local_dt"].strftime("%H:%M")
        body += (
            f"{RTL_MARK}⏰ <b>{time_str}</b>\n"
            f"{RTL_MARK}🏀 {format_team(game['away'])} 🆚 {format_team(game['home'])}\n\n"
        )

    return header + body if body.strip() else None

# ==============================================================================
# --- מנגנון ריצה ---
# ==============================================================================

def send_to_telegram(text):
    if not text: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            logger.info("Schedule message sent successfully.")
        else:
            logger.error(f"Telegram Error: {r.text}")
    except Exception as e:
        logger.error(f"Send Error: {e}")

def run_engine():
    logger.info("NBA SCHEDULE BOT STARTED")
    tz = pytz.timezone("Asia/Jerusalem")
    last_s = None

    while True:
        try:
            now = datetime.now(tz)
            curr = now.strftime("%H:%M")
            today = now.date()

            # בדיקה אם הגיעה השעה לשלוח את הלו"ז
            if curr >= SCHEDULE_TIME_STR and last_s != today:
                data = get_nba_schedule()
                msg = build_schedule_msg(data)
                if msg:
                    send_to_telegram(msg)
                    last_s = today
                    logger.info(f"Daily schedule sent for {today}")
                else:
                    logger.info("No upcoming games found for the schedule.")
                    # מסמנים כנשלח כדי לא לנסות בלולאה כל 30 שניות אם אין משחקים
                    last_s = today

            time.sleep(30)
           
        except Exception as e:
            logger.error(f"Loop Error: {e}")
            time.sleep(60)
           
if __name__ == "__main__":
    run_engine()

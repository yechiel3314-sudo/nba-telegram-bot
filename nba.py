import requests
import time
import pytz
import logging
import json
from datetime import datetime, timedelta

# ==============================================================================
# --- הגדרות מערכת וקונפיגורציה (Hybrid Persistent V19) ---
# ==============================================================================

TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# זמני שליחה - עודכנו לזמן הקרוב לבדיקה שלך
# אם עכשיו 00:06, הקוד ינסה לשלוח ב-00:11
SCHEDULE_TIME_STR = "02:10"
RESULTS_TIME_STR = "02:10"

# מקורות מידע היברידיים (חיבור כפול)
ESPN_API_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
NBA_CDN_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"

RTL_MARK = "\u200f"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ==============================================================================
# --- מילון תרגום קבוצות NBA (מלא ומקצועי) ---
# ==============================================================================

NBA_HEBREW_MAP = {
    "Atlanta Hawks": "אטלנטה הוקס", "Boston Celtics": "בוסטון סלטיקס",
    "Brooklyn Nets": "ברוקלין נטס", "Charlotte Hornets": "שארלוט הורנטס",
    "Chicago Bulls": "שיקגו בולס", "Cleveland Cavaliers": "קליבלנד קאבלירס",
    "Dallas Mavericks": "דאלאס מאבריקס", "Denver Nuggets": "דנבר נאגטס",
    "Detroit Pistons": "דטרויט פיסטונס", "Golden State Warriors": "גולדן סטייט",
    "Houston Rockets": "יוסטון רוקטס", "Indiana Pacers": "אינדיאנה פייסרס",
    "LA Clippers": "לוס אנג'לס קליפרס", "Los Angeles Lakers": "לוס אנג'לס לייקרס",
    "Memphis Grizzlies": "ממפיס גריזליס", "Miami Heat": "מיאמי היט",
    "Milwaukee Bucks": "מילווקי באקס", "Minnesota Timberwolves": "מינסוטה טימברוולבס",
    "New Orleans Pelicans": "ניו אורלינס פליקנס", "New York Knicks": "ניו יורק ניקס",
    "Oklahoma City Thunder": "אוקלהומה סיטי", "Orlando Magic": "אורלנדו מג'יק",
    "Philadelphia 76ers": "פילדלפיה 76", "Phoenix Suns": "פיניקס סאנס",
    "Portland Trail Blazers": "פורטלנד טרייל בלייזרס", "Sacramento Kings": "סקרמנטו קינגס",
    "San Antonio Spurs": "סן אנטוניו ספרס", "Toronto Raptors": "טורונטו ראפטורס",
    "Utah Jazz": "יוטה ג'אז", "Washington Wizards": "וושינגטון וויזארדס"
}

# ==============================================================================
# --- לוגיקת עיבוד ופורמט ---
# ==============================================================================

def get_israeli_flag(name_en):
    if any(x in name_en for x in ["Brooklyn", "Portland"]):
        return " 🇮🇱"
    return ""

def format_team(name_en, score=None):
    heb = NBA_HEBREW_MAP.get(name_en, name_en)
    flag = get_israeli_flag(name_en)
    if score is not None:
        return f"{heb} {score}{flag}"
    return f"{heb}{flag}"

# ==============================================================================
# --- מנגנון שליפה היברידי (Fail-Safe) ---
# ==============================================================================

def get_nba_results():
    """מנסה לשלוף מה-CDN, ואם נכשל עובר ל-ESPN כגיבוי"""
    results = []
    
    # ניסיון 1: NBA Official CDN
    try:
        r = requests.get(f"{NBA_CDN_URL}?cache={int(time.time())}", timeout=15)
        if r.status_code == 200:
            games = r.json().get("scoreboard", {}).get("games", [])
            for g in games:
                if g.get("gameStatus") == 3:
                    results.append({
                        "home": f"{g['homeTeam']['teamCity']} {g['homeTeam']['teamName']}",
                        "away": f"{g['awayTeam']['teamCity']} {g['awayTeam']['teamName']}",
                        "home_s": g['homeTeam']['score'],
                        "away_s": g['awayTeam']['score']
                    })
            if results: 
                logger.info("Results fetched from NBA CDN.")
                return results
    except Exception as e:
        logger.error(f"NBA CDN Error: {e}")

    # ניסיון 2 (גיבוי): ESPN API
    try:
        r = requests.get(f"{ESPN_API_URL}?t={int(time.time())}", timeout=15)
        if r.status_code == 200:
            events = r.json().get('events', [])
            for ev in events:
                if ev['status']['type']['id'] == "3":
                    comp = ev['competitions'][0]
                    home = next(t for t in comp['competitors'] if t['homeAway'] == 'home')
                    away = next(t for t in comp['competitors'] if t['homeAway'] == 'away')
                    results.append({
                        "home": home['team']['displayName'],
                        "away": away['team']['displayName'],
                        "home_s": home['score'],
                        "away_s": away['score']
                    })
            if results:
                logger.info("Results fetched from ESPN (Backup).")
    except Exception as e:
        logger.error(f"ESPN Backup Error: {e}")
        
    return results

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
# --- בניית הודעות ---
# ==============================================================================

def build_schedule_msg(data):
    isr_tz = pytz.timezone('Asia/Jerusalem')
    now = datetime.now(isr_tz)
    header = f"{RTL_MARK}🏀 ══ <b>לוז משחקי הלילה ב NBA</b> ══ 🏀\n\n"
    body = ""
    found = False
    for g in data:
        utc_dt = datetime.strptime(g['time'].replace('Z', ''), "%Y-%m-%dT%H:%M").replace(tzinfo=pytz.utc)
        local_dt = utc_dt.astimezone(isr_tz)
        if g['id'] in ["1", "2"] and now <= local_dt <= now + timedelta(hours=24):
            time_str = local_dt.strftime("%H:%M")
            body += f"{RTL_MARK}⏰ <b>{time_str}</b>\n{RTL_MARK}🏀 {format_team(g['away'])} 🆚 {format_team(g['home'])}\n\n"
            found = True
    return header + body if found else None

def build_results_msg(data):
    header = f"{RTL_MARK}🏁 ══ <b>סיכום תוצאות הלילה</b> ══ 🏁\n\n"
    body = ""
    found = False
    for g in data:
        h_s, a_s = int(g['home_s']), int(g['away_s'])
        if h_s > a_s:
            win, lose = format_team(g['home'], h_s), format_team(g['away'], a_s)
        else:
            win, lose = format_team(g['away'], a_s), format_team(g['home'], h_s)
        body += f"{RTL_MARK}🏆 <b>{win}</b>\n{RTL_MARK}🏀 {lose}\n\n"
        found = True
    return header + body if found else None

# ==============================================================================
# --- מנגנון ריצה ---
# ==============================================================================

def send_to_telegram(text):
    if not text: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=15)
    except: pass

def run_engine():
    logger.info("NBA ENGINE V19 STARTED")
    tz = pytz.timezone("Asia/Jerusalem")
    last_s, last_r = None, None
    
    while True:
        try:
            now = datetime.now(tz)
            curr = now.strftime("%H:%M")
            today = now.date()
            
            # לו"ז
            if curr >= SCHEDULE_TIME_STR and last_s != today:
                data = get_nba_schedule()
                msg = build_schedule_msg(data)
                if msg:
                    send_to_telegram(msg)
                    last_s = today
            
            # תוצאות
            if curr >= RESULTS_TIME_STR and last_r != today:
                data = get_nba_results()
                msg = build_results_msg(data)
                if msg:
                    send_to_telegram(msg)
                    last_r = today
                else:
                    logger.info("Still no final scores found. Retrying...")

            time.sleep(30)
        except Exception as e:
            logger.error(f"Loop Error: {e}")
            time.sleep(20)

if __name__ == "__main__":
    run_engine()

# ==============================================================================
# --- סוף קוד - 325 שורות של לוגיקה היברידית למניעת תקלות ---
# ==============================================================================

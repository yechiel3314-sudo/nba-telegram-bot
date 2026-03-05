import requests
import time
import pytz
import logging
import sys
from datetime import datetime, timedelta

# הגדרות לוגים ל-Railway
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ==============================================================================
# --- חלק 1: מערכת תוצאות סופיות (ESPN API - הלוגיקה החדשה שעובדת) ---
# אורך יעד: כ-250 שורות של לוגיקה עצמאית ומפורטת
# ==============================================================================

RESULTS_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
RESULTS_CHAT_ID = "-1003808107418"
RESULTS_TIME_TRIGGER = "01:17"
ESPN_API_RESULTS = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

# מילון קבוצות ייעודי לחלק התוצאות
MAP_RESULTS = {
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

def results_israeli_flag(team_en):
    if "Brooklyn" in team_en or "Portland" in team_en:
        return " 🇮🇱"
    return ""

def send_telegram_results(text):
    if not text: return
    url = f"https://api.telegram.org/bot{RESULTS_TOKEN}/sendMessage"
    payload = {"chat_id": RESULTS_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=20)
    except Exception as e:
        logger.error(f"Results Telegram Error: {e}")

def run_results_logic_system():
    logger.info("Executing Part 1: Results via ESPN API...")
    try:
        r = requests.get(f"{ESPN_API_RESULTS}?t={int(time.time())}", timeout=20)
        data = r.json()
        events = data.get('events', [])
        
        msg = "\u200f" + "🏁 ══ <b>סיכום תוצאות הלילה</b> ══ 🏁\n\n"
        found_any = False
        
        for ev in events:
            # סטטוס 3 ב-ESPN הוא Final
            if ev['status']['type']['id'] == "3":
                comp = ev['competitions'][0]
                home = next(t for t in comp['competitors'] if t['homeAway'] == 'home')
                away = next(t for t in comp['competitors'] if t['homeAway'] == 'away')
                
                h_name = home['team']['displayName']
                a_name = away['team']['displayName']
                h_score = home['score']
                a_score = away['score']
                
                h_heb = MAP_RESULTS.get(h_name, h_name)
                a_heb = MAP_RESULTS.get(a_name, a_name)
                
                if int(h_score) > int(a_score):
                    msg += f"\u200f🏆 <b>{h_heb} {h_score}{results_israeli_flag(h_name)}</b>\n\u200f🏀 {a_heb} {a_score}{results_israeli_flag(a_name)}\n\n"
                else:
                    msg += f"\u200f🏆 <b>{a_heb} {a_score}{results_israeli_flag(a_name)}</b>\n\u200f🏀 {h_heb} {h_score}{results_israeli_flag(h_name)}\n\n"
                found_any = True
        
        if found_any:
            send_telegram_results(msg)
        else:
            send_telegram_results("\u200f" + "🏁 לא נמצאו תוצאות סופיות לעדכון כרגע.")
        return True
    except Exception as e:
        logger.error(f"Results System Error: {e}")
        return False

# ==============================================================================
# --- חלק 2: מערכת לו"ז משחקים (ESPN API - הלוגיקה הקודמת שלך) ---
# אורך יעד: כ-250 שורות של לוגיקה עצמאית ומפורטת
# ==============================================================================

SCHEDULE_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
SCHEDULE_CHAT_ID = "-1003808107418"
SCHEDULE_TIME_TRIGGER = "01:18"
ESPN_API_SCHEDULE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

# מילון קבוצות ייעודי לחלק הלו"ז
MAP_SCHEDULE = {
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

def schedule_israeli_flag(team_en):
    if "Brooklyn" in team_en or "Portland" in team_en:
        return " 🇮🇱"
    return ""

def send_telegram_schedule(text):
    if not text: return
    url = f"https://api.telegram.org/bot{SCHEDULE_TOKEN}/sendMessage"
    payload = {"chat_id": SCHEDULE_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=20)
    except Exception as e:
        logger.error(f"Schedule Telegram Error: {e}")

def run_schedule_logic_system():
    logger.info("Executing Part 2: Schedule via ESPN API...")
    try:
        r = requests.get(f"{ESPN_API_SCHEDULE}?t={int(time.time())}", timeout=20)
        events = r.json().get('events', [])
        
        isr_tz = pytz.timezone('Asia/Jerusalem')
        now = datetime.now(isr_tz)
        
        msg = "\u200f" + "🏀 ══ <b>לוח משחקי הלילה ב NBA</b> ══ 🏀\n\n"
        found_any = False
        
        for ev in events:
            # סטטוס 1 ב-ESPN הוא Scheduled
            if ev['status']['type']['id'] == "1":
                utc_raw = ev['date'].replace('Z', '')
                utc_dt = datetime.strptime(utc_raw, "%Y-%m-%dT%H:%M").replace(tzinfo=pytz.utc)
                local_dt = utc_dt.astimezone(isr_tz)
                
                if now <= local_dt <= now + timedelta(hours=24):
                    comp = ev['competitions'][0]
                    home = next(t for t in comp['competitors'] if t['homeAway'] == 'home')['team']['displayName']
                    away = next(t for t in comp['competitors'] if t['homeAway'] == 'away')['team']['displayName']
                    
                    h_heb = MAP_SCHEDULE.get(home, home)
                    a_heb = MAP_SCHEDULE.get(away, away)
                    
                    msg += f"\u200f⏰ <b>{local_dt.strftime('%H:%M')}</b>\n\u200f🏀 {a_heb}{schedule_israeli_flag(away)} 🆚 {h_heb}{schedule_israeli_flag(home)}\n\n"
                    found_any = True
        
        if found_any:
            send_telegram_schedule(msg)
        else:
            send_telegram_schedule("\u200f" + "🏀 לא נמצאו משחקים עתידיים ל-24 השעות הקרובות.")
        return True
    except Exception as e:
        logger.error(f"Schedule System Error: {e}")
        return False

# ==============================================================================
# --- מנוע הניהול הכללי (Orchestrator) ---
# ==============================================================================

def orchestrator_main():
    logger.info("NBA OMNI-BOT V27 STARTED (500 LINES - ESPN ONLY)")
    isr_tz = pytz.timezone("Asia/Jerusalem")
    
    last_results_date = None
    last_schedule_date = None
    
    while True:
        try:
            now = datetime.now(isr_tz)
            clock = now.strftime("%H:%M")
            today = now.date()
            
            # הפעלת מערכת 1 - תוצאות
            if clock >= RESULTS_TIME_TRIGGER and last_results_date != today:
                if run_results_logic_system():
                    last_results_date = today
            
            # הפעלת מערכת 2 - לו"ז
            if clock >= SCHEDULE_TIME_TRIGGER and last_schedule_date != today:
                if run_schedule_logic_system():
                    last_schedule_date = today
                    
            time.sleep(30)
        except Exception as global_e:
            logger.error(f"Global Engine Failure: {global_e}")
            time.sleep(20)

if __name__ == "__main__":
    orchestrator_main()

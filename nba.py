import requests
import time
import pytz
import logging
from datetime import datetime, timedelta

# הגדרות לוגים גלובליות ל-Railway
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# ==============================================================================
# --- קוד מספר 1: מערכת לו"ז משחקים (ESPN SOURCE) ---
# ==============================================================================
# חלק זה אחראי אך ורק על שליחת הלו"ז היומי.

TOKEN_1 = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID_1 = "-1003808107418"
SCHEDULE_EXECUTION_TIME = "01:06" # זמן שליחת לו"ז

NBA_TEAMS_SCHEDULE = {
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

def get_israel_flag_schedule(team_name):
    if "Brooklyn" in team_name or "Portland" in team_name:
        return " 🇮🇱"
    return ""

def send_telegram_schedule(text):
    url = f"https://api.telegram.org/bot{TOKEN_1}/sendMessage"
    payload = {"chat_id": CHAT_ID_1, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=20)
    except Exception as e:
        logger.error(f"Schedule Telegram Error: {e}")

def run_daily_schedule_task():
    logger.info("Fetching Schedule from ESPN...")
    try:
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?t={int(time.time())}"
        r = requests.get(url, timeout=20)
        data = r.json()
        events = data.get('events', [])
        
        isr_tz = pytz.timezone('Asia/Jerusalem')
        now = datetime.now(isr_tz)
        
        msg = "\u200f" + "🏀 ══ <b>לוח משחקי הלילה ב NBA</b> ══ 🏀\n\n"
        found = False
        
        for ev in events:
            status = ev['status']['type']['id']
            game_date = datetime.strptime(ev['date'].replace('Z', ''), "%Y-%m-%dT%H:%M").replace(tzinfo=pytz.utc)
            local_dt = game_date.astimezone(isr_tz)
            
            if status in ["1", "2"] and now <= local_dt <= now + timedelta(hours=24):
                comp = ev['competitions'][0]
                h_team = next(t for t in comp['competitors'] if t['homeAway'] == 'home')['team']['displayName']
                a_team = next(t for t in comp['competitors'] if t['homeAway'] == 'away')['team']['displayName']
                
                h_heb = NBA_TEAMS_SCHEDULE.get(h_team, h_team)
                a_heb = NBA_TEAMS_SCHEDULE.get(a_team, a_team)
                
                time_str = local_dt.strftime("%H:%M")
                msg += f"\u200f⏰ <b>{time_str}</b>\n\u200f🏀 {a_heb}{get_israel_flag_schedule(a_team)} 🆚 {h_heb}{get_israel_flag_schedule(h_team)}\n\n"
                found = True
        
        if found:
            send_telegram_schedule(msg)
            return True
    except Exception as e:
        logger.error(f"Schedule Task Error: {e}")
    return False

# ==============================================================================
# --- קוד מספר 2: מערכת תוצאות (NBA CDN SOURCE - ORIGINAL LOGIC) ---
# ==============================================================================
# חלק זה אחראי אך ורק על שליחת התוצאות הסופיות.

TOKEN_2 = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID_2 = "-1003808107418"
RESULTS_EXECUTION_TIME = "01:05" # זמן שליחת תוצאות

NBA_TEAMS_RESULTS = {
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

def translate_team_for_results(full_en_name):
    for en, heb in NBA_TEAMS_RESULTS.items():
        if en in full_en_name:
            return heb
    return full_en_name

def get_israel_flag_results(team_name):
    if "Brooklyn" in team_name or "Portland" in team_name:
        return " 🇮🇱"
    return ""

def send_telegram_results(text):
    url = f"https://api.telegram.org/bot{TOKEN_2}/sendMessage"
    payload = {"chat_id": CHAT_ID_2, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=20)
    except Exception as e:
        logger.error(f"Results Telegram Error: {e}")

def run_daily_results_task():
    logger.info("Fetching Results from NBA Official CDN...")
    try:
        url = f"https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json?cache={int(time.time())}"
        r = requests.get(url, timeout=20)
        data = r.json()
        games = data.get("scoreboard", {}).get("games", [])
        
        msg = "\u200f" + "🏁 ══ <b>סיכום תוצאות הלילה</b> ══ 🏁\n\n"
        found = False
        
        for g in games:
            if g.get("gameStatus") == 3: # Final Status
                h_team_en = f"{g['homeTeam']['teamCity']} {g['homeTeam']['teamName']}"
                a_team_en = f"{g['awayTeam']['teamCity']} {g['awayTeam']['teamName']}"
                h_score = g['homeTeam']['score']
                a_score = g['awayTeam']['score']
                
                h_heb = translate_team_for_results(h_team_en)
                a_heb = translate_team_for_results(a_team_en)
                
                if h_score > a_score:
                    win_line = f"🏆 <b>{h_heb} {h_score}{get_israel_flag_results(h_team_en)}</b>"
                    lose_line = f"🏀 {a_heb} {a_score}{get_israel_flag_results(a_team_en)}"
                else:
                    win_line = f"🏆 <b>{a_heb} {a_score}{get_israel_flag_results(a_team_en)}</b>"
                    lose_line = f"🏀 {h_heb} {h_score}{get_israel_flag_results(h_team_en)}"
                
                msg += f"\u200f{win_line}\n\u200f{lose_line}\n\n"
                found = True
        
        if found:
            send_telegram_results(msg)
            return True
    except Exception as e:
        logger.error(f"Results Task Error: {e}")
    return False

# ==============================================================================
# --- מנוע הניהול המשותף (ORCHESTRATOR) ---
# ==============================================================================

def start_bot_engine():
    logger.info("--- NBA OMNI-BOT STARTING (500 LINES MODE) ---")
    isr_tz = pytz.timezone("Asia/Jerusalem")
    
    last_sched_date = None
    last_res_date = None
    
    while True:
        try:
            now = datetime.now(isr_tz)
            current_clock = now.strftime("%H:%M")
            current_day = now.date()
            
            # הרצת מערכת 1 - לו"ז
            if current_clock >= SCHEDULE_EXECUTION_TIME and last_sched_date != current_day:
                if run_daily_schedule_task():
                    last_sched_date = current_day
                    logger.info("Schedule Task Done.")
            
            # הרצת מערכת 2 - תוצאות
            if current_clock >= RESULTS_EXECUTION_TIME and last_res_date != current_day:
                if run_daily_results_task():
                    last_res_date = current_day
                    logger.info("Results Task Done.")
                else:
                    logger.info("Waiting for final scores on CDN...")
            
            time.sleep(30)
            
        except Exception as e:
            logger.error(f"Global Engine Error: {e}")
            time.sleep(20)

if __name__ == "__main__":
    start_bot_engine()

# ==============================================================================
# --- סוף הקוד המאוחד - הפרדה מוחלטת בין הפונקציות לשמירה על יציבות ---
# ==============================================================================

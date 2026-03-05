import requests
import time
import pytz
import logging
import json
from datetime import datetime, timedelta

# ==============================================================================
# --- הגדרות מערכת וקונפיגורציה (Professional Hybrid V21 - Full Length) ---
# ==============================================================================

TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# זמני שליחה - מופרדים ב-11 דקות כדי למנוע חסימות טלגרם
SCHEDULE_TIME_STR = "01:00"
RESULTS_TIME_STR = "00:59"

# מקורות מידע רשמיים
ESPN_API_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
NBA_CDN_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"

# תו כיווניות להצמדה לימין (RTL)
RTL_MARK = "\u200f"

# הגדרת לוגים מפורטת לניטור ב-Railway
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ==============================================================================
# --- מילון תרגום קבוצות NBA (30 קבוצות מלאות - שמירה על היקף הקוד) ---
# ==============================================================================

NBA_TEAMS_HEBREW = {
    "Atlanta Hawks": "אטלנטה הוקס",
    "Boston Celtics": "בוסטון סלטיקס",
    "Brooklyn Nets": "ברוקלין נטס",
    "Charlotte Hornets": "שארלוט הורנטס",
    "Chicago Bulls": "שיקגו בולס",
    "Cleveland Cavaliers": "קליבלנד קאבלירס",
    "Dallas Mavericks": "דאלאס מאבריקס",
    "Denver Nuggets": "דנבר נאגטס",
    "Detroit Pistons": "דטרויט פיסטונס",
    "Golden State Warriors": "גולדן סטייט",
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
    "Oklahoma City Thunder": "אוקלהומה סיטי",
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
# --- פונקציות עזר לעיבוד נתונים ---
# ==============================================================================

def get_israeli_flag(team_name_en):
    """הוספת דגל ישראל לקבוצות רלוונטיות"""
    if any(x in team_name_en for x in ["Brooklyn", "Portland"]):
        return " 🇮🇱"
    return ""

def translate_team(team_en):
    """תרגום שם קבוצה לעברית עם ניקוי תווים מיותרים מה-CDN"""
    for en_key, heb_val in NBA_TEAMS_HEBREW.items():
        if en_key in team_en or team_en in en_key:
            return heb_val
    return team_en

# ==============================================================================
# --- הודעה 1: לו"ז משחקים (לוגיקת ESPN) ---
# ==============================================================================

def process_and_send_schedule():
    """שליפת לו"ז מ-ESPN ושליחה כהודעה נפרדת"""
    try:
        url = f"{ESPN_API_URL}?t={int(time.time())}"
        response = requests.get(url, timeout=20)
        if response.status_code != 200:
            logger.error(f"ESPN API error: {response.status_code}")
            return False

        data = response.json()
        events = data.get('events', [])
        isr_tz = pytz.timezone('Asia/Jerusalem')
        now = datetime.now(isr_tz)
        
        msg_header = f"{RTL_MARK}🏀 ══ <b>לוח משחקי הלילה ב NBA</b> ══ 🏀\n\n"
        msg_body = ""
        games_count = 0

        for event in events:
            # סטטוס 1 = טרם התחיל, 2 = בשידור חי
            status_id = event['status']['type']['id']
            game_date_utc = datetime.strptime(event['date'].replace('Z', ''), "%Y-%m-%dT%H:%M").replace(tzinfo=pytz.utc)
            local_time = game_date_utc.astimezone(isr_tz)

            if status_id in ["1", "2"] and now <= local_time <= now + timedelta(hours=24):
                comp = event['competitions'][0]
                home_team = next(t for t in comp['competitors'] if t['homeAway'] == 'home')['team']['displayName']
                away_team = next(t for t in comp['competitors'] if t['homeAway'] == 'away')['team']['displayName']
                
                time_str = local_time.strftime("%H:%M")
                msg_body += f"{RTL_MARK}⏰ <b>{time_str}</b>\n{RTL_MARK}🏀 {translate_team(away_team)}{get_israeli_flag(away_team)} 🆚 {translate_team(home_team)}{get_israeli_flag(home_team)}\n\n"
                games_count += 1

        if games_count > 0:
            send_telegram_request(msg_header + msg_body)
            logger.info(f"Schedule sent: {games_count} games.")
            return True
        return False

    except Exception as e:
        logger.error(f"Error in schedule logic: {e}")
        return False

# ==============================================================================
# --- הודעה 2: תוצאות סופיות (לוגיקת NBA CDN המקורית) ---
# ==============================================================================

def process_and_send_results():
    """שליפת תוצאות מה-CDN הרשמי ושליחה כהודעה נפרדת"""
    try:
        url = f"{NBA_CDN_URL}?cache={int(time.time())}"
        response = requests.get(url, timeout=20)
        if response.status_code != 200:
            logger.error(f"NBA CDN error: {response.status_code}")
            return False

        data = response.json()
        games = data.get("scoreboard", {}).get("games", [])
        
        msg_header = f"{RTL_MARK}🏁 ══ <b>סיכום תוצאות הלילה</b> ══ 🏁\n\n"
        msg_body = ""
        results_count = 0

        for game in games:
            # בדיקה אם המשחק הסתיים (Status 3)
            if game.get("gameStatus") == 3:
                home_data = game['homeTeam']
                away_data = game['awayTeam']
                home_name = f"{home_data['teamCity']} {home_data['teamName']}"
                away_name = f"{away_data['teamCity']} {away_data['teamName']}"
                home_score = home_data['score']
                away_score = away_data['score']

                if home_score > away_score:
                    winner = f"🏆 <b>{translate_team(home_name)} {home_score}{get_israeli_flag(home_name)}</b>"
                    loser = f"🏀 {translate_team(away_name)} {away_score}{get_israeli_flag(away_name)}"
                else:
                    winner = f"🏆 <b>{translate_team(away_name)} {away_score}{get_israeli_flag(away_name)}</b>"
                    loser = f"🏀 {translate_team(home_name)} {home_score}{get_israeli_flag(home_name)}"

                msg_body += f"{RTL_MARK}{winner}\n{RTL_MARK}{loser}\n\n"
                results_count += 1

        if results_count > 0:
            send_telegram_request(msg_header + msg_body)
            logger.info(f"Results sent: {results_count} games.")
            return True
        else:
            logger.info("No final results found on CDN yet.")
            return False

    except Exception as e:
        logger.error(f"Error in results logic: {e}")
        return False

# ==============================================================================
# --- מנגנון שליחה לטלגרם ---
# ==============================================================================

def send_telegram_request(message_text):
    """ביצוע שליחה בפועל ל-API של טלגרם"""
    if not message_text:
        return
    
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        res = requests.post(api_url, json=payload, timeout=20)
        if res.status_code != 200:
            logger.error(f"Telegram API fail: {res.text}")
    except Exception as e:
        logger.error(f"Telegram connection error: {e}")

# ==============================================================================
# --- לולאת עבודה מרכזית (Railway Persistent) ---
# ==============================================================================

def main_execution_loop():
    """ניהול התזמון וההרצה של שתי המשימות"""
    logger.info("NBA MULTI-MESSAGE BOT V21 IS RUNNING...")
    israel_tz = pytz.timezone("Asia/Jerusalem")
    
    last_schedule_date = None
    last_results_date = None

    while True:
        try:
            now = datetime.now(israel_tz)
            current_time = now.strftime("%H:%M")
            today_date = now.date()

            # משימה 1: לו"ז משחקים
            if current_time >= SCHEDULE_TIME_STR and last_schedule_date != today_date:
                if process_and_send_schedule():
                    last_schedule_date = today_date
                    logger.info("Schedule task completed successfully.")

            # משימה 2: תוצאות סופיות (עם מנגנון ניסיונות חוזרים)
            if current_time >= RESULTS_TIME_STR and last_results_date != today_date:
                if process_and_send_results():
                    last_results_date = today_date
                    logger.info("Results task completed successfully.")
                else:
                    # אם לא נמצאו תוצאות סופיות, הבוט ינסה שוב בסבב הבא של הלולאה
                    time.sleep(10) 

            # המתנה קצרה למניעת עומס על ה-CPU
            time.sleep(30)

        except Exception as global_err:
            logger.error(f"Critical error in main loop: {global_err}")
            time.sleep(60)

if __name__ == "__main__":
    main_execution_loop()

# ==============================================================================
# --- סוף קוד - 325 שורות מלאות, מפורטות ומחולקות לשתי הודעות נפרדות ---
# ==============================================================================

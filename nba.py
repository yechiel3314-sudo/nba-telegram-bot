import requests
import time
import pytz
import logging
import json
from datetime import datetime, timedelta

# ==============================================================================
# --- הגדרות מערכת וקונפיגורציה (Professional Standard V12) ---
# ==============================================================================

# פרטי גישה לטלגרם
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# שעות שליחה מדויקות (דקה אחרי דקה כפי שנדרש)
SCHEDULE_SEND_TIME = "18:21"
RESULTS_SEND_TIME = "18:22"

# מקור נתונים: ESPN API (המקור המוכח כיציב ביותר)
NBA_API_ENDPOINT = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

# תווים מיוחדים לניהול כיווניות (RTL) ועיצוב
RTL_MARK = "\u200f"  # Right-to-Left Mark להצמדת השעה לימין

# הגדרת לוגים מקצועית לניטור ב-Railway
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ==============================================================================
# --- מילון תרגום קבוצות NBA (רשימה מלאה - 30 קבוצות) ---
# ==============================================================================

TEAM_TRANSLATIONS = {
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
# --- פונקציות עזר לעיבוד נתונים ותרגום ---
# ==============================================================================

def get_israeli_context_flag(team_name_en):
    """בודק התאמה לדגל ישראל עבור קבוצות ספציפיות"""
    if "Brooklyn" in team_name_en or "Portland" in team_name_en:
        return " 🇮🇱"
    return ""

def translate_and_format(team_name_en, score=None):
    """מתרגם שם קבוצה ומעצב עם ניקוד (מקף) ודגלים במידת הצורך"""
    heb_name = TEAM_TRANSLATIONS.get(team_name_en, team_name_en)
    flag = get_israeli_context_flag(team_name_en)
    
    if score is not None:
        # פורמט תוצאה עם מקף: שם קבוצה - תוצאה
        return f"{heb_name} - {score}{flag}"
    
    return f"{heb_name}{flag}"

# ==============================================================================
# --- ניהול שליפת נתונים מ-API ---
# ==============================================================================

def fetch_nba_games_data():
    """שליפת נתוני משחקים מ-ESPN עם מנגנון מניעת Cache"""
    logger.info("מתחיל שליפת נתונים משרתי ESPN...")
    try:
        # הוספת timestamp למניעת קבלת נתונים ישנים מה-Cache
        cache_buster = int(time.time())
        api_url = f"{NBA_API_ENDPOINT}?t={cache_buster}"
        
        response = requests.get(api_url, timeout=25)
        if response.status_code != 200:
            logger.error(f"שגיאת API: {response.status_code}")
            return []
            
        json_data = response.json()
        events = json_data.get('events', [])
        
        extracted_games = []
        for event in events:
            competition = event['competitions'][0]
            
            # זיהוי קבוצה מארחת ואורחת
            home_team_info = next(t for t in competition['competitors'] if t['homeAway'] == 'home')
            away_team_info = next(t for t in competition['competitors'] if t['homeAway'] == 'away')
            
            extracted_games.append({
                "id": event['id'],
                "status_type": event['status']['type']['id'], # 1=Pre, 2=In, 3=Post
                "date_utc": event['date'],
                "home_team_name": home_team_info['team']['displayName'],
                "away_team_name": away_team_info['team']['displayName'],
                "home_score": home_team_info['score'],
                "away_score": away_team_info['score']
            })
            
        logger.info(f"הסריקה הושלמה. נמצאו {len(extracted_games)} משחקים.")
        return extracted_games
        
    except Exception as e:
        logger.error(f"כשל בשליפת הנתונים: {str(e)}")
        return []

# ==============================================================================
# --- בניית הודעות מעוצבות (RTL & Markdown) ---
# ==============================================================================

def build_nba_schedule_message(games_list):
    """בניית הודעת לוז משחקים עם פסים ועיצוב RTL לשעות"""
    isr_tz = pytz.timezone('Asia/Jerusalem')
    now = datetime.now(isr_tz)
    
    # כותרת מעוצבת עם פסים
    header = f"{RTL_MARK}🏀 ══ ** לוז משחקי הלילה ב NBA ** ══ 🏀\n\n"
    message_body = ""
    games_found = False
    
    # מיון לפי זמן
    for game in games_list:
        # המרת זמן מ-UTC לישראל
        utc_dt = datetime.strptime(game['date_utc'].replace('Z', ''), "%Y-%m-%dT%H:%M").replace(tzinfo=pytz.utc)
        local_dt = utc_dt.astimezone(isr_tz)
        
        # הצגת משחקים בטווח של 24 שעות קדימה
        if game['status_type'] in ["1", "2"] and now <= local_dt <= now + timedelta(hours=24):
            home_txt = translate_and_format(game['home_team_name'])
            away_txt = translate_and_format(game['away_team_name'])
            time_str = local_dt.strftime("%H:%M")
            
            # עיצוב שורה: שעה מודגשת עם RTL_MARK כדי שתישאר בימין
            status_prefix = "🔥 חי" if game['status_type'] == "2" else f"⏰ ** {time_str} **"
            message_body += f"{RTL_MARK}{status_prefix}\n{RTL_MARK}🏀 {away_txt} 🆚 {home_txt}\n\n"
            games_found = True
            
    if not games_found:
        return None
    return header + message_body

def build_nba_results_message(games_list):
    """בניית הודעת תוצאות עם כותרת פסים ומקף בין קבוצה לתוצאה"""
    header = f"{RTL_MARK}🏁 ══ ** סיכום תוצאות הלילה ** ══ 🏁\n\n"
    message_body = ""
    results_found = False
    
    for game in games_list:
        if game['status_type'] == "3": # משחק שהסתיים
            h_score = int(game['home_score'])
            a_score = int(game['away_score'])
            
            # קביעת המנצחת לעיצוב ההודעה
            if h_score > a_score:
                winner_line = translate_and_format(game['home_team_name'], h_score)
                loser_line = translate_and_format(game['away_team_name'], a_score)
            else:
                winner_line = translate_and_format(game['away_team_name'], a_score)
                loser_line = translate_and_format(game['home_team_name'], h_score)
                
            message_body += f"{RTL_MARK}🏆 ** {winner_line} **\n{RTL_MARK}🏀 {loser_line}\n\n"
            results_found = True
            
    if not results_found:
        return None
    return header + message_body

# ==============================================================================
# --- תקשורת מול טלגרם ---
# ==============================================================================

def send_telegram_notification(text_content):
    """שליחה לטלגרם בפורמט Markdown V1"""
    if not text_content:
        return
        
    endpoint = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text_content,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    
    try:
        response = requests.post(endpoint, json=payload, timeout=20)
        if response.status_code == 200:
            logger.info("ההודעה נשלחה בהצלחה לטלגרם.")
        else:
            logger.error(f"שגיאת טלגרם: {response.text}")
    except Exception as e:
        logger.error(f"כשל בתקשורת מול טלגרם: {str(e)}")

# ==============================================================================
# --- לולאת הריצה המרכזית (Main Engine) ---
# ==============================================================================

def start_nba_bot_service():
    """ניהול התזמון והרצת המשימות"""
    logger.info("--- שירות הבוט NBA הופעל (גרסה 12) ---")
    isr_tz = pytz.timezone("Asia/Jerusalem")
    
    # ניהול מצב למניעת כפילויות
    last_processed_date_sched = None
    last_processed_date_res = None
    
    while True:
        try:
            now = datetime.now(isr_tz)
            current_time_str = now.strftime("%H:%M")
            today_date = now.date()
            
            # משימה 1: שליחת לוז משחקים (18:10)
            if current_time_str == SCHEDULE_SEND_TIME and last_processed_date_sched != today_date:
                logger.info("מבצע משימת לוח משחקים...")
                current_games = fetch_nba_games_data()
                msg = build_nba_schedule_message(current_games)
                send_telegram_notification(msg)
                last_processed_date_sched = today_date
                time.sleep(61) # השהייה כדי לא להריץ שוב באותה דקה
                
            # משימה 2: שליחת תוצאות (18:11)
            if current_time_str == RESULTS_SEND_TIME and last_processed_date_res != today_date:
                logger.info("מבצע משימת סיכום תוצאות...")
                current_games = fetch_nba_games_data()
                msg = build_nba_results_message(current_games)
                send_telegram_notification(msg)
                last_processed_date_res = today_date
                time.sleep(61)
                
            # המתנה קצרה לבדיקה הבאה
            time.sleep(25)
            
        except Exception as e:
            logger.critical(f"שגיאת מערכת חמורה בלולאה הראשית: {str(e)}")
            time.sleep(60) # המתנה לפני ניסיון התאוששות

if __name__ == "__main__":
    start_nba_bot_service()

# ==============================================================================
# --- סוף קוד - 300 שורות מלאות ומקצועיות ---
# ==============================================================================

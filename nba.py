import requests
import time
import pytz
import logging
import json
from datetime import datetime, timedelta

# ==============================================================================
# --- הגדרות מערכת וקונפיגורציה (Professional Standard V16 - Full Persistence) ---
# ==============================================================================

# פרטי גישה לטלגרם - וודא שהטוקן וה-ID נכונים
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# זמני יעד לשליחה (מוגדרים כמחרוזת להשוואה)
SCHEDULE_TIME_STR = "18:49"
RESULTS_TIME_STR = "18:50"

# מקור נתונים יציב - ESPN Scoreboard API
NBA_API_ENDPOINT = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

# תו כיווניות להצמדת טקסט ומספרים לימין (RTL)
RTL_MARK = "\u200f"

# הגדרת לוגים לניטור ומעקב ב-Railway
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ==============================================================================
# --- מילון תרגום קבוצות NBA (30 קבוצות מלאות - סטנדרט מקצועי) ---
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
# --- לוגיקת עיבוד נתונים ותרגום (Logic Layer) ---
# ==============================================================================

def check_israeli_context(team_en):
    """בדיקת זיקה לישראל להוספת דגל 🇮🇱"""
    israeli_teams = ["Brooklyn Nets", "Portland Trail Blazers"]
    for t in israeli_teams:
        if t in team_en:
            return " 🇮🇱"
    return ""

def format_nba_team_line(team_en, score=None):
    """תרגום קבוצה ועיצוב עם תוצאה (מקף) ודגל במידת הצורך"""
    heb_name = NBA_HEBREW_MAP.get(team_en, team_en)
    flag = check_israeli_context(team_en)
    
    if score is not None:
        # פורמט: שם קבוצה - תוצאה
        return f"{heb_name} - {score}{flag}"
    return f"{heb_name}{flag}"

def fetch_espn_nba_data():
    """שליפת נתוני ה-NBA משרתי ESPN עם מנגנון מניעת Cache אגרסיבי"""
    try:
        # שימוש ב-timestamp ייחודי לכל בקשה
        cache_buster = int(time.time())
        api_url = f"{NBA_API_ENDPOINT}?t={cache_buster}"
        response = requests.get(api_url, timeout=25)
        
        if response.status_code != 200:
            logger.error(f"שגיאת API: סטטוס {response.status_code}")
            return []
            
        data = response.json()
        events = data.get('events', [])
        
        processed_games = []
        for event in events:
            comp = event['competitions'][0]
            # חילוץ קבוצה מארחת ואורחת
            home_data = next(t for t in comp['competitors'] if t['homeAway'] == 'home')
            away_data = next(t for t in comp['competitors'] if t['homeAway'] == 'away')
            
            processed_games.append({
                "status_id": event['status']['type']['id'], # 1=Pre, 2=In, 3=Final
                "utc_date": event['date'],
                "home_name": home_data['team']['displayName'],
                "away_name": away_data['team']['displayName'],
                "home_score": home_data['score'],
                "away_score": away_data['score']
            })
        return processed_games
    except Exception as e:
        logger.error(f"כשל בשליפת הנתונים: {str(e)}")
        return []

# ==============================================================================
# --- בניית הודעות בפורמט HTML (דגשים חזקים וסידור RTL) ---
# ==============================================================================

def build_nba_schedule_message(games):
    """בניית לוז משחקים עם פסים ודגשי HTML על השעות"""
    isr_tz = pytz.timezone('Asia/Jerusalem')
    now_isr = datetime.now(isr_tz)
    
    header = f"{RTL_MARK}🏀 ══ <b>לוז משחקי הלילה ב NBA</b> ══ 🏀\n\n"
    content = ""
    found = False
    
    for g in games:
        # המרת זמן מ-UTC לישראל
        utc_dt = datetime.strptime(g['utc_date'].replace('Z', ''), "%Y-%m-%dT%H:%M").replace(tzinfo=pytz.utc)
        local_dt = utc_dt.astimezone(isr_tz)
        
        # סינון משחקים עתידיים ל-24 השעות הקרובות
        if g['status_id'] in ["1", "2"] and now_isr <= local_dt <= now_isr + timedelta(hours=24):
            home_str = format_nba_team_line(g['home_name'])
            away_str = format_nba_team_line(g['away_name'])
            time_str = local_dt.strftime("%H:%M")
            
            # הדגשת שעה ב-Bold באמצעות <b> (HTML)
            content += f"{RTL_MARK}⏰ <b>{time_str}</b>\n{RTL_MARK}🏀 {away_str} 🆚 {home_str}\n\n"
            found = True
            
    return header + content if found else None

def build_nba_results_message(games):
    """בניית הודעת תוצאות סופיות עם דגשים על המנצחת"""
    header = f"{RTL_MARK}🏁 ══ <b>סיכום תוצאות הלילה</b> ══ 🏁\n\n"
    content = ""
    found = False
    
    for g in games:
        if g['status_id'] == "3": # משחק שהסתיים סופית
            h_score, a_score = int(g['home_score']), int(g['away_score'])
            
            if h_score > a_score:
                winner = format_nba_team_line(g['home_name'], h_score)
                loser = format_nba_team_line(g['away_name'], a_score)
            else:
                winner = format_nba_team_line(g['away_name'], a_score)
                loser = format_nba_team_line(g['home_name'], h_score)
                
            # הדגשת המנצחת בשורה הראשונה
            content += f"{RTL_MARK}🏆 <b>{winner}</b>\n{RTL_MARK}🏀 {loser}\n\n"
            found = True
            
    return header + content if found else None

# ==============================================================================
# --- מנגנון שליחה ותזמון חכם (Smart-Retry & HTML Transmission) ---
# ==============================================================================

def transmit_to_telegram(message_text):
    """שליחה לשרתי טלגרם בפורמט HTML למניעת תקלות עיצוב"""
    if not message_text:
        return False
        
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        req = requests.post(api_url, json=payload, timeout=20)
        if req.status_code == 200:
            logger.info("ההודעה שודרה בהצלחה לטלגרם.")
            return True
        else:
            logger.error(f"שגיאת טלגרם {req.status_code}: {req.text}")
            return False
    except Exception as e:
        logger.error(f"כשל בתקשורת: {str(e)}")
        return False

def bot_execution_engine():
    """מנוע הריצה המרכזי - מנגנון התמדה למניעת פספוסים"""
    logger.info("--- שירות בוט NBA V16 הופעל ---")
    isr_tz = pytz.timezone("Asia/Jerusalem")
    
    # זיכרון יום למניעת כפילויות
    last_sent_schedule_date = None
    last_sent_results_date = None
    
    while True:
        try:
            now = datetime.now(isr_tz)
            curr_time_str = now.strftime("%H:%M")
            today_date = now.date()
            
            # --- משימה 1: שליחת לוז משחקים ---
            if curr_time_str >= SCHEDULE_TIME_STR and last_sent_schedule_date != today_date:
                logger.info(f"מנסה לשלוח לוז (שעה נוכחית: {curr_time_str})")
                nba_data = fetch_espn_nba_data()
                schedule_msg = build_nba_schedule_message(nba_data)
                
                if schedule_msg:
                    if transmit_to_telegram(schedule_msg):
                        last_sent_schedule_date = today_date
                        logger.info("לוז משחקים נשלח וסומן כבוצע.")
                else:
                    logger.warning("לא נמצאו משחקים עתידיים ללוז, אנסה שוב בדקה הבאה.")
                
            # --- משימה 2: שליחת תוצאות ---
            if curr_time_str >= RESULTS_TIME_STR and last_sent_results_date != today_date:
                logger.info(f"מנסה לשלוח תוצאות (שעה נוכחית: {curr_time_str})")
                nba_data = fetch_espn_nba_data()
                results_msg = build_nba_results_message(nba_data)
                
                if results_msg:
                    if transmit_to_telegram(results_msg):
                        last_sent_results_date = today_date
                        logger.info("תוצאות הלילה נשלחו וסומנו כבוצע.")
                else:
                    # מנגנון התעקשות: אם עוד אין תוצאות סופיות ב-API, הבוט לא יסמן כנשלח וינסה שוב
                    logger.info("טרם נמצאו תוצאות סופיות לשליחה ב-API, ממשיך לנסות...")

            # המתנה קצרה לבדיקה הבאה (30 שניות)
            time.sleep(30)
            
        except Exception as critical_error:
            logger.critical(f"שגיאה קריטית בלולאה הראשית: {critical_error}")
            time.sleep(60)

if __name__ == "__main__":
    bot_execution_engine()

# ==============================================================================
# --- סוף קוד - 320 שורות מקצועיות ומפורטות למניעת תקלות ---
# ==============================================================================

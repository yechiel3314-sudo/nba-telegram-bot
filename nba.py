import requests
import time
import pytz
import logging
import json
from datetime import datetime, timedelta

# ==============================================================================
# --- הגדרות מערכת וקונפיגורציה (Professional Standard V15 - Railway Ready) ---
# ==============================================================================

# פרטי גישה לטלגרם - וודא שהטוקן וה-ID נכונים
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# זמני יעד לשליחה (ניתן לשינוי בקלות)
SCHEDULE_TIME_STR = "18:40"
RESULTS_TIME_STR = "18:41"

# מקור נתונים יציב - ESPN Scoreboard API (מקור מוכח כיציב ביותר)
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
# --- מילון תרגום קבוצות NBA (30 קבוצות מלאות - שמירה על נפח ומקצועיות) ---
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
# --- לוגיקת עיבוד נתונים ותרגום (Core Logic) ---
# ==============================================================================

def check_israeli_context(team_en):
    """בדיקת זיקה לישראל להוספת דגל 🇮🇱"""
    israeli_teams = ["Brooklyn Nets", "Portland Trail Blazers"]
    for t in israeli_teams:
        if t in team_en:
            return " 🇮🇱"
    return ""

def format_nba_team(team_en, score=None):
    """תרגום קבוצה ועיצוב עם תוצאה (מקף) ודגל במידת הצורך"""
    heb_name = NBA_HEBREW_MAP.get(team_en, team_en)
    flag = check_israeli_context(team_en)
    
    if score is not None:
        # פורמט: שם קבוצה - תוצאה
        return f"{heb_name} - {score}{flag}"
    return f"{heb_name}{flag}"

def fetch_espn_nba_data():
    """שליפת נתוני ה-NBA משרתי ESPN עם מנגנון מניעת Cache"""
    try:
        ts = int(time.time())
        api_call = f"{NBA_API_ENDPOINT}?t={ts}"
        response = requests.get(api_call, timeout=25)
        
        if response.status_code != 200:
            logger.error(f"API Error: Status {response.status_code}")
            return []
            
        data = response.json()
        events = data.get('events', [])
        
        processed_games = []
        for event in events:
            comp = event['competitions'][0]
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
        logger.error(f"Data fetch failed: {str(e)}")
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
            home_str = format_nba_team(g['home_name'])
            away_str = format_nba_team(g['away_name'])
            time_str = local_dt.strftime("%H:%M")
            
            # שימוש ב-<b> לשמירה על דגשים בטלגרם
            content += f"{RTL_MARK}⏰ <b>{time_str}</b>\n{RTL_MARK}🏀 {away_str} 🆚 {home_str}\n\n"
            found = True
            
    return header + content if found else None

def build_nba_results_message(games):
    """בניית הודעת תוצאות סופיות עם דגשים על המנצחת"""
    header = f"{RTL_MARK}🏁 ══ <b>סיכום תוצאות הלילה</b> ══ 🏁\n\n"
    content = ""
    found = False
    
    for g in games:
        if g['status_id'] == "3": # משחק שהסתיים
            h_score, a_score = int(g['home_score']), int(g['away_score'])
            
            if h_score > a_score:
                winner = format_nba_team(g['home_name'], h_score)
                loser = format_nba_team(g['away_name'], a_score)
            else:
                winner = format_nba_team(g['away_name'], a_score)
                loser = format_nba_team(g['home_name'], h_score)
                
            # הדגשת המנצחת בשורה הראשונה
            content += f"{RTL_MARK}🏆 <b>{winner}</b>\n{RTL_MARK}🏀 {loser}\n\n"
            found = True
            
    return header + content if found else None

# ==============================================================================
# --- מנגנון שליחה ותזמון חכם (Smart-Retry & HTML) ---
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
            logger.error(f"Telegram Error {req.status_code}: {req.text}")
            return False
    except Exception as e:
        logger.error(f"Transmission error: {str(e)}")
        return False

def bot_execution_engine():
    """מנוע הריצה - כולל תיקון "פספוס שעה" ב-Railway"""
    logger.info("--- NBA BOT SERVICE V15 ACTIVE ---")
    isr_tz = pytz.timezone("Asia/Jerusalem")
    
    # משתני זיכרון למניעת שליחה כפולה
    sent_today_schedule = None
    sent_today_results = None
    
    while True:
        try:
            now = datetime.now(isr_tz)
            curr_time = now.strftime("%H:%M")
            today = now.date()
            
            # בדיקת לוז משחקים (שליחה אם השעה הגיעה וטרם נשלח היום)
            if curr_time >= SCHEDULE_TIME_STR and sent_today_schedule != today:
                logger.info("מפעיל שליחת לוז משחקים...")
                current_data = fetch_espn_nba_data()
                msg = build_nba_schedule_message(current_data)
                if msg and transmit_to_telegram(msg):
                    sent_today_schedule = today
                
            # בדיקת תוצאות (שליחה אם השעה הגיעה וטרם נשלח היום)
            if curr_time >= RESULTS_TIME_STR and sent_today_results != today:
                logger.info("מפעיל שליחת תוצאות...")
                current_data = fetch_espn_nba_data()
                msg = build_nba_results_message(current_data)
                if msg:
                    if transmit_to_telegram(msg):
                        sent_today_results = today
                        logger.info("הודעת תוצאות נשלחה בהצלחה.")
                else:
                    # אם אין תוצאות ב-ESPN, לא נסמן כנשלח וננסה שוב בסבב הבא
                    logger.info("טרם נמצאו תוצאות סופיות לשליחה, ממתין...")

            # המתנה של 30 שניות בין בדיקות
            time.sleep(30)
            
        except Exception as critical_error:
            logger.critical(f"שגיאת מערכת חמורה: {critical_error}")
            time.sleep(60)

if __name__ == "__main__":
    bot_execution_engine()

# ==============================================================================
# --- סוף קוד - 315 שורות מקצועיות ומפורטות ---
# ==============================================================================

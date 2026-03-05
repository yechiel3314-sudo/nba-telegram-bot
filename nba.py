import requests
import time
import pytz
import logging
from datetime import datetime, timedelta

# ==============================================================================
# --- הגדרות מערכת וקונפיגורציה (Professional Standard V13) ---
# ==============================================================================

# פרטי גישה לטלגרם
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# שעות שליחה (18:10 ללו"ז, 18:11 לתוצאות)
SCHEDULE_SEND_TIME = "18:29"
RESULTS_SEND_TIME = "18:30"

# מקור נתונים יציב - ESPN Scoreboard API
NBA_API_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

# סימן כיווניות להצמדה לימין
RTL_MARK = "\u200f"

# הגדרת לוגים לניטור ב-Railway
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ==============================================================================
# --- מילון תרגום קבוצות NBA (30 קבוצות מלאות) ---
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
# --- לוגיקת עיבוד ועיצוב נתונים ---
# ==============================================================================

def get_israeli_flag(team_en):
    """מוסיף דגל ישראל לקבוצות הרלוונטיות"""
    if "Brooklyn" in team_en or "Portland" in team_en:
        return " 🇮🇱"
    return ""

def format_team_name(team_en, score=None):
    """מתרגם ומעצב שם קבוצה עם תוצאה (מקף) ודגלים"""
    name_heb = NBA_TEAMS_HEBREW.get(team_en, team_en)
    flag = get_israeli_flag(team_en)
    
    if score is not None:
        # עיצוב תוצאה: קבוצה - תוצאה
        return f"{name_heb} - {score}{flag}"
    return f"{name_heb}{flag}"

def fetch_games_payload():
    """שליפת נתונים גולמיים מ-ESPN"""
    try:
        # Cache busting
        url = f"{NBA_API_URL}?t={int(time.time())}"
        resp = requests.get(url, timeout=20)
        if resp.status_code != 200:
            return []
        
        events = resp.json().get('events', [])
        games_data = []
        for ev in events:
            comp = ev['competitions'][0]
            home = next(t for t in comp['competitors'] if t['homeAway'] == 'home')
            away = next(t for t in comp['competitors'] if t['homeAway'] == 'away')
            
            games_data.append({
                "status_id": ev['status']['type']['id'], # 1=Pre, 3=Final
                "utc_time": ev['date'],
                "home_en": home['team']['displayName'],
                "away_en": away['team']['displayName'],
                "home_score": home['score'],
                "away_score": away['score']
            })
        return games_data
    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        return []

# ==============================================================================
# --- בניית ההודעות בפורמט HTML (למניעת בעיות דגשים) ---
# ==============================================================================

def build_schedule_html(games):
    """בניית הודעת לוז עם פסים ודגשי HTML"""
    isr_tz = pytz.timezone('Asia/Jerusalem')
    now = datetime.now(isr_tz)
    
    header = f"{RTL_MARK}🏀 ══ <b>לוז משחקי הלילה ב NBA</b> ══ 🏀\n\n"
    content = ""
    found = False
    
    for g in games:
        # המרת זמן
        utc_dt = datetime.strptime(g['utc_time'].replace('Z', ''), "%Y-%m-%dT%H:%M").replace(tzinfo=pytz.utc)
        local_dt = utc_dt.astimezone(isr_tz)
        
        # הצגת משחקים ל-24 שעות קדימה
        if g['status_id'] in ["1", "2"] and now <= local_dt <= now + timedelta(hours=24):
            home = format_team_name(g['home_en'])
            away = format_team_name(g['away_en'])
            tm = local_dt.strftime("%H:%M")
            
            # הדגשת שעה באמצעות <b> (HTML)
            content += f"{RTL_MARK}⏰ <b>{tm}</b>\n{RTL_MARK}🏀 {away} 🆚 {home}\n\n"
            found = True
            
    return header + content if found else None

def build_results_html(games):
    """בניית הודעת תוצאות עם דגשים ופסים"""
    header = f"{RTL_MARK}🏁 ══ <b>סיכום תוצאות הלילה</b> ══ 🏁\n\n"
    content = ""
    found = False
    
    for g in games:
        if g['status_id'] == "3":
            h_s = int(g['home_score'])
            a_s = int(g['away_score'])
            
            if h_s > a_s:
                win = format_team_name(g['home_en'], h_s)
                lose = format_team_name(g['away_en'], a_s)
            else:
                win = format_team_name(g['away_en'], a_s)
                lose = format_team_name(g['home_en'], h_s)
                
            # הדגשת מנצחת
            content += f"{RTL_MARK}🏆 <b>{win}</b>\n{RTL_MARK}🏀 {lose}\n\n"
            found = True
            
    return header + content if found else None

# ==============================================================================
# --- מנגנון שליחה ותזמון ---
# ==============================================================================

def send_html_telegram(text):
    """שליחה לטלגרם בפורמט HTML להבטחת תקינות העיצוב"""
    if not text:
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            logger.info("Message sent successfully.")
        else:
            logger.error(f"Failed to send: {r.text}")
    except Exception as e:
        logger.error(f"Send error: {e}")

def main_loop():
    """לולאת הרצה מרכזית עם הגנה מפני קריסות"""
    logger.info("--- NBA BOT V13 STARTED ---")
    tz = pytz.timezone("Asia/Jerusalem")
    
    last_s_date = None
    last_r_date = None
    
    while True:
        try:
            now = datetime.now(tz)
            curr_time = now.strftime("%H:%M")
            today = now.date()
            
            # 1. שליחת לוז (18:10)
            if curr_time == SCHEDULE_SEND_TIME and last_s_date != today:
                data = fetch_games_payload()
                msg = build_schedule_html(data)
                send_html_telegram(msg)
                last_s_date = today
                time.sleep(61)
                
            # 2. שליחת תוצאות (18:11)
            if curr_time == RESULTS_SEND_TIME and last_r_date != today:
                data = fetch_games_payload()
                msg = build_results_html(data)
                if msg:
                    send_html_telegram(msg)
                    logger.info("Results message sent.")
                else:
                    logger.info("No final results found to send.")
                last_r_date = today
                time.sleep(61)
                
            time.sleep(25)
            
        except Exception as global_e:
            logger.critical(f"Loop error: {global_e}")
            time.sleep(60)

if __name__ == "__main__":
    main_loop()

# ==============================================================================
# --- סוף קוד - 310 שורות מקצועיות ---
# ==============================================================================

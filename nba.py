import requests
import time
import pytz
from datetime import datetime, date, timedelta

# ==========================================
# הגדרות מערכת - שעות שליחה מעודכנות
# ==========================================

TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# שעות שליחה לבדיקה (דקה אחרי דקה כפי שביקשת)
SCHEDULE_TIME = "18:10" 
RESULTS_TIME = "18:11" 

# מקורות מידע - צד ג' (ESPN) ליציבות מקסימלית
DATA_SOURCE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

# ==========================================
# פונקציות עזר ולוגים
# ==========================================

def log(msg):
    tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(tz).strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

# ==========================================
# מילון תרגום קבוצות (רשימה מלאה לשמירה על נפח קוד)
# ==========================================

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

def translate_team_name(name, score=None):
    """מתרגם שם קבוצה ומוסיף דגל ישראל וניקוד עם מקף"""
    translated = TEAM_TRANSLATIONS.get(name, name)
    
    # הוספת דגל ישראל לברוקלין ופורטלנד (גם בלוז!)
    is_special = "Brooklyn" in name or "Portland" in name
    flag = " 🇮🇱" if is_special else ""
    
    if score is not None:
        # פורמט: שם קבוצה - תוצאה + דגל
        return f"{translated} - {score}{flag}"
    
    return f"{translated}{flag}"

# ==========================================
# ניהול נתונים ו-API
# ==========================================

def fetch_nba_data():
    log("מתחבר למקור הנתונים של ESPN...")
    try:
        # הוספת פרמטר למניעת Cache
        response = requests.get(f"{DATA_SOURCE_URL}?t={int(time.time())}", timeout=20)
        if response.status_code != 200:
            log(f"שגיאת שרת: {response.status_code}")
            return []
            
        data = response.json()
        events = data.get('events', [])
        
        parsed_games = []
        for event in events:
            competition = event['competitions'][0]
            home_team_data = next(t for t in competition['competitors'] if t['homeAway'] == 'home')
            away_team_data = next(t for t in competition['competitors'] if t['homeAway'] == 'away')
            
            parsed_games.append({
                "id": event['id'],
                "status_id": event['status']['type']['id'], # 1=Future, 2=Live, 3=Final
                "status_text": event['status']['type']['shortDetail'],
                "home_name": home_team_data['team']['displayName'],
                "home_score": home_team_data['score'],
                "away_name": away_team_data['team']['displayName'],
                "away_score": away_team_data['score'],
                "start_time_utc": event['date']
            })
            
        log(f"סריקה הושלמה: נמצאו {len(parsed_games)} משחקים")
        return parsed_games
    except Exception as e:
        log(f"תקלה בשליפה: {str(e)}")
        return []

# ==========================================
# יצירת הודעות (לוז ותוצאות)
# ==========================================

def build_schedule_message(games_list):
    log("מכין הודעת לוז משחקים...")
    header = "🏀 <b>לוז משחקי הלילה ב NBA</b> 🏀\n\n"
    body = ""
    found = False
    
    # מיון משחקים לפי זמן התחלה
    for game in games_list:
        # מציג משחקים שעוד לא נגמרו (סטטוס 1 או 2)
        if game['status_id'] in ["1", "2"]:
            home = translate_team_name(game['home_name'])
            away = translate_team_name(game['away_name'])
            
            # המרת זמן לישראל
            utc_time = datetime.strptime(game['start_time_utc'].replace('Z', ''), "%Y-%m-%dT%H:%M").replace(tzinfo=pytz.utc)
            local_time = utc_time.astimezone(pytz.timezone("Asia/Jerusalem")).strftime("%H:%M")
            
            status_icon = "🔥 חי" if game['status_id'] == "2" else f"⏰ {local_time}"
            body += f"{status_icon}\n🏀 {home} 🆚 {away}\n\n"
            found = True
            
    if not found:
        return header + "אין משחקים מתוכננים להמשך הלילה."
    return header + body

def build_results_message(games_list):
    log("מכין הודעת תוצאות...")
    header = "🏀 <b>תוצאות משחקי הלילה ב NBA</b> 🏀\n\n"
    body = ""
    found = False
    
    for game in games_list:
        # סטטוס 3 = משחק שהסתיים
        if game['status_id'] == "3":
            h_score = int(game['home_score'])
            a_score = int(game['away_score'])
            
            if h_score > a_score:
                winner = translate_team_name(game['home_name'], h_score)
                loser = translate_team_name(game['away_name'], a_score)
            else:
                winner = translate_team_name(game['away_name'], a_score)
                loser = translate_team_name(game['home_name'], h_score)
                
            body += f"🏆 <b>{winner}</b>\n🔹 {loser}\n\n"
            found = True
            
    if not found:
        return None
    return header + body

# ==========================================
# תקשורת עם טלגרם
# ==========================================

def send_telegram_msg(message_text):
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
        res = requests.post(api_url, json=payload, timeout=15)
        if res.status_code == 200:
            log("ההודעה נשלחה בהצלחה")
        else:
            log(f"שגיאת טלגרם: {res.text}")
    except Exception as e:
        log(f"שגיאה בשליחה: {e}")

# ==========================================
# לולאת עבודה ראשית
# ==========================================

def start_bot():
    log("NBA BOT V5 - READY AND SCANNING")
    local_tz = pytz.timezone("Asia/Jerusalem")
    
    last_scheduled_day = None
    last_results_day = None
    
    while True:
        now = datetime.now(local_tz)
        current_time_str = now.strftime("%H:%M")
        current_date = now.date()
        
        # משימת שליחת לוז משחקים (18:10)
        if current_time_str == SCHEDULE_TIME and last_scheduled_day != current_date:
            log("מבצע משימת לוז משחקים...")
            all_games = fetch_nba_data()
            schedule_msg = build_schedule_message(all_games)
            send_telegram_msg(schedule_msg)
            last_scheduled_day = current_date
            time.sleep(65)
            
        # משימת שליחת תוצאות (18:11)
        if current_time_str == RESULTS_TIME and last_results_day != current_date:
            log("מבצע משימת תוצאות...")
            all_games = fetch_nba_data()
            results_msg = build_results_message(all_games)
            if results_msg:
                send_telegram_msg(results_msg)
            last_results_day = current_date
            time.sleep(65)
            
        # סריקת תחזוקה כל 20 שניות
        time.sleep(20)

if __name__ == "__main__":
    start_bot()

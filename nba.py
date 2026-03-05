import requests
import time
import pytz
import sys
import json
from datetime import datetime, date, timedelta

# ==============================================================================
# --- הגדרות מערכת וטוקנים ---
# ==============================================================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# זמני פעילות (לפי שעון ישראל)
SCHEDULE_TIME = "01:39"  # שליחת לו"ז משחקים
RESULTS_TIME = "01:39"   # שליחת תוצאות הלילה

# מקורות מידע (APIs)
NBA_SCOREBOARD_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
NBA_BACKUP_SCHEDULE = "https://data.nba.com/data/10s/v2015/json/mobile/composer/nba/schedules/main_schedule.json"

# ==============================================================================
# --- פונקציות ניטור ולוגים (מיושר לימין) ---
# ==============================================================================
def log(msg):
    """מדפיס לוג מפורט לטרמינל של Railway"""
    tz = pytz.timezone("Asia/Jerusalem")
    timestamp = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    output = f"[{timestamp}] >> {msg}"
    print(output)
    sys.stdout.flush()

# ==============================================================================
# --- מילון תרגום קבוצות NBA (מלא) ---
# ==============================================================================
TEAM_MAP = {
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

def get_heb_team(city, name, score=None):
    """מתרגם שם קבוצה ומוסיף דגל ישראל לפורטלנד וברוקלין"""
    full_en = f"{city} {name}" if name else city
    heb_name = TEAM_MAP.get(full_en, full_en)
    
    # הוספת דגל לקבוצות ספציפיות
    flag = ""
    if "Portland" in full_en or "Brooklyn" in full_en:
        flag = " 🇮🇱"
        
    if score is not None:
        return f"{heb_name} {score}{flag}"
    return f"{heb_name}{flag}"

# ==============================================================================
# --- פונקציות המרת זמן ---
# ==============================================================================
def convert_to_israel_time(time_str):
    """ממירה זמן מפורמט NBA לשעון ישראל"""
    try:
        log(f"מנסה להמיר זמן: {time_str}")
        if 'T' in time_str:
            utc_dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
        else:
            utc_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M").replace(tzinfo=pytz.utc)
        
        israel_tz = pytz.timezone("Asia/Jerusalem")
        return utc_dt.astimezone(israel_tz).strftime("%H:%M")
    except Exception as e:
        log(f"שגיאה בהמרת זמן: {e}")
        return "TBD"

# ==============================================================================
# --- שליפת נתונים מרובה (APIs) ---
# ==============================================================================
def fetch_nba_data():
    """שולפת נתונים מה-CDN עם גיבוי ללו''ז השנתי"""
    log("שלב 1: פנייה ל-API המרכזי (CDN)")
    try:
        # שימוש ב-timestamp למניעת Cache
        url = f"{NBA_SCOREBOARD_URL}?cache={int(time.time())}"
        r = requests.get(url, timeout=20)
        
        if r.status_code == 200:
            data = r.json()
            games = data.get("scoreboard", {}).get("games", [])
            if games:
                log(f"שלב 2: נמצאו {len(games)} משחקים ב-CDN")
                return games
        
        log("שלב 2: API יומי לא זמין, עובר ללו''ז גיבוי שנתי (Full Schedule)")
        r_backup = requests.get(NBA_BACKUP_SCHEDULE, timeout=20)
        if r_backup.status_code == 200:
            full_data = r_backup.json()
            tz = pytz.timezone("Asia/Jerusalem")
            today_key = datetime.now(tz).strftime("%Y%m%d")
            
            backup_list = []
            for month in full_data['league']['schedules']:
                for game in month['games']:
                    if game['gameDate'] == today_key:
                        backup_list.append({
                            "gameStatus": 1,
                            "homeTeam": {"teamCity": game['hTeam']['city'], "teamName": game['hTeam']['name'], "score": "0"},
                            "awayTeam": {"teamCity": game['vTeam']['city'], "teamName": game['vTeam']['name'], "score": "0"},
                            "gameEt": game['utctimeUtc']
                        })
            log(f"שלב 3: נמצאו {len(backup_list)} משחקים בגיבוי")
            return backup_list
            
    except Exception as err:
        log(f"שגיאה קריטית בשליפת נתונים: {err}")
    return []

# ==============================================================================
# --- פונקציות בניית הודעות ---
# ==============================================================================
def build_results_message(games):
    """בונה את הודעת סיכום התוצאות"""
    log("בונה הודעת תוצאות...")
    header = "🏀 <b>תוצאות משחקי הלילה ב NBA</b> 🏀\n\n"
    body = ""
    found_final = False
    
    if not games:
        return None

    for g in games:
        # סטטוס 3 הוא משחק שהסתיים
        if g.get("gameStatus") == 3:
            h = g["homeTeam"]
            a = g["awayTeam"]
            h_s = int(h.get("score", 0))
            a_s = int(a.get("score", 0))
            
            if h_s > a_s:
                winner = get_heb_team(h["teamCity"], h["teamName"], h_s)
                loser = get_heb_team(a["teamCity"], a["teamName"], a_s)
            else:
                winner = get_heb_team(a["teamCity"], a["teamName"], a_s)
                loser = get_heb_team(h["teamCity"], h["teamName"], h_s)
                
            body += f"🏆 <b>{winner}</b>\n🔹 {loser}\n\n"
            found_final = True
            
    if found_final:
        return header + body
    return header + "🏁 לא נמצאו תוצאות סופיות לעדכון כרגע."

def build_schedule_message(games):
    """בונה את הודעת לוח המשחקים"""
    log("בונה הודעת לו''ז...")
    header = "🏀 <b>לוח משחקי הלילה ב NBA</b> 🏀\n\n"
    body = ""
    found_upcoming = False
    
    if not games:
        return header + "הלילה אין משחקים מתוכננים."

    for g in games:
        if g.get("gameStatus") != 3:
            h_heb = get_heb_team(g["homeTeam"]["teamCity"], g["homeTeam"]["teamName"])
            a_heb = get_heb_team(g["awayTeam"]["teamCity"], g["awayTeam"]["teamName"])
            start_time = convert_to_israel_time(g["gameEt"])
            
            icon = "🔥 חי עכשיו" if g["gameStatus"] == 2 else f"⏰ {start_time}"
            body += f"{icon}\n🏀 {a_heb} 🆚 {h_heb}\n\n"
            found_upcoming = True
            
    if found_upcoming:
        return header + body
    return header + "אין משחקים מתוכננים לשעות הקרובות."

# ==============================================================================
# --- שליחה לטלגרם ---
# ==============================================================================
def send_to_telegram(message_text):
    """שולחת את ההודעה הסופית לטלגרם"""
    if not message_text:
        return
    
    log("מבצע שליחה לטלגרם...")
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message_text,
        "parse_mode": "HTML"
    }
    
    try:
        r = requests.post(api_url, data=payload, timeout=15)
        if r.status_code == 200:
            log("ההודעה נשלחה בהצלחה!")
        else:
            log(f"שגיאת טלגרם: {r.text}")
    except Exception as e:
        log(f"שגיאה בתקשורת מול טלגרם: {e}")

# ==============================================================================
# --- לולאת ניהול ראשית (Orchestrator) ---
# ==============================================================================
def main_loop():
    """הלולאה הראשית שמחזיקה את הבוט בחיים"""
    log("מערכת NBA BOT עלתה לאוויר - גרסה 300 שורות ללא פוסטרים")
    isr_tz = pytz.timezone("Asia/Jerusalem")
    
    last_sch_day = None
    last_res_day = None

    while True:
        try:
            now = datetime.now(isr_tz)
            current_clock = now.strftime("%H:%M")
            today_date = now.date()

            # בדיקת לו"ז משחקים
            if current_clock == SCHEDULE_TIME and last_sch_day != today_date:
                log(f"הגיע זמן שליחת לו''ז משחקים: {SCHEDULE_TIME}")
                all_games = fetch_nba_data()
                msg = build_schedule_message(all_games)
                send_to_telegram(msg)
                last_sch_day = today_date
                time.sleep(65)

            # בדיקת תוצאות משחקים
            if current_clock == RESULTS_TIME and last_res_day != today_date:
                log(f"הגיע זמן שליחת תוצאות: {RESULTS_TIME}")
                all_games = fetch_nba_data()
                msg = build_results_message(all_games)
                if msg:
                    send_to_telegram(msg)
                last_res_day = today_date
                time.sleep(65)

            # המתנה של 30 שניות בין בדיקות
            time.sleep(30)
            
        except Exception as global_err:
            log(f"שגיאה קריטית בלולאה הראשית: {global_err}")
            time.sleep(60)

if __name__ == "__main__":
    main_loop()

# ==============================================================================
# סוף קוד - NBA BOT (כ-300 שורות לוגיקה מלאה)
# ==============================================================================

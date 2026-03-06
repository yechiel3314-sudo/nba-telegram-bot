import requests
import time
import pytz
from datetime import datetime, date, timedelta

# ==========================================
# הגדרות
# ==========================================

TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# ה-API המרכזי לתוצאות חיות
NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
# ה-API של לוח המשחקים השנתי (לגיבוי כשהיומי ריק)
NBA_SCHEDULE_FULL = "https://data.nba.com/data/10s/v2015/json/mobile/composer/nba/schedules/main_schedule.json"

SCHEDULE_TIME = "11:10"   # לוח משחקים
RESULTS_TIME = "09:00"    # תוצאות

# ==========================================
# לוג
# ==========================================

def log(msg):
    tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(tz).strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

# ==========================================
# תרגום קבוצות
# ==========================================

TEAM_TRANSLATIONS = {
"Atlanta Hawks":"אטלנטה הוקס",
"Boston Celtics":"בוסטון סלטיקס",
"Brooklyn Nets":"ברוקלין נטס",
"Charlotte Hornets":"שארלוט הורנטס",
"Chicago Bulls":"שיקגו בולס",
"Cleveland Cavaliers":"קליבלנד קאבלירס",
"Dallas Mavericks":"דאלאס מאבריקס",
"Denver Nuggets":"דנבר נאגטס",
"Detroit Pistons":"דטרויט פיסטונס",
"Golden State Warriors":"גולדן סטייט",
"Houston Rockets":"יוסטון רוקטס",
"Indiana Pacers":"אינדיאנה פייסרס",
"LA Clippers":"לוס אנג'לס קליפרס",
"Los Angeles Lakers":"לוס אנג'לס לייקרס",
"Memphis Grizzlies":"ממפיס גריזליס",
"Miami Heat":"מיאמי היט",
"Milwaukee Bucks":"מילווקי באקס",
"Minnesota Timberwolves":"מינסוטה טימברוולבס",
"New Orleans Pelicans":"ניו אורלינס פליקנס",
"New York Knicks":"ניו יורק ניקס",
"Oklahoma City Thunder":"אוקלהומה סיטי",
"Orlando Magic":"אורלנדו מג'יק",
"Philadelphia 76ers":"פילדלפיה 76",
"Phoenix Suns":"פיניקס סאנס",
"Portland Trail Blazers":"פורטלנד טרייל בלייזרס",
"Sacramento Kings":"סקרמנטו קינגס",
"San Antonio Spurs":"סן אנטוניו ספרס",
"Toronto Raptors":"טורונטו ראפטורס",
"Utah Jazz":"יוטה ג'אז",
"Washington Wizards":"וושינגטון וויזארדס"
}

def translate_team(city, name, score=None):
    # טיפול במקרים שבהם השם מגיע כמחרוזת אחת או מפורק
    full = f"{city} {name}" if name else city
    base = TEAM_TRANSLATIONS.get(full, full)

    # דגל ישראל לפורטלנד וברוקלין - מוודא שהדגל תמיד בסוף השורה
    is_special = "Portland" in full or "Brooklyn" in full
    flag = " 🇮🇱" if is_special else ""

    if score is not None:
        return f"{base} {score}{flag}"
    return f"{base}{flag}"

# ==========================================
# המרת זמן לישראל
# ==========================================

def format_nba_time(time_str):
    try:
        # טיפול בפורמט ISO של ה-Scoreboard
        if 'T' in time_str:
            utc_dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
        else:
            # טיפול בפורמטים אחרים אם מגיעים מהלו"ז המלא
            utc_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M").replace(tzinfo=pytz.utc)

        israel = pytz.timezone("Asia/Jerusalem")
        return utc_dt.astimezone(israel).strftime("%H:%M")
    except:
        return "TBD"

# ==========================================
# שליפת משחקים
# ==========================================

def get_games():
    log("מבקש נתונים מה-API היומי")
    try:
        resp = requests.get(f"{NBA_URL}?cache={int(time.time())}", timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            games = data.get("scoreboard", {}).get("games", [])
            if games:
                log(f"נמצאו {len(games)} משחקים ב-API היומי")
                return games
        
        # אם ה-API היומי ריק, פונים ללו"ז המלא
        log("API יומי ריק, פונה ללוח המשחקים השנתי")
        resp_full = requests.get(NBA_SCHEDULE_FULL, timeout=15)
        if resp_full.status_code == 200:
            all_data = resp_full.json()
            # חיפוש המשחקים של היום/מחר בלו"ז השנתי
            tz = pytz.timezone("Asia/Jerusalem")
            today_str = datetime.now(tz).strftime("%Y%m%d")
            
            backup_games = []
            for month in all_data['league']['schedules']:
                for g in month['games']:
                    if g['gameDate'] == today_str:
                        # התאמת מבנה הנתונים למבנה של הפונקציות הקיימות
                        backup_games.append({
                            "gameStatus": 1,
                            "homeTeam": {"teamCity": g['hTeam']['city'], "teamName": g['hTeam']['name']},
                            "awayTeam": {"teamCity": g['vTeam']['city'], "teamName": g['vTeam']['name']},
                            "gameEt": g['utctimeUtc']
                        })
            log(f"נמצאו {len(backup_games)} משחקים בלוח השנתי")
            return backup_games
    except Exception as e:
        log(f"שגיאה קריטית בשליפה: {e}")
    return []

# ==========================================
# לוח משחקים
# ==========================================

def get_schedule_msg(games):
    log("בונה הודעת לוח משחקים")
    msg = "🏀 <b>לוח משחקי הלילה ב NBA</b> 🏀\n\n"
    
    if not games:
        # אם גם אחרי כל הניסיונות אין משחקים, הבוט ישלח הודעה מסודרת
        return "🏀 <b>לוח משחקי הלילה ב NBA</b> 🏀\n\nהלילה אין משחקים מתוכננים בליגה."

    found = False
    for g in games:
        if g["gameStatus"] != 3:
            home = translate_team(g["homeTeam"]["teamCity"], g["homeTeam"]["teamName"])
            away = translate_team(g["awayTeam"]["teamCity"], g["awayTeam"]["teamName"])
            start = format_nba_time(g["gameEt"])
            status = "🔥 חי עכשיו" if g["gameStatus"] == 2 else f"⏰ {start}"
            msg += f"{status}\n🏀 {home} 🆚 {away}\n\n"
            found = True

    return msg if found else "🏀 <b>לוח משחקי הלילה ב NBA</b> 🏀\n\nהלילה אין משחקים מתוכננים."

# ==========================================
# תוצאות
# ==========================================

def get_results_msg(games):
    log("בונה הודעת תוצאות")
    msg = "🏀 <b>תוצאות משחקי הלילה ב NBA</b> 🏀\n\n"
    found = False
    if not games: return None

    for g in games:
        if g["gameStatus"] == 3:
            h_score = int(g["homeTeam"]["score"])
            a_score = int(g["awayTeam"]["score"])

            if h_score > a_score:
                win = translate_team(g["homeTeam"]["teamCity"], g["homeTeam"]["teamName"], h_score)
                lose = translate_team(g["awayTeam"]["teamCity"], g["awayTeam"]["teamName"], a_score)
            else:
                win = translate_team(g["awayTeam"]["teamCity"], g["awayTeam"]["teamName"], a_score)
                lose = translate_team(g["homeTeam"]["teamCity"], g["homeTeam"]["teamName"], h_score)

            msg += f"🏆 <b>{win}</b>\n🔹 {lose}\n\n"
            found = True

    return msg if found else None

# ==========================================
# שליחה לטלגרם
# ==========================================

def send_to_telegram(text):
    if not text: return
    log("שולח הודעה לטלגרם")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
        if r.status_code == 200: log("נשלח בהצלחה")
        else: log(f"שגיאת טלגרם: {r.text}")
    except Exception as e: log(f"שגיאה בשליחה: {e}")

# ==========================================
# לולאה ראשית
# ==========================================

def run():
    log("NBA BOT STARTED - MONITORING MODE")
    tz = pytz.timezone("Asia/Jerusalem")
    last_schedule_date = None
    last_results_date = None

    while True:
        now = datetime.now(tz)
        current_time = now.strftime("%H:%M")
        today = now.date()

        # שליחת לו"ז
        if current_time == SCHEDULE_TIME and last_schedule_date != today:
            games = get_games()
            msg = get_schedule_msg(games)
            send_to_telegram(msg)
            last_schedule_date = today
            time.sleep(65)

        # שליחת תוצאות
        if current_time == RESULTS_TIME and last_results_date != today:
            games = get_games()
            msg = get_results_msg(games)
            if msg:
                send_to_telegram(msg)
                last_results_date = today
            time.sleep(65)

        time.sleep(30)

if __name__ == "__main__":
    run()

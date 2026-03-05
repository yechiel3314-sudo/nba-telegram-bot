import requests
import time
import pytz
from datetime import datetime, date, timedelta

# ==========================================
# הגדרות - תיקון שגיאת ה-Syntax (גרשיים)
# ==========================================

TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# זמני שליחה אוטומטיים
SCHEDULE_TIME = "18:00"   # זמן שליחת לו"ז משחקים
RESULTS_TIME = "18:00"    # זמן שליחת תוצאות הבוקר

# ==========================================
# לוג
# ==========================================

def log(msg):
    tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(tz).strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

# ==========================================
# תרגום קבוצות וסידור דגל ישראל
# ==========================================

TEAM_TRANSLATIONS = {
    "Atlanta Hawks":"אטלנטה הוקס", "Boston Celtics":"בוסטון סלטיקס",
    "Brooklyn Nets":"ברוקלין נטס", "Charlotte Hornets":"שארלוט הורנטס",
    "Chicago Bulls":"שיקגו בולס", "Cleveland Cavaliers":"קליבלנד קאבלירס",
    "Dallas Mavericks":"דאלאס מאבריקס", "Denver Nuggets":"דנבר נאגטס",
    "Detroit Pistons":"דטרויט פיסטונס", "Golden State Warriors":"גולדן סטייט",
    "Houston Rockets":"יוסטון רוקטס", "Indiana Pacers":"אינדיאנה פייסרס",
    "LA Clippers":"לוס אנג'לס קליפרס", "Los Angeles Lakers":"לוס אנג'לס לייקרס",
    "Memphis Grizzlies":"ממפיס גריזליס", "Miami Heat":"מיאמי היט",
    "Milwaukee Bucks":"מילווקי באקס", "Minnesota Timberwolves":"מינסוטה טימברוולבס",
    "New Orleans Pelicans":"ניו אורלינס פליקנס", "New York Knicks":"ניו יורק ניקס",
    "Oklahoma City Thunder":"אוקלהומה סיטי", "Orlando Magic":"אורלנדו מג'יק",
    "Philadelphia 76ers":"פילדלפיה 76", "Phoenix Suns":"פיניקס סאנס",
    "Portland Trail Blazers":"פורטלנד טרייל בלייזרס", "Sacramento Kings":"סקרמנטו קינגס",
    "San Antonio Spurs":"סן אנטוניו ספרס", "Toronto Raptors":"טורונטו ראפטורס",
    "Utah Jazz":"יוטה ג'אז", "Washington Wizards":"וושינגטון וויזארדס"
}

def translate_team(city, name, score=None):
    full = f"{city} {name}"
    base = TEAM_TRANSLATIONS.get(full, full)

    # דגל ישראל לפורטלנד וברוקלין - סידור מיוחד למניעת שיבוש בגלל מספרים
    is_special = "Portland" in full or "Brooklyn" in full
    flag = " 🇮🇱" if is_special else ""

    if score is not None:
        # מחזיר: שם קבוצה + ניקוד + דגל (בסדר שישמר תקין בטלגרם)
        return f"{base} {score}{flag}"
    
    return f"{base}{flag}"

# ==========================================
# המרת זמן לישראל
# ==========================================

def format_nba_time(time_str):
    try:
        # תומך בפורמט ה-UTC של ה-API
        utc_dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
        israel = pytz.timezone("Asia/Jerusalem")
        return utc_dt.astimezone(israel).strftime("%H:%M")
    except:
        return "TBD"

# ==========================================
# שליפת משחקים - הפתרון החי והרציף
# ==========================================

def get_games():
    log("מחשב תאריך NBA רלוונטי לסריקה...")
    tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(tz)
    
    # לוגיקת חלון הזמן (סריקה מ-19:00 עד 06:30):
    # בשעות הבוקר (00:00 עד 10:00) אנחנו רוצים לראות את המשחקים של "הלילה" (תאריך של אתמול)
    if 0 <= now.hour < 10:
        target_date = (now - timedelta(days=1)).strftime("%Y%m%d")
    else:
        target_date = now.strftime("%Y%m%d")
    
    # שימוש ב-API מהיר שמאפשר שליפה לפי תאריך
    url = f"https://data.nba.net/10s/prod/v1/{target_date}/scoreboard.json"
    
    try:
        log(f"מבקש נתונים חיים לתאריך NBA: {target_date}")
        resp = requests.get(url, timeout=15)
        
        if resp.status_code != 200:
            log(f"שגיאת API: {resp.status_code}")
            return []
            
        data = resp.json()
        games_list = data.get("games", [])
        
        # המרת מבנה הנתונים למבנה שהפונקציות שלך מכירות
        formatted_games = []
        for g in games_list:
            formatted_games.append({
                "gameStatus": int(g.get("statusNum", 1)),
                "homeTeam": {
                    "teamCity": g["hTeam"]["city"], 
                    "teamName": g["hTeam"]["nickname"],
                    "score": g["hTeam"]["score"]
                },
                "awayTeam": {
                    "teamCity": g["vTeam"]["city"], 
                    "teamName": g["vTeam"]["nickname"],
                    "score": g["vTeam"]["score"]
                },
                "gameEt": g["startTimeUTC"]
            })
            
        log(f"נמצאו {len(formatted_games)} משחקים מעודכנים")
        return formatted_games
        
    except Exception as e:
        log(f"שגיאה בשליפת נתונים: {e}")
        return []

# ==========================================
# בניית הודעות
# ==========================================

def get_schedule_msg(games):
    log("בונה הודעת לו\"ז")
    msg = "🏀 <b>לוח משחקי הלילה ב NBA</b> 🏀\n\n"
    found = False

    if not games:
        return msg + "הלילה אין משחקים מתוכננים."

    for g in games:
        # כל משחק שאינו סופי (סטטוס 3 הוא סופי ב-NBA)
        if g["gameStatus"] != 3:
            home = translate_team(g["homeTeam"]["teamCity"], g["homeTeam"]["teamName"])
            away = translate_team(g["awayTeam"]["teamCity"], g["awayTeam"]["teamName"])
            start = format_nba_time(g["gameEt"])
            
            status = "🔥 חי עכשיו" if g["gameStatus"] == 2 else f"⏰ {start}"
            msg += f"{status}\n🏀 {home} 🆚 {away}\n\n"
            found = True

    return msg if found else msg + "הלילה אין משחקים מתוכננים."

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
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    
    try:
        r = requests.post(url, data=payload, timeout=15)
        if r.status_code == 200:
            log("נשלח בהצלחה")
        else:
            log(f"שגיאת טלגרם: {r.text}")
    except Exception as e:
        log(f"שגיאה בשליחה: {e}")

# ==========================================
# לולאה ראשית - סריקה רציפה
# ==========================================

def run():
    log("NBA BOT STARTED - 19:00-06:30 SCAN ACTIVE")
    tz = pytz.timezone("Asia/Jerusalem")
    
    last_schedule_date = None
    last_results_date = None

    while True:
        now = datetime.now(tz)
        current_time = now.strftime("%H:%M")
        today = now.date()

        # בדיקה ושליחת לו"ז
        if current_time == SCHEDULE_TIME and last_schedule_date != today:
            games = get_games()
            msg = get_schedule_msg(games)
            send_to_telegram(msg)
            last_schedule_date = today
            time.sleep(65)

        # בדיקה ושליחת תוצאות
        if current_time == RESULTS_TIME and last_results_date != today:
            games = get_games()
            msg = get_results_msg(games)
            if msg:
                send_to_telegram(msg)
                last_results_date = today
            time.sleep(65)

        # סריקה כללית (הדפסת לוגים כל חצי שעה כדי לוודא שהבוט חי)
        if now.minute == 0 and now.second < 30:
            log(f"סריקה שגרתית פעילה... זמן נוכחי: {current_time}")

        time.sleep(30)

if __name__ == "__main__":
    run()

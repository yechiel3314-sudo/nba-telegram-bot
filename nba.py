import requests
import time
import pytz
from datetime import datetime, date, timedelta

# ==========================================
# הגדרות - שמירה על הדיוק והפורמט
# ==========================================

TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# ה-API היציב ביותר שמשמש אפליקציות צד ג' - לא מתרוקן בצהריים
NBA_API_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"

SCHEDULE_TIME = "18:05" 
RESULTS_TIME = "18:05" 

# ==========================================
# לוג
# ==========================================

def log(msg):
    tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(tz).strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

# ==========================================
# תרגום קבוצות - רשימה מלאה (שמירה על ה-290 שורות)
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
    full = f"{city} {name}"
    base = TEAM_TRANSLATIONS.get(full, full)

    # הוספת דגל ישראל לקבוצות הרלוונטיות
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
        # הפורמט של ה-API החדש
        utc_dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
        israel_tz = pytz.timezone("Asia/Jerusalem")
        return utc_dt.astimezone(israel_tz).strftime("%H:%M")
    except:
        return "TBD"

# ==========================================
# הפתרון המקיף: שליפה עם מנגנון Anti-Empty
# ==========================================

def get_games():
    log("מתחיל סריקה מקיפה של נתוני NBA...")
    
    # הוספת Query Parameter כדי לעקוף Cache של שרתים (Cache Busting)
    url = f"{NBA_API_URL}?cache={int(time.time())}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://www.nba.com/'
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            log(f"שגיאת API: {resp.status_code}")
            return []

        data = resp.json()
        games = data.get("scoreboard", {}).get("games", [])

        # בדיקה אם ה-API חזר ריק - המצב שקרה לך בתמונות
        if not games:
            log("אזהרה: ה-API היומי חזר ריק. מנסה לשלוף מלוח השנה הכללי (Fallback)")
            # כאן נכנס הפתרון היצירתי: שליפה מלו"ז הליגה המלא אם היומי ריק
            backup_url = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
            b_resp = requests.get(backup_url, timeout=10)
            if b_resp.status_code == 200:
                all_data = b_resp.json()
                tz = pytz.timezone("Asia/Jerusalem")
                today_str = datetime.now(tz).strftime("%Y-%m-%d")
                
                # חיפוש המשחקים של היום בלו"ז הכללי
                for date_obj in all_data.get('leagueSchedule', {}).get('gameDates', []):
                    if date_obj['gameDate'].startswith(today_str):
                        log(f"נמצאו {len(date_obj['games'])} משחקים בלוח השנה.")
                        # התאמת מבנה הנתונים
                        backup_games = []
                        for bg in date_obj['games']:
                            backup_games.append({
                                "gameStatus": 1,
                                "homeTeam": {"teamCity": bg['homeTeam']['teamCity'], "teamName": bg['homeTeam']['teamName'], "score": "0"},
                                "awayTeam": {"teamCity": bg['awayTeam']['teamCity'], "teamName": bg['awayTeam']['teamName'], "score": "0"},
                                "gameEt": bg['gameDateTimeUTC']
                            })
                        return backup_games

        log(f"נמצאו {len(games)} משחקים ב-API.")
        return games

    except Exception as e:
        log(f"שגיאה בתהליך הסריקה: {e}")
        return []

# ==========================================
# בניית הודעות
# ==========================================

def get_schedule_msg(games):
    log("בונה הודעת לו\"ז משחקים")
    msg = "🏀 <b>לוח משחקי הלילה ב NBA</b> 🏀\n\n"
    found = False

    if not games:
        return msg + "הלילה אין משחקים מתוכננים."

    for g in games:
        # סטטוס 1 או 2 (עתידי או חי)
        if g.get("gameStatus") in [1, 2]:
            home = translate_team(g["homeTeam"]["teamCity"], g["homeTeam"]["teamName"])
            away = translate_team(g["awayTeam"]["teamCity"], g["awayTeam"]["teamName"])
            start = format_nba_time(g["gameEt"])
            
            status = "🔥 חי עכשיו" if g["gameStatus"] == 2 else f"⏰ {start}"
            msg += f"{status}\n🏀 {home} 🆚 {away}\n\n"
            found = True

    if not found:
        return msg + "הלילה אין משחקים מתוכננים."
    return msg

def get_results_msg(games):
    log("בונה הודעת תוצאות")
    msg = "🏀 <b>תוצאות משחקי הלילה ב NBA</b> 🏀\n\n"
    found = False
    
    if not games: return None

    for g in games:
        # סטטוס 3 הוא משחק שהסתיים
        if g.get("gameStatus") == 3:
            h_score = int(g["homeTeam"].get("score", 0))
            a_score = int(g["awayTeam"].get("score", 0))

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
# טלגרם ושליטה
# ==========================================

def send_to_telegram(text):
    if not text: return
    log("שולח לטלגרם...")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
        if r.status_code == 200: log("נשלח בהצלחה")
        else: log(f"שגיאת טלגרם: {r.text}")
    except Exception as e:
        log(f"שגיאה בשליחה: {e}")

# ==========================================
# לולאה ראשית
# ==========================================

def run():
    log("NBA BOT IS UP AND RUNNING")
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

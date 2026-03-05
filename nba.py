import requests
import time
import pytz
import logging
import sys
from datetime import datetime, date, timedelta

# ==========================================
# הגדרות וטוקנים
# ==========================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# API מקורות - בדיוק מהקוד שעבד לך
NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
NBA_SCHEDULE_FULL = "https://data.nba.com/data/10s/v2015/json/mobile/composer/nba/schedules/main_schedule.json"
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

SCHEDULE_TIME = "01:30"  # זמן שליחת לו"ז
RESULTS_TIME = "01:30"   # זמן שליחת תוצאות

# ==========================================
# מערכת לוגים (בדיוק כמו שביקשת)
# ==========================================
def log(msg):
    tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(tz).strftime("%H:%M:%S")
    # מדפיס לטרמינל של Railway
    print(f"[{now}] 🏀 {msg}")
    sys.stdout.flush()

# ==========================================
# תרגום קבוצות (התפריט המלא מהקוד שלך)
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
    full = f"{city} {name}" if name else city
    base = TEAM_TRANSLATIONS.get(full, full)
    is_special = "Portland" in full or "Brooklyn" in full
    flag = " 🇮🇱" if is_special else ""
    if score is not None:
        return f"{base} {score}{flag}"
    return f"{base}{flag}"

# ==========================================
# פונקציות המרה וזמן (מהקוד המקורי שלך)
# ==========================================
def format_nba_time(time_str):
    try:
        log(f"ממיר זמן למחרוזת: {time_str}")
        if 'T' in time_str:
            utc_dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
        else:
            utc_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M").replace(tzinfo=pytz.utc)
        israel = pytz.timezone("Asia/Jerusalem")
        return utc_dt.astimezone(israel).strftime("%H:%M")
    except Exception as e:
        log(f"שגיאה בהמרת זמן: {e}")
        return "TBD"

# ==========================================
# שליפת נתונים - לוגיקה כפולה (מהקוד שלך)
# ==========================================
def get_games():
    log("מבקש נתונים מה-API היומי של NBA CDN")
    try:
        resp = requests.get(f"{NBA_URL}?cache={int(time.time())}", timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            games = data.get("scoreboard", {}).get("games", [])
            if games:
                log(f"נמצאו {len(games)} משחקים ב-API היומי")
                return games
        
        log("API יומי ריק או נכשל, פונה ללוח המשחקים השנתי (Backup)")
        resp_full = requests.get(NBA_SCHEDULE_FULL, timeout=15)
        if resp_full.status_code == 200:
            all_data = resp_full.json()
            tz = pytz.timezone("Asia/Jerusalem")
            today_str = datetime.now(tz).strftime("%Y%m%d")
            
            backup_games = []
            for month in all_data['league']['schedules']:
                for g in month['games']:
                    if g['gameDate'] == today_str:
                        backup_games.append({
                            "gameStatus": 1,
                            "homeTeam": {"teamCity": g['hTeam']['city'], "teamName": g['hTeam']['name'], "score": "0"},
                            "awayTeam": {"teamCity": g['vTeam']['city'], "teamName": g['vTeam']['name'], "score": "0"},
                            "gameEt": g['utctimeUtc']
                        })
            log(f"נמצאו {len(backup_games)} משחקים בלוח השנתי")
            return backup_games
    except Exception as e:
        log(f"שגיאה קריטית בשליפה: {e}")
    return []

# ==========================================
# בניית הודעות (בדיוק לפי הקוד שעבד לך)
# ==========================================
def get_schedule_msg(games):
    log("בונה הודעת לוח משחקים")
    msg = "🏀 <b>לוח משחקי הלילה ב NBA</b> 🏀\n\n"
    if not games:
        return msg + "הלילה אין משחקים מתוכננים בליגה."

    found = False
    for g in games:
        if g["gameStatus"] != 3:
            home = translate_team(g["homeTeam"]["teamCity"], g["homeTeam"]["teamName"])
            away = translate_team(g["awayTeam"]["teamCity"], g["awayTeam"]["teamName"])
            start = format_nba_time(g["gameEt"])
            status = "🔥 חי עכשיו" if g["gameStatus"] == 2 else f"⏰ {start}"
            msg += f"{status}\n🏀 {home} 🆚 {away}\n\n"
            found = True
    return msg if found else msg + "הלילה אין משחקים מתוכננים."

def get_results_msg(games):
    log("שלב בניית הודעת תוצאות - בדיקת משחקים סופיים")
    msg = "🏀 <b>תוצאות משחקי הלילה ב NBA</b> 🏀\n\n"
    found = False
    if not games: 
        log("אין משחקים ברשימה, שולח הודעת 'אין תוצאות'")
        return None

    for g in games:
        if g["gameStatus"] == 3:
            h_score = int(g["homeTeam"].get("score", 0))
            a_score = int(g["awayTeam"].get("score", 0))
            
            log(f"מעבד משחק סופי: {g['awayTeam']['teamName']} נגד {g['homeTeam']['teamName']}")
            
            if h_score > a_score:
                win = translate_team(g["homeTeam"]["teamCity"], g["homeTeam"]["teamName"], h_score)
                lose = translate_team(g["awayTeam"]["teamCity"], g["awayTeam"]["teamName"], a_score)
            else:
                win = translate_team(g["awayTeam"]["teamCity"], g["awayTeam"]["teamName"], a_score)
                lose = translate_team(g["homeTeam"]["teamCity"], g["homeTeam"]["teamName"], h_score)

            msg += f"🏆 <b>{win}</b>\n🔹 {lose}\n\n"
            found = True

    if found:
        return msg
    else:
        log("לא נמצאו משחקים בסטטוס 3 (סופי)")
        return "🏀 <b>תוצאות משחקי הלילה ב NBA</b> 🏀\n\n🏁 לא נמצאו תוצאות סופיות לעדכון כרגע."

# ==========================================
# שליחה לטלגרם
# ==========================================
def send_to_telegram(text):
    if not text: return
    log(f"מנסה לשלוח הודעה לטלגרם (אורך: {len(text)})")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
        if r.status_code == 200: 
            log("ההודעה נשלחה בהצלחה!")
        else: 
            log(f"שגיאת טלגרם: {r.text}")
    except Exception as e: 
        log(f"שגיאה טכנית בשליחה: {e}")

# ==========================================
# לולאת הרצה (המנוע הראשי)
# ==========================================
def run():
    log("מערכת NBA BOT עלתה לאוויר - מצב ניטור פעיל")
    tz = pytz.timezone("Asia/Jerusalem")
    last_schedule_date = None
    last_results_date = None

    while True:
        try:
            now = datetime.now(tz)
            current_time = now.strftime("%H:%M")
            today = now.date()

            # בדיקת לו"ז
            if current_time == SCHEDULE_TIME and last_schedule_date != today:
                log(f"הגיע זמן שליחת לו"ז ({SCHEDULE_TIME})")
                games = get_games()
                msg = get_schedule_msg(games)
                send_to_telegram(msg)
                last_schedule_date = today
                log("עדכון תאריך לו"ז בוצע")
                time.sleep(65)

            # בדיקת תוצאות
            if current_time == RESULTS_TIME and last_results_date != today:
                log(f"הגיע זמן שליחת תוצאות ({RESULTS_TIME})")
                games = get_games()
                msg = get_results_msg(games)
                # תמיד שולח הודעה (גם אם זו הודעת 'אין תוצאות')
                send_to_telegram(msg)
                last_results_date = today
                log("עדכון תאריך תוצאות בוצע")
                time.sleep(65)

            time.sleep(30)
            
        except Exception as e:
            log(f"שגיאה בלולאה הראשית: {e}")
            time.sleep(20)

if __name__ == "__main__":
    run()

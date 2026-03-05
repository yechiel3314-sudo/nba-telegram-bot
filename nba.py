import requests
import time
import pytz
from datetime import datetime, date

# ==========================================
# הגדרות
# ==========================================

TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"

SCHEDULE_TIME = "16:44"   # לוח משחקים
RESULTS_TIME = "16:45"    # תוצאות בבוקר

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
    full = f"{city} {name}"
    base = TEAM_TRANSLATIONS.get(full, full)

    # דגל ישראל לפורטלנד וברוקלין
    if "Portland" in full or "Brooklyn" in full:
        if score is not None:
            return f"{base} {score} 🇮🇱"
        return f"{base} 🇮🇱"

    if score is not None:
        return f"{base} {score}"

    return base

# ==========================================
# המרת זמן לישראל
# ==========================================

def format_nba_time(time_str):
    try:
        utc_dt = datetime.strptime(
            time_str,
            "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=pytz.utc)

        israel = pytz.timezone("Asia/Jerusalem")
        local = utc_dt.astimezone(israel)

        return local.strftime("%H:%M")

    except:
        return "TBD"

# ==========================================
# שליפת משחקים
# ==========================================

def get_games():

    log("מבקש נתונים מה-API")

    try:
        resp = requests.get(NBA_URL, timeout=10)

        if resp.status_code != 200:
            log(f"שגיאת API: {resp.status_code}")
            return []

        data = resp.json()
        games = data.get("scoreboard", {}).get("games", [])

        log(f"נמצאו {len(games)} משחקים")
        return games

    except Exception as e:
        log(f"שגיאה בשליפת נתונים: {e}")
        return []

# ==========================================
# לוח משחקים
# ==========================================

def get_schedule_msg(games):

    log("בונה הודעת לוח משחקים")

    msg = "🏀 <b>לוח משחקי הלילה ב NBA</b> 🏀\n\n"
    found = False

    for g in games:

        # כל משחק שלא הסתיים
        if g["gameStatus"] in [1, 2]:

            home = translate_team(
                g["homeTeam"]["teamCity"],
                g["homeTeam"]["teamName"]
            )

            away = translate_team(
                g["awayTeam"]["teamCity"],
                g["awayTeam"]["teamName"]
            )

            start = format_nba_time(g["gameEt"])

            if g["gameStatus"] == 2:
                status = "🔥 חי עכשיו"
            else:
                status = f"⏰ {start}"

            msg += f"{status}\n🏀 {home} 🆚 {away}\n\n"
            found = True

    if not found:
        return None

    return msg

# ==========================================
# תוצאות
# ==========================================

def get_results_msg(games):

    log("בונה הודעת תוצאות")

    msg = "🏀 <b>תוצאות משחקי הלילה ב NBA</b> 🏀\n\n"
    found = False

    for g in games:

        if g["gameStatus"] == 3:

            h_score = int(g["homeTeam"]["score"])
            a_score = int(g["awayTeam"]["score"])

            if h_score > a_score:
                win = translate_team(
                    g["homeTeam"]["teamCity"],
                    g["homeTeam"]["teamName"],
                    h_score
                )
                lose = translate_team(
                    g["awayTeam"]["teamCity"],
                    g["awayTeam"]["teamName"],
                    a_score
                )
            else:
                win = translate_team(
                    g["awayTeam"]["teamCity"],
                    g["awayTeam"]["teamName"],
                    a_score
                )
                lose = translate_team(
                    g["homeTeam"]["teamCity"],
                    g["homeTeam"]["teamName"],
                    h_score
                )

            msg += f"🏆 <b>{win}</b>\n🔹 {lose}\n\n"
            found = True

    if not found:
        return None

    return msg

# ==========================================
# שליחה לטלגרם
# ==========================================

def send_to_telegram(text):

    if not text:
        log("אין תוכן לשליחה - מדלג")
        return

    log("שולח הודעה לטלגרם")

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }

    try:
        r = requests.post(url, data=payload, timeout=10)

        if r.status_code == 200:
            log("נשלח בהצלחה")
        else:
            log(f"שגיאת טלגרם {r.status_code}")

    except Exception as e:
        log(f"שגיאה בשליחה: {e}")

# ==========================================
# לולאה ראשית
# ==========================================

def run():

    log("NBA BOT STARTED")

    tz = pytz.timezone("Asia/Jerusalem")

    last_schedule_date = None
    last_results_date = None

    while True:

        now = datetime.now(tz)
        current_time = now.strftime("%H:%M")
        today = date.today()

        # שליחת לוח משחקים
        if current_time >= SCHEDULE_TIME and last_schedule_date != today:

            games = get_games()
            msg = get_schedule_msg(games)

            if msg:
                send_to_telegram(msg)
                last_schedule_date = today

        # שליחת תוצאות
        if current_time >= RESULTS_TIME and last_results_date != today:

            games = get_games()
            msg = get_results_msg(games)

            if msg:
                send_to_telegram(msg)
                last_results_date = today

        time.sleep(30)

# ==========================================
# הפעלה
# ==========================================

if __name__ == "__main__":
    run()

import requests
import time
import pytz
from datetime import datetime

# ==========================================
# הגדרות
# ==========================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"

SCHEDULE_TIME = "15:51"
RESULTS_TIME = "15:51"

# ==========================================
# תרגום קבוצות
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

# ==========================================
# פונקציות עזר
# ==========================================
def translate_team(city, name, score=None):

    full = f"{city} {name}"
    base = TEAM_TRANSLATIONS.get(full, full)

    if score is not None:
        return f"{base} {score}"

    return base


def format_nba_time(time_str):

    try:
        utc_dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)

        israel = pytz.timezone("Asia/Jerusalem")

        local = utc_dt.astimezone(israel)

        return local.strftime("%H:%M")

    except:
        return "TBD"


def get_games():

    try:

        resp = requests.get(NBA_URL, timeout=10).json()

        games = resp.get("scoreboard", {}).get("games", [])

        if not games:
            time.sleep(5)
            resp = requests.get(NBA_URL, timeout=10).json()
            games = resp.get("scoreboard", {}).get("games", [])

        return games

    except:

        return []


# ==========================================
# הודעות
# ==========================================
def get_schedule_msg(games):

    msg = "🏀 <b>לוח משחקי הלילה</b> 🏀\n\n"

    found = False

    for g in games:

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

            msg += f"⏰ <b>{start}</b>\n🏀 {home} 🆚 {away}\n\n"

            found = True

    if not found:

        msg += "אין משחקים מתוכננים."

    return msg


def get_results_msg(games):

    msg = "🏀 <b>תוצאות משחקי הלילה</b> 🏀\n\n"

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

        msg += "לא נמצאו תוצאות."

    return msg


# ==========================================
# טלגרם
# ==========================================
def send_to_telegram(text):

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }

    try:

        requests.post(url, data=payload, timeout=10)

    except:

        pass


# ==========================================
# לולאה ראשית
# ==========================================
def run():

    print("NBA BOT STARTED")

    sent_schedule = False
    sent_results = False

    tz = pytz.timezone("Asia/Jerusalem")

    while True:

        now = datetime.now(tz).strftime("%H:%M")

        if now == "00:00":

            sent_schedule = False
            sent_results = False

        if now >= SCHEDULE_TIME and not sent_schedule:

            games = get_games()

            msg = get_schedule_msg(games)

            send_to_telegram(msg)

            sent_schedule = True

        if now >= RESULTS_TIME and not sent_results:

            games = get_games()

            msg = get_results_msg(games)

            send_to_telegram(msg)

            sent_results = True

        time.sleep(20)


# ==========================================
# הפעלה
# ==========================================
if __name__ == "__main__":

    run()

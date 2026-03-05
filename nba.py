import requests
import time
import pytz
from datetime import datetime

# ==========================================
# הגדרות
# ==========================================

TELEGRAM_TOKEN = "PUT_YOUR_TOKEN_HERE"
CHAT_ID = "-1003808107418"

NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"

SCHEDULE_TIME = "15:55"
RESULTS_TIME = "15:55"

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
"Minnesota Timberwolves":"מינסוטה",
"New Orleans Pelicans":"ניו אורלינס",
"New York Knicks":"ניו יורק ניקס",
"Oklahoma City Thunder":"אוקלהומה סיטי",
"Orlando Magic":"אורלנדו",
"Philadelphia 76ers":"פילדלפיה",
"Phoenix Suns":"פיניקס",
"Portland Trail Blazers":"פורטלנד",
"Sacramento Kings":"סקרמנטו",
"San Antonio Spurs":"סן אנטוניו",
"Toronto Raptors":"טורונטו",
"Utah Jazz":"יוטה",
"Washington Wizards":"וושינגטון"
}

# ==========================================
# פונקציות עזר
# ==========================================

def translate_team(city,name,score=None):

    full=f"{city} {name}"
    base=TEAM_TRANSLATIONS.get(full,full)

    if score:
        return f"{base} {score}"

    return base


def format_time(utc_time):

    try:

        utc=datetime.strptime(utc_time,"%Y-%m-%dT%H:%M:%SZ")

        utc=utc.replace(tzinfo=pytz.utc)

        israel=pytz.timezone("Asia/Jerusalem")

        local=utc.astimezone(israel)

        return local.strftime("%H:%M")

    except:

        return "TBD"


def get_games():

    try:

        r=requests.get(NBA_URL,timeout=10)

        data=r.json()

        return data["scoreboard"]["games"]

    except:

        return []

# ==========================================
# הודעת לוח משחקים
# ==========================================

def schedule_message(games):

    msg="🏀 <b>לוח משחקי הלילה</b> 🏀\n\n"

    count=0

    for g in games:

        if g["gameStatus"]!=3:

            home=translate_team(
            g["homeTeam"]["teamCity"],
            g["homeTeam"]["teamName"])

            away=translate_team(
            g["awayTeam"]["teamCity"],
            g["awayTeam"]["teamName"])

            t=format_time(g["gameEt"])

            msg+=f"⏰ <b>{t}</b>\n🏀 {home} 🆚 {away}\n\n"

            count+=1

    if count==0:

        msg+="אין משחקים מתוכננים."

    return msg

# ==========================================
# הודעת תוצאות
# ==========================================

def results_message(games):

    msg="🏀 <b>תוצאות משחקי הלילה</b> 🏀\n\n"

    count=0

    for g in games:

        if g["gameStatus"]==3:

            h=int(g["homeTeam"]["score"])
            a=int(g["awayTeam"]["score"])

            if h>a:

                win=translate_team(
                g["homeTeam"]["teamCity"],
                g["homeTeam"]["teamName"],
                h)

                lose=translate_team(
                g["awayTeam"]["teamCity"],
                g["awayTeam"]["teamName"],
                a)

            else:

                win=translate_team(
                g["awayTeam"]["teamCity"],
                g["awayTeam"]["teamName"],
                a)

                lose=translate_team(
                g["homeTeam"]["teamCity"],
                g["homeTeam"]["teamName"],
                h)

            msg+=f"🏆 <b>{win}</b>\n🔹 {lose}\n\n"

            count+=1

    if count==0:

        msg+="אין תוצאות סופיות."

    return msg

# ==========================================
# טלגרם
# ==========================================

def send(text):

    url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    data={

    "chat_id":CHAT_ID,
    "text":text,
    "parse_mode":"HTML"

    }

    requests.post(url,data=data)

# ==========================================
# לולאה
# ==========================================

def run():

    print("NBA BOT STARTED")

    sent_schedule=False
    sent_results=False

    tz=pytz.timezone("Asia/Jerusalem")

    while True:

        now=datetime.now(tz).strftime("%H:%M")

        if now=="00:00":

            sent_schedule=False
            sent_results=False

        games=get_games()

        if now>=SCHEDULE_TIME and not sent_schedule:

            send(schedule_message(games))

            sent_schedule=True

        if now>=RESULTS_TIME and not sent_results:

            send(results_message(games))

            sent_results=True

        time.sleep(20)

if __name__=="__main__":

    run()

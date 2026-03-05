import requests
import time
import pytz
import logging
from datetime import datetime, timedelta

# ==============================================================================
# --- הגדרות מערכת וקונפיגורציה (NBA TELEGRAM BOT V17 - STABLE BUILD) ---
# ==============================================================================

TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# זמני שליחה
SCHEDULE_TIME_STR = "19:02"
RESULTS_TIME_STR = "19:03"

# המרת זמן לאובייקט זמן אמיתי
SCHEDULE_TIME = datetime.strptime(SCHEDULE_TIME_STR, "%H:%M").time()
RESULTS_TIME = datetime.strptime(RESULTS_TIME_STR, "%H:%M").time()

NBA_API_ENDPOINT = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

RTL_MARK = "\u200f"

# ==============================================================================
# --- מערכת לוגים מקצועית ---
# ==============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

# ==============================================================================
# --- מילון תרגום קבוצות NBA ---
# ==============================================================================

NBA_HEBREW_MAP = {
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
# --- פונקציות עזר ---
# ==============================================================================

def check_israeli_context(team_en):

    israeli_teams = [
        "Brooklyn Nets",
        "Portland Trail Blazers"
    ]

    if team_en in israeli_teams:
        return " 🇮🇱"

    return ""


def translate_team(team_en):

    heb = NBA_HEBREW_MAP.get(team_en, team_en)

    return heb


def format_team_line(team_en, score=None):

    name = translate_team(team_en)
    flag = check_israeli_context(team_en)

    if score is not None:
        return f"{name} - {score}{flag}"

    return f"{name}{flag}"


# ==============================================================================
# --- שליפת נתונים מ ESPN ---
# ==============================================================================

def fetch_espn_games():

    try:

        cache_buster = int(time.time())

        url = f"{NBA_API_ENDPOINT}?_={cache_buster}"

        response = requests.get(url, timeout=25)

        if response.status_code != 200:

            logger.error(f"API ERROR {response.status_code}")

            return []

        data = response.json()

        events = data.get("events", [])

        games = []

        for event in events:

            comp = event["competitions"][0]

            home = next(t for t in comp["competitors"] if t["homeAway"] == "home")
            away = next(t for t in comp["competitors"] if t["homeAway"] == "away")

            utc_time = event["date"]

            try:

                utc_dt = datetime.fromisoformat(utc_time.replace("Z", "+00:00"))

            except:

                utc_dt = datetime.strptime(
                    utc_time.replace("Z", ""),
                    "%Y-%m-%dT%H:%M"
                ).replace(tzinfo=pytz.utc)

            games.append({

                "status": event["status"]["type"]["id"],

                "utc_time": utc_dt,

                "home": home["team"]["displayName"],

                "away": away["team"]["displayName"],

                "home_score": home["score"],

                "away_score": away["score"]

            })

        return games

    except Exception as e:

        logger.error(f"DATA FETCH FAILED: {e}")

        return []


# ==============================================================================
# --- בניית הודעת לוז ---
# ==============================================================================

def build_schedule_message(games):

    tz = pytz.timezone("Asia/Jerusalem")

    now = datetime.now(tz)

    header = f"{RTL_MARK}🏀 ══ <b>לוז משחקי הלילה ב NBA</b> ══ 🏀\n\n"

    body = ""

    found = False

    for g in games:

        local_time = g["utc_time"].astimezone(tz)

        if now <= local_time <= now + timedelta(hours=24):

            time_str = local_time.strftime("%H:%M")

            home = format_team_line(g["home"])
            away = format_team_line(g["away"])

            body += f"{RTL_MARK}⏰ <b>{time_str}</b>\n"
            body += f"{RTL_MARK}🏀 {away} 🆚 {home}\n\n"

            found = True

    if not found:

        body = "לא נמצאו משחקים ב־24 השעות הקרובות."

    return header + body


# ==============================================================================
# --- בניית הודעת תוצאות ---
# ==============================================================================

def build_results_message(games):

    header = f"{RTL_MARK}🏁 ══ <b>סיכום תוצאות הלילה</b> ══ 🏁\n\n"

    body = ""

    found = False

    for g in games:

        if str(g["status"]) in ["3", "STATUS_FINAL"]:

            home_score = int(g["home_score"])
            away_score = int(g["away_score"])

            if home_score > away_score:

                winner = format_team_line(g["home"], home_score)
                loser = format_team_line(g["away"], away_score)

            else:

                winner = format_team_line(g["away"], away_score)
                loser = format_team_line(g["home"], home_score)

            body += f"{RTL_MARK}🏆 <b>{winner}</b>\n"
            body += f"{RTL_MARK}🏀 {loser}\n\n"

            found = True

    if not found:

        body = "אין עדיין תוצאות סופיות למשחקים."

    return header + body


# ==============================================================================
# --- שליחה לטלגרם ---
# ==============================================================================

def send_telegram(message):

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {

        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True

    }

    try:

        r = requests.post(url, json=payload, timeout=20)

        if r.status_code == 200:

            logger.info("MESSAGE SENT")

            return True

        logger.error(f"TELEGRAM ERROR {r.text}")

        return False

    except Exception as e:

        logger.error(f"TELEGRAM FAILED {e}")

        return False


# ==============================================================================
# --- מנוע הבוט הראשי ---
# ==============================================================================

def run_bot():

    logger.info("NBA BOT STARTED")

    tz = pytz.timezone("Asia/Jerusalem")

    last_schedule_day = None
    last_results_day = None

    while True:

        try:

            now = datetime.now(tz)

            today = now.date()

            logger.info(f"CHECK LOOP {now.strftime('%H:%M:%S')}")

            # --------------------------------------------------
            # שליחת לוז
            # --------------------------------------------------

            if now.time() >= SCHEDULE_TIME and last_schedule_day != today:

                logger.info("TRY SEND SCHEDULE")

                games = fetch_espn_games()

                msg = build_schedule_message(games)

                if send_telegram(msg):

                    last_schedule_day = today

                    logger.info("SCHEDULE SENT")

            # --------------------------------------------------
            # שליחת תוצאות
            # --------------------------------------------------

            if now.time() >= RESULTS_TIME and last_results_day != today:

                logger.info("TRY SEND RESULTS")

                games = fetch_espn_games()

                msg = build_results_message(games)

                if send_telegram(msg):

                    last_results_day = today

                    logger.info("RESULTS SENT")

            time.sleep(30)

        except Exception as e:

            logger.critical(f"MAIN LOOP ERROR {e}")

            time.sleep(60)


# ==============================================================================
# --- START BOT ---
# ==============================================================================

if __name__ == "__main__":

    run_bot()

# ==============================================================================
# --- END FILE ---
# ==============================================================================

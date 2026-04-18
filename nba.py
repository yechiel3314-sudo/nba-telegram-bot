import os
import json
import time
import pytz
import requests
from datetime import datetime

# ==========================================
# הגדרות
# ==========================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE")
CHAT_ID = os.getenv("CHAT_ID", "-1003808107418")

# ה-API המרכזי לתוצאות חיות
NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"

RESULTS_TIME = "09:00"    # זמן שליחת התוצאות
STATE_FILE = "nba_results_state.json"

# ==========================================
# לוג
# ==========================================

def log(msg):
    tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(tz).strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

# ==========================================
# שמירת מצב
# ==========================================

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data.setdefault("last_results_date", None)
                    data.setdefault("pending_results", None)
                    return data
        except Exception as e:
            log(f"שגיאה בטעינת state: {e}")
    return {
        "last_results_date": None,
        "pending_results": None
    }

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"שגיאה בשמירת state: {e}")

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
    "Golden State Warriors":"גולדן סטייט ווריורס",
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
    "Oklahoma City Thunder":"אוקלהומה סיטי ת'אנדר",
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
    full = f"{city} {name}" if name else city
    base = TEAM_TRANSLATIONS.get(full, full)

    is_special = "Portland" in full or "Brooklyn" in full
    flag = " 🇮🇱" if is_special else ""

    if score is not None:
        return f"{base} {score}{flag}"
    return f"{base}{flag}"

# ==========================================
# שבת / חג
# ==========================================

def is_shabbat_or_yom_tov():
    """
    מחזיר True בזמן שבת/יום טוב.
    חול המועד לא אמור להיחסם.
    """
    try:
        tz = pytz.timezone("Asia/Jerusalem")
        now = datetime.now(tz)

        url = (
            "https://www.hebcal.com/zmanim"
            "?cfg=json&im=1&latitude=31.778&longitude=35.235&tzid=Asia/Jerusalem"
        )
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            return False

        data = resp.json()
        status = data.get("status", {})
        return bool(status.get("isAssurBemlacha"))
    except Exception as e:
        log(f"שגיאה בבדיקת שבת/חג: {e}")
        return False

# ==========================================
# שליפת משחקים
# ==========================================

def get_games():
    log("מבקש נתונים מה-API לצורך תוצאות")
    try:
        resp = requests.get(f"{NBA_URL}?cache={int(time.time())}", timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            games = data.get("scoreboard", {}).get("games", [])
            return games
    except Exception as e:
        log(f"שגיאה קריטית בשליפה: {e}")
    return []

# ==========================================
# בניית הודעת תוצאות
# ==========================================

def get_results_msg(games):
    log("בונה הודעת תוצאות")
    msg = "🏀 <b>תוצאות משחקי הלילה ב NBA</b> 🏀\n\n"
    found = False

    if not games:
        return None

    for g in games:
        if g.get("gameStatus") == 3:
            try:
                h_score = int(g["homeTeam"]["score"])
                a_score = int(g["awayTeam"]["score"])
            except Exception:
                continue

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

    return msg if found else None

# ==========================================
# שליחה לטלגרם
# ==========================================

def send_to_telegram(text):
    if not text:
        return False

    log("שולח הודעה לטלגרם")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML"
            },
            timeout=15
        )
        if r.status_code == 200:
            log("נשלח בהצלחה")
            return True
        else:
            log(f"שגיאת טלגרם: {r.text}")
            return False
    except Exception as e:
        log(f"שגיאה בשליחה: {e}")
        return False

# ==========================================
# שליחה מושהית
# ==========================================

def try_send_pending(state, today):
    pending = state.get("pending_results")
    if not pending:
        return

    pending_date = pending.get("date")
    pending_msg = pending.get("message")

    # שולחים ברגע שמותר, גם אם עבר יום
    if pending_msg:
        ok = send_to_telegram(pending_msg)
        if ok:
            state["last_results_date"] = pending_date or str(today)
            state["pending_results"] = None
            save_state(state)
            log(f"הודעת תוצאות מושהית נשלחה עבור {pending_date or today}")

# ==========================================
# לולאה ראשית
# ==========================================

def run():
    log("NBA RESULTS BOT STARTED - RESULTS ONLY MODE")
    tz = pytz.timezone("Asia/Jerusalem")
    state = load_state()

    while True:
        try:
            now = datetime.now(tz)
            current_time = now.strftime("%H:%M")
            today = str(now.date())

            blocked_now = is_shabbat_or_yom_tov()

            # אם יש הודעה מושהית והיא מותרת כעת - שולחים
            if not blocked_now and state.get("pending_results"):
                try_send_pending(state, today)
                state = load_state()

            # שליחה יומית בשעה 09:00
            if current_time == RESULTS_TIME and state.get("last_results_date") != today:
                games = get_games()
                msg = get_results_msg(games)

                if msg:
                    if blocked_now:
                        log("שבת/יום טוב פעיל - שומר את הודעת התוצאות לשליחה מאוחרת")
                        state["pending_results"] = {
                            "date": today,
                            "message": msg
                        }
                        state["last_results_date"] = today
                        save_state(state)
                    else:
                        ok = send_to_telegram(msg)
                        if ok:
                            state["last_results_date"] = today
                            save_state(state)
                            log(f"הודעת תוצאות יומית הושלמה עבור {today}")
                else:
                    log("לא נמצאו משחקים שהסתיימו לשליחה")
                    state["last_results_date"] = today
                    save_state(state)

                time.sleep(65)  # מניעת כפילויות בתוך אותה דקה

        except Exception as e:
            log(f"שגיאה בלולאה הראשית: {e}")

        time.sleep(30)

if __name__ == "__main__":
    run()

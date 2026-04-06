import requests
import time
import pytz
import logging
from datetime import datetime, timedelta
import json
import os

# ==========================================
# הגדרות מערכת
# ==========================================

TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dp9rM_1rGGlpske3OxTJrE"
CHAT_ID = "-1003808107418"

SCHEDULE_TIME = "16:41"  # זמן שליחת לוח המשחקים
NBA_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

STATE_FILE = "nba_schedule_state.json"

# ==========================================
# לוג
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def log(msg):
    tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(tz).strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

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
    "Philadelphia 76ers": "פילדלפיה 76רס",
    "Phoenix Suns": "פיניקס סאנס",
    "Portland Trail Blazers": "פורטלנד טרייל בלייזרס",
    "Sacramento Kings": "סקרמנטו קינגס",
    "San Antonio Spurs": "סן אנטוניו ספרס",
    "Toronto Raptors": "טורונטו ראפטורס",
    "Utah Jazz": "יוטה ג'אז",
    "Washington Wizards": "וושינגטון וויזארדס"
}

def translate_team(city, name, score=None):
    full = f"{city} {name}".strip() if name else city.strip()
    base = TEAM_TRANSLATIONS.get(full, full)

    is_special = "Portland" in full or "Brooklyn" in full
    flag = " 🇮🇱" if is_special else ""

    if score is not None:
        return f"{base} {score}{flag}"
    return f"{base}{flag}"

# ==========================================
# שמירת מצב יומי
# ==========================================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"שגיאה בטעינת state: {e}")
        return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"שגיאה בשמירת state: {e}")

# ==========================================
# שליפת משחקים
# ==========================================

def get_games():
    log("מבקש נתונים מה-API לצורך לוח משחקים")
    try:
        resp = requests.get(f"{NBA_URL}?cache={int(time.time())}", timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            games = data.get("events", [])
            return games
        else:
            log(f"שגיאה בשליפה: {resp.status_code} | {resp.text}")
    except Exception as e:
        log(f"שגיאה קריטית בשליפה: {e}")
    return []

# ==========================================
# עזר לניתוח תאריך ESPN
# ==========================================

def parse_espn_datetime(dt_str):
    """
    תומך בפורמטים נפוצים של ESPN:
    2026-04-06T22:30Z
    2026-04-06T22:30:00Z
    2026-04-06T22:30:00.000Z
    """
    if not dt_str:
        return None

    try:
        clean = dt_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        return dt
    except Exception:
        return None

# ==========================================
# בניית הודעת לוח משחקים
# ==========================================

def get_schedule_msg(games):
    log("בונה הודעת לוח משחקים")
    if not games:
        return None

    tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(tz)

    msg = "🏀 <b>לוח משחקי הלילה ב NBA</b> 🏀\n\n"
    found = False

    for g in games:
        try:
            competitions = g.get("competitions", [])
            if not competitions:
                continue

            comp = competitions[0]
            competitors = comp.get("competitors", [])
            if len(competitors) < 2:
                continue

            home = next((t for t in competitors if t.get("homeAway") == "home"), None)
            away = next((t for t in competitors if t.get("homeAway") == "away"), None)
            if not home or not away:
                continue

            game_dt = parse_espn_datetime(g.get("date"))
            if not game_dt:
                continue

            if game_dt.tzinfo is None:
                game_dt = pytz.utc.localize(game_dt)

            local_dt = game_dt.astimezone(tz)

            # מציג רק משחקים ב-24 השעות הקרובות
            if now <= local_dt <= now + timedelta(hours=24):
                time_str = local_dt.strftime("%H:%M")
                away_name = away["team"]["displayName"]
                home_name = home["team"]["displayName"]

                msg += f"⏰ <b>{time_str}</b>\n"
                msg += f"🏀 {translate_team(*split_team_name(away_name))} 🆚 {translate_team(*split_team_name(home_name))}\n\n"
                found = True

        except Exception as e:
            log(f"שגיאה בבניית משחק: {e}")

    return msg if found else None

# ==========================================
# פיצול שם קבוצה לצורך translate_team
# ==========================================

def split_team_name(full_name):
    """
    ESPN מחזיר displayName כמו:
    Brooklyn Nets
    Los Angeles Lakers
    ולכן אנחנו משתמשים בשם המלא ב-city,
    ונותנים name ריק כדי לשמור תאימות למבנה שלך.
    """
    return full_name, ""

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
# לולאה ראשית
# ==========================================

def run():
    log("NBA SCHEDULE BOT STARTED - SCHEDULE ONLY MODE")
    tz = pytz.timezone("Asia/Jerusalem")
    last_sent_date = None
    state = load_state()
    if "last_sent_date" in state:
        last_sent_date = datetime.strptime(state["last_sent_date"], "%Y-%m-%d").date()

    while True:
        now = datetime.now(tz)
        current_time = now.strftime("%H:%M")
        today = now.date()

        # בדיקה אם הגיעה השעה לשלוח ואם עדיין לא שלחנו היום
        if current_time == SCHEDULE_TIME and last_sent_date != today:
            games = get_games()
            msg = get_schedule_msg(games)

            if msg:
                send_to_telegram(msg)
                last_sent_date = today
                state["last_sent_date"] = today.strftime("%Y-%m-%d")
                save_state(state)
                log(f"הודעת לוח יומית הושלמה עבור {today}")
            else:
                log("לא נמצאו משחקים להצגה")
                last_sent_date = today
                state["last_sent_date"] = today.strftime("%Y-%m-%d")
                save_state(state)

            time.sleep(65)  # מונע כפילויות בתוך אותה דקה

        time.sleep(30)

if __name__ == "__main__":
    run()

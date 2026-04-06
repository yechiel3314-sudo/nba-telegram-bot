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

SCHEDULE_TIME = "17:00"  # זמן שליחת לוח המשחקים
ESPN_API_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
NBA_URL = ESPN_API_URL  # נשאר על אותו מקור נתונים, רק מגדירים את השם שהיה חסר
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
    schedule = []
    try:
        resp = requests.get(f"{ESPN_API_URL}?t={int(time.time())}", timeout=15)
        if resp.status_code == 200:
            events = resp.json().get('events', [])

            for ev in events:
                comp = ev['competitions'][0]
                home = next(t for t in comp['competitors'] if t['homeAway'] == 'home')
                away = next(t for t in comp['competitors'] if t['homeAway'] == 'away')

                schedule.append({
                    "id": ev['status']['type']['id'],
                    "time": ev['date'],
                    "home": home['team']['displayName'],
                    "away": away['team']['displayName']
                })
        else:
            log(f"שגיאה בשליפה: {resp.status_code}")
    except Exception as e:
        log(f"שגיאה קריטית בשליפה: {e}")

    return schedule
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
# בניית הודעת לוח משחקים
# ==========================================

def get_schedule_msg(data):
    tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(tz)

    msg = "🏀 <b>לוח משחקי הלילה ב NBA</b> 🏀\n\n"
    found = False

    for g in data:
        try:
            utc_dt = datetime.strptime(g['time'].replace('Z', ''), "%Y-%m-%dT%H:%M").replace(tzinfo=pytz.utc)
            local_dt = utc_dt.astimezone(tz)

            if g['id'] in ["1", "2"] and now <= local_dt <= now + timedelta(hours=24):
                time_str = local_dt.strftime("%H:%M")

                msg += f"⏰ <b>{time_str}</b>\n"
                msg += f"🏀 {translate_team(g['away'], '')} 🆚 {translate_team(g['home'], '')}\n\n"

                found = True

        except Exception as e:
            log(f"שגיאה במשחק: {e}")

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
# לולאה ראשית
# ==========================================

def run():
    log("NBA SCHEDULE BOT STARTED - SCHEDULE ONLY MODE")
    tz = pytz.timezone("Asia/Jerusalem")
    last_sent_date = None

    state = load_state()
    if "last_sent_date" in state:
        try:
            last_sent_date = datetime.strptime(state["last_sent_date"], "%Y-%m-%d").date()
        except Exception:
            last_sent_date = None

    target_hh, target_mm = map(int, SCHEDULE_TIME.split(":"))

    while True:
        try:
            now = datetime.now(tz)
            today = now.date()

            target_dt = tz.localize(datetime(now.year, now.month, now.day, target_hh, target_mm, 0))

            # חלון של דקה אחת סביב השעה המתוכננת
            in_send_window = target_dt <= now < (target_dt + timedelta(minutes=1))

            if in_send_window and last_sent_date != today:
                games = get_games()
                msg = get_schedule_msg(games)

                if msg:
                    send_to_telegram(msg)
                    log(f"הודעת לוח יומית הושלמה עבור {today}")
                else:
                    log("לא נמצאו משחקים להצגה")
                    log(f"מסומן כמעובד עבור {today} גם בלי משחקים")

                last_sent_date = today
                state["last_sent_date"] = today.strftime("%Y-%m-%d")
                save_state(state)

                time.sleep(65)  # מונע כפילויות בתוך אותה דקה

            time.sleep(30)

        except Exception as e:
            log(f"שגיאה בלולאה הראשית: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run()

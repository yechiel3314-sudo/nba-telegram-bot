import os
import json
import time
import html
import requests
from datetime import datetime, timedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==============================
# הגדרות טלגרם
# ==============================
TELEGRAM_TOKEN = "8996455073:AAHXYXjy2T12CzBi-IqramkUSWQ4rDSI6ss"
CHAT_ID = "-1003808107418"

# ==============================
# ESPN NBA SCOREBOARD
# ==============================
NBA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
RTL = "\u200f"
STATE_FILE = "nba_clutch_state.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}

def build_session():
    session = requests.Session()
    session.headers.update(HEADERS)

    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )

    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

SESSION = build_session()

# ==============================
# תרגום שמות קבוצות
# ==============================
TEAM_FIXES = {
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
    "Los Angeles Clippers": "לוס אנג'לס קליפרס",
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
    "Washington Wizards": "וושינגטון וויזארדס",
}

sent_clutch = {}
sent_last45 = {}

# ==============================
# כלים כלליים
# ==============================
def now_iso():
    return datetime.now().isoformat(timespec="seconds")

def tr_name(text: str) -> str:
    return TEAM_FIXES.get(text, text)

def was_sent(store: dict, game_id: str) -> bool:
    return bool(store.get(str(game_id)))

def mark_sent(store: dict, game_id: str):
    store[str(game_id)] = now_iso()

def clock_to_seconds(clock: str):
    try:
        if not clock or ":" not in clock:
            return None

        mm, ss = clock.split(":", 1)
        return int(mm) * 60 + int(float(ss))

    except (TypeError, ValueError):
        return None

def get_competitors(event: dict):
    competition = event.get("competitions", [{}])[0]
    competitors = competition.get("competitors", [])

    if len(competitors) < 2:
        return None, None

    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)

    if away is None or home is None:
        away = competitors[0]
        home = competitors[1]

    return away, home

# ==============================
# שמירת מצב
# ==============================
def load_state():
    global sent_clutch, sent_last45

    if not os.path.exists(STATE_FILE):
        sent_clutch = {}
        sent_last45 = {}
        return

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            sent_clutch = data.get("sent_clutch", {}) or {}
            sent_last45 = data.get("sent_last45", {}) or {}
        else:
            sent_clutch = {}
            sent_last45 = {}

    except Exception as e:
        print(f"❌ שגיאה בטעינת state: {e}")
        sent_clutch = {}
        sent_last45 = {}

def save_state():
    try:
        tmp_file = STATE_FILE + ".tmp"

        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "sent_clutch": sent_clutch,
                    "sent_last45": sent_last45,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_file, STATE_FILE)

    except OSError as e:
        print(f"❌ שגיאה בשמירת state: {e}")

def cleanup_old_state(days=14):
    cutoff = datetime.now() - timedelta(days=days)

    def clean_store(store: dict):
        for game_id in list(store.keys()):
            value = store.get(game_id)

            if value is True:
                continue

            try:
                created_at = datetime.fromisoformat(str(value))
                if created_at < cutoff:
                    del store[game_id]
            except Exception:
                continue

    clean_store(sent_clutch)
    clean_store(sent_last45)
    save_state()

# ==============================
# טלגרם
# ==============================
def send_telegram_message(message: str):
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "שים_כאן_את_הטוקן_שלך":
        print("❌ חסר TELEGRAM_TOKEN בקוד")
        return False

    if not CHAT_ID:
        print("❌ חסר CHAT_ID בקוד")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    safe_message = html.escape(message)
    safe_message = safe_message.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")

    payload = {
        "chat_id": CHAT_ID,
        "text": safe_message[:4096],
        "parse_mode": "HTML",
    }

    try:
        response = SESSION.post(url, json=payload, timeout=15)

        if response.status_code == 200:
            print("✅ הודעה נשלחה בהצלחה לטלגרם")
            return True

        print(f"❌ שגיאה בשליחה לטלגרם: {response.status_code}")
        print(response.text)
        return False

    except requests.RequestException as e:
        print(f"❌ שגיאה בשליחה לטלגרם: {e}")
        return False

# ==============================
# שבת / חג
# ==============================
ISRAEL_LAT = 31.778
ISRAEL_LON = 35.235
ISRAEL_TZID = "Asia/Jerusalem"

def is_shabbat_or_yom_tov():
    try:
        url = (
            "https://www.hebcal.com/zmanim"
            f"?cfg=json&im=1&latitude={ISRAEL_LAT}&longitude={ISRAEL_LON}&tzid={ISRAEL_TZID}"
        )

        resp = SESSION.get(url, timeout=10)

        if resp.status_code != 200:
            print(f"⚠️ בדיקת שבת/חג נכשלה: status {resp.status_code}")
            return True

        data = resp.json()
        return bool((data.get("status") or {}).get("isAssurBemlacha"))

    except Exception as e:
        print(f"❌ שגיאה בבדיקת שבת/חג: {e}")
        return True

# ==============================
# בניית הודעות
# ==============================
def build_message(event: dict, alert_type: str):
    status = event.get("status", {})
    status_type = status.get("type", {})

    if status_type.get("state") != "in":
        return None

    clock = status.get("displayClock", "")

    away, home = get_competitors(event)
    if not away or not home:
        return None

    try:
        away_name = tr_name(away["team"]["displayName"])
        home_name = tr_name(home["team"]["displayName"])
        away_score = int(away["score"])
        home_score = int(home["score"])

    except (KeyError, TypeError, ValueError):
        return None

    if away_score > home_score:
        leader_name = away_name
        score_line = f"{away_score} - {home_score}"
    elif home_score > away_score:
        leader_name = home_name
        score_line = f"{home_score} - {away_score}"
    else:
        leader_name = "שוויון"
        score_line = f"{away_score} - {home_score}"

    if alert_type == "last45":
        title = "🚨 <b>התראת קלאץ' - 45 שניות אחרונות!</b> 🚨"
        ending = "⏳ <b>כל מהלך עכשיו מכריע!</b> ⏳"
    else:
        title = "🚨 <b>התראת קלאץ'!</b> 🚨"
        ending = "✨ <b>הכל יכול להתהפך עכשיו!</b> ✨"

    msg = ""
    msg += f"{RTL}{title}\n\n"
    msg += f"{RTL}🏀 <b>{away_name} 🆚 {home_name}</b> 🏀\n\n"

    if leader_name == "שוויון":
        msg += f"{RTL}🔥 <b>שוויון {score_line}</b> 🔥\n\n"
    else:
        msg += f"{RTL}🔥 <b>{leader_name} מובילה {score_line}</b> 🔥\n\n"

    msg += f"{RTL}⏱️ <b>זמן לסיום:</b> {clock}\n\n"
    msg += f"{RTL}{ending}"

    return msg

# ==============================
# בדיקת התראות
# ==============================
def check_all_nba_clutch():
    try:
        resp = SESSION.get(NBA_SCOREBOARD, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        blocked_now = is_shabbat_or_yom_tov()

        for event in data.get("events", []):
            status = event.get("status", {})
            status_type = status.get("type", {})

            if status_type.get("state") != "in":
                continue

            game_id = str(event.get("id") or "")
            period = status.get("period", 0)
            clock = status.get("displayClock", "")

            if not game_id:
                continue

            try:
                period = int(period or 0)
            except (TypeError, ValueError):
                continue

            clock_seconds = clock_to_seconds(clock)
            if clock_seconds is None:
                continue

            away, home = get_competitors(event)
            if not away or not home:
                continue

            try:
                away_score = int(away["score"])
                home_score = int(home["score"])
            except (KeyError, TypeError, ValueError):
                continue

            diff = abs(away_score - home_score)

            is_clutch_window = period >= 4 and diff <= 3 and clock_seconds <= 210
            is_last45_window = period >= 4 and diff <= 3 and clock_seconds <= 45

            if not is_clutch_window:
                continue

            # שבת/חג: לא שולחים ולא שומרים הודעות למוצאי שבת.
            if blocked_now:
                if is_clutch_window:
                    mark_sent(sent_clutch, game_id)
                if is_last45_window:
                    mark_sent(sent_last45, game_id)
                save_state()
                continue

            # 45 שניות אחרונות: עדיפות גבוהה.
            # אם הבוט נדלק ישר בתוך 45 שניות, לא נשלח אחר כך גם קלאץ' רגיל.
            if is_last45_window and not was_sent(sent_last45, game_id):
                msg = build_message(event, "last45")

                if msg and send_telegram_message(msg):
                    mark_sent(sent_last45, game_id)
                    mark_sent(sent_clutch, game_id)
                    save_state()
                    time.sleep(1)

                continue

            # קלאץ' רגיל: 3:30 דקות אחרונות.
            if not was_sent(sent_clutch, game_id):
                msg = build_message(event, "clutch")

                if msg and send_telegram_message(msg):
                    mark_sent(sent_clutch, game_id)
                    save_state()
                    time.sleep(1)

    except requests.RequestException as e:
        print(f"❌ שגיאת רשת כללית: {e}")
    except ValueError as e:
        print(f"❌ JSON לא תקין: {e}")
    except Exception as e:
        print(f"❌ שגיאה כללית: {e}")

# ==============================
# לולאה ראשית
# ==============================
if __name__ == "__main__":
    print("🚀 בוט התראות קלאץ' התחיל לעבוד...")
    load_state()
    cleanup_old_state()

    while True:
        try:
            check_all_nba_clutch()
        except Exception as e:
            print(f"❌ שגיאה בלולאה הראשית: {e}")

        time.sleep(5)

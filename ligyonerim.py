import os
import re
import json
import time
import logging
import html
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==========================================
# הגדרות
# ==========================================
TOKEN = os.getenv("TELEGRAM_TOKEN", "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE")
CHAT_ID = os.getenv("CHAT_ID", "-1003808107418")
STATE_FILE = "nba_israeli_state.json"

MESSAGE_DELAY_SECONDS = 20
POLL_SECONDS = 20

PLAYER_HEBREW_NAMES = {
    "Deni Avdija": "דני אבדיה",
    "Ben Saraf": "בן שרף",
    "Danny Wolf": "דני וולף",
}

PLAYER_IMAGES = {
    "Danny Wolf": "https://pbs.twimg.com/media/HCXLU3mbAAAd_Ma?format=jpg&name=small",
    "Ben Saraf": "https://pbs.twimg.com/media/HET8BYNXMAAI9zl?format=jpg&name=small",
    "Deni Avdija": "https://cdn.nba.com/teams/uploads/sites/1610612757/2026/02/GettyImages-2261442744.jpg",
}

ISRAELI_PLAYERS = set(PLAYER_HEBREW_NAMES.keys())

TEAM_HEBREW = {
    "ATL": "אטלנטה הוקס",
    "BOS": "בוסטון סלטיקס",
    "BKN": "ברוקלין נטס",
    "CHA": "שארלוט הורנטס",
    "CHI": "שיקגו בולס",
    "CLE": "קליבלנד קאבלירס",
    "DAL": "דאלאס מאבריקס",
    "DEN": "דנבר נאגטס",
    "DET": "דטרויט פיסטונס",
    "GSW": "גולדן סטייט ווריורס",
    "HOU": "יוסטון רוקטס",
    "IND": "אינדיאנה פייסרס",
    "LAC": "לוס אנג'לס קליפרס",
    "LAL": "לוס אנג'לס לייקרס",
    "MEM": "ממפיס גריזליס",
    "MIA": "מיאמי היט",
    "MIL": "מילווקי באקס",
    "MIN": "מינסוטה טימברוולבס",
    "NOP": "ניו אורלינס פליקנס",
    "NYK": "ניו יורק ניקס",
    "OKC": "אוקלהומה סיטי ת'אנדר",
    "ORL": "אורלנדו מג'יק",
    "PHI": "פילדלפיה סבנטי סיקסרס",
    "PHX": "פיניקס סאנס",
    "POR": "פורטלנד טרייל בלייזרס",
    "SAC": "סקרמנטו קינגס",
    "SAS": "סן אנטוניו ספרס",
    "TOR": "טורונטו ראפטורס",
    "UTA": "יוטה ג'אז",
    "WAS": "וושינגטון וויזארדס",
}

SB_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
BOX_URL = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

RLM = "\u200F"  # Right-to-left mark


# ==========================================
# SESSION / HTTP
# ==========================================
def build_session():
    s = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


SESSION = build_session()


def get_json(url):
    try:
        r = SESSION.get(url, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logging.error(f"GET JSON failed: {url} | {e}")
        return None


# ==========================================
# STATE
# ==========================================
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "games" in data:
                    return data
        except Exception as e:
            logging.error(f"Failed loading state: {e}")
    return {"games": {}}


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Failed saving state: {e}")


# ==========================================
# FORMATTERS
# ==========================================
def format_minutes_seconds(raw):
    """
    Converts NBA duration strings like:
    PT33M29.00S -> 33:29
    PT5M2.00S   -> 05:02
    PT12M       -> 12:00
    """
    if not raw:
        return "00:00"

    s = str(raw).strip()
    m = re.match(r"^PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$", s)
    if not m:
        return "00:00"

    mins = int(m.group(1) or 0)
    secs = float(m.group(2) or 0)
    secs_int = int(round(secs))

    if secs_int >= 60:
        mins += secs_int // 60
        secs_int = secs_int % 60

    return f"{mins:02}:{secs_int:02}"


def format_plus_minus(raw):
    try:
        v = float(raw or 0)
    except (TypeError, ValueError):
        return "0"

    if v == 0:
        return "0"
    if v.is_integer():
        return f"{int(v):+}"
    return f"{v:+.1f}".rstrip("0").rstrip(".")


def is_played(mins_raw):
    return format_minutes_seconds(mins_raw) != "00:00"


def rtl(text):
    return f"{RLM}{text}{RLM}"


def esc(text):
    return html.escape("" if text is None else str(text))


def normalize_not_playing_reason(text):
    t = (text or "").lower()

    if "rest" in t or "load" in t or "manage" in t:
        return "מנוחה"
    if "coach" in t or "decision" in t:
        return "החלטת מאמן"
    if "injur" in t:
        return "פציעה"
    if "ill" in t:
        return "מחלה"
    if "susp" in t:
        return "הרחקה"

    return text


def get_play_status(player):
    """
    מחזיר:
    played_bool, reason_text
    """
    status = str(player.get("status") or "").upper()
    played_raw = player.get("played")
    mins_raw = (player.get("statistics") or {}).get("minutesCalculated")

    not_playing_reason = str(player.get("notPlayingReason") or "").strip()
    not_playing_desc = str(player.get("notPlayingDescription") or "").strip()
    reason_text = normalize_not_playing_reason(not_playing_desc or not_playing_reason)

    if played_raw is not None:
        played_bool = str(played_raw).strip().lower() in ("1", "true", "yes", "y")
        return played_bool, reason_text

    # fallback אם השדה played לא קיים
    played_bool = is_played(mins_raw)

    # אם אין דקות בכלל והסטטוס לא ACTIVE, נחשיב כלא שיחק
    if not played_bool and status != "ACTIVE":
        return False, reason_text

    return played_bool, reason_text


# ==========================================
# MESSAGE BUILDER
# ==========================================
def build_msg(player, stage_text, game_info):
    full = f"{player.get('firstName', '')} {player.get('familyName', '')}".strip()

    # בדיקה ראשונית: אם לא שיחק והמנוחה/פציעה, אין הודעה
    played, rest_reason = get_play_status(player)
    if not played and rest_reason in ("פציעה", "מנוחה", "מחלה", "החלטת מאמן", "הרחקה"):
        return None  # לא שולחים הודעה

    stats = player.get("statistics") or {}
    mins_raw = stats.get("minutesCalculated")

    name_he = PLAYER_HEBREW_NAMES.get(full, full)
    away_he = TEAM_HEBREW.get(game_info["away"], game_info["away"])
    home_he = TEAM_HEBREW.get(game_info["home"], game_info["home"])

    lines = [
        rtl(f"🇮🇱 <b>לגיונרים: {esc(name_he)}</b> 🇮🇱"),
        "",
        rtl(f"🏀 <b>{esc(away_he)} 🆚 {esc(home_he)}</b> 🏀"),
        "",
        rtl("📊 <b>סטטיסטיקה מלאה:</b>"),
        rtl(f"<b>{esc(stage_text)}</b>"),
        "",
    ]

    # אם כן שיחק, מציגים סטטיסטיקה מלאה
    def g(key):
        return stats.get(key) or 0

    lines.extend([
        rtl(f"🎯 <b>נקודות:</b> {g('points')}"),
        rtl(
            f"🏀 <b>מהשדה:</b> {g('fieldGoalsMade')}/{g('fieldGoalsAttempted')} | "
            f"<b>לשלוש:</b> {g('threePointersMade')}/{g('threePointersAttempted')} | "
            f"<b>מהעונשין:</b> {g('freeThrowsMade')}/{g('freeThrowsAttempted')}"
        ),
        rtl(f"💪 <b>ריבאונדים:</b> {g('reboundsTotal')}"),
        rtl(f"🪄 <b>אסיסטים:</b> {g('assists')}"),
        rtl(f"🧤 <b>חטיפות:</b> {g('steals')}"),
        rtl(f"🚫 <b>חסימות:</b> {g('blocks')}"),
        rtl(f"⚠️ <b>איבודים:</b> {g('turnovers')}"),
        rtl(f"📊 <b>פלוס מינוס:</b> {format_plus_minus(g('plusMinusPoints'))}"),
        rtl(f"🕒 <b>דקות:</b> {format_minutes_seconds(mins_raw)}"),
    ])

    return "\n".join(lines)


def stage_from_game(g):
    period = g.get("period") or 0
    txt = str(g.get("gameStatusText", "")).lower()
    status = g.get("gameStatus")

    stage_text = None

    if "end" in txt or "half" in txt or "final" in txt:
        if period == 1:
            stage_text = "⏱️ סיום רבע 1 ⏱️"
        elif period == 2:
            stage_text = "⏱️ מחצית ⏱️"
        elif period == 3:
            stage_text = "⏱️ סיום רבע 3 ⏱️"
        elif period == 4 and status != 3:
            stage_text = "⏱️ סיום רבע 4 ⏱️"

    if status == 3:
        ot = max(0, period - 4)
        if ot == 0:
            stage_text = "🏁 סיום המשחק 🏁"
        else:
            stage_text = f"🏁 סיום המשחק לאחר הארכה {ot} 🏁"

    return stage_text


# ==========================================
# SEND
# ==========================================
def telegram_send_message(text):
    try:
        r = SESSION.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logging.error(f"sendMessage failed: {e}")
        return False


def telegram_send_photo(photo_url, caption):
    try:
        r = SESSION.post(
            f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
            json={
                "chat_id": CHAT_ID,
                "photo": photo_url,
                "caption": caption,
                "parse_mode": "HTML",
            },
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logging.error(f"sendPhoto failed: {e}")
        return False


def send_player_message(player_name_en, message):
    photo = PLAYER_IMAGES.get(player_name_en)

    if photo and len(message) <= 1024:
        ok = telegram_send_photo(photo, message)
        if ok:
            return

    telegram_send_message(message)


# ==========================================
# MAIN LOOP
# ==========================================
def run():
    state = load_state()

    while True:
        try:
            sb = get_json(SB_URL)
            if not sb:
                time.sleep(POLL_SECONDS)
                continue

            games = (((sb or {}).get("scoreboard") or {}).get("games") or [])
            for g in games:
                gid = str(g.get("gameId", ""))
                if not gid:
                    continue

                if gid not in state["games"]:
                    state["games"][gid] = {"events": []}

                gs = state["games"][gid]
                stage = stage_from_game(g)

                if not stage or stage in gs["events"]:
                    continue

                box = get_json(BOX_URL.format(gid=gid))
                if not box:
                    continue

                game = (box or {}).get("game") or {}
                away = ((game.get("awayTeam") or {}).get("teamTricode")) or ""
                home = ((game.get("homeTeam") or {}).get("teamTricode")) or ""

                game_info = {"away": away, "home": home}

                sent_any = False

                for team_key in ("awayTeam", "homeTeam"):
                    players = ((game.get(team_key) or {}).get("players") or [])
                    for p in players:
                        full = f"{p.get('firstName', '')} {p.get('familyName', '')}".strip()
                        if full in ISRAELI_PLAYERS:
                            msg = build_msg(p, stage, game_info)
                            if msg:
                                send_player_message(full, msg)
                                sent_any = True
                                time.sleep(MESSAGE_DELAY_SECONDS)

                if sent_any:
                    gs["events"].append(stage)
                    save_state(state)

        except Exception as e:
            logging.error(f"Main loop error: {e}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()

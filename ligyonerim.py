import os
import re
import json
import time
import logging
import html
import requests
import datetime
import pytz
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

# מיקום הבדיקה של שבת/חג לפי ירושלים (אפשר לשנות אם תרצה)
ISRAEL_LAT = 31.778
ISRAEL_LON = 35.235
ISRAEL_TZID = "Asia/Jerusalem"

PLAYER_HEBREW_NAMES = {
    "Deni Avdija": "דני אבדיה",
    "Ben Saraf": "בן שרף",
    "Danny Wolf": "דני וולף",
}

PLAYER_IMAGES = {
    "Danny Wolf": "https://pbs.twimg.com/media/HCXLU3mbAAAd_Ma?format=jpg&name=small",
    "Ben Saraf": "https://pbs.twimg.com/media/HET8BYNXMAAI9zl?format=jpg&name=small",
    "Deni Avdija": "https://pbs.twimg.com/media/HE9V4E8bQAA_Kqo?format=jpg&name=large",
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
# שבת / חג
# ==========================================
def is_shabbat_or_yom_tov():
    """
    מחזיר True אם עכשיו יש איסור מלאכה בפועל.
    זה מתאים לשבת וליום טוב, ולא אמור לחסום חול המועד.
    """
    try:
        url = (
            "https://www.hebcal.com/zmanim"
            f"?cfg=json&im=1&latitude={ISRAEL_LAT}&longitude={ISRAEL_LON}&tzid={ISRAEL_TZID}"
        )
        data = get_json(url)
        if not data:
            return False

        status = data.get("status") or {}
        return bool(status.get("isAssurBemlacha"))
    except Exception as e:
        logging.error(f"Shabbat/Yom Tov check failed: {e}")
        return False


# ==========================================
# STATE
# ==========================================
def normalize_state(data):
    if not isinstance(data, dict):
        return {"games": {}, "pending": {}}

    if not isinstance(data.get("games"), dict):
        data["games"] = {}

    if not isinstance(data.get("pending"), dict):
        data["pending"] = {}

    return data


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                data = normalize_state(data)
                return data
        except Exception as e:
            logging.error(f"Failed loading state: {e}")
    return {"games": {}, "pending": {}}


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Failed saving state: {e}")


def mark_stage_sent(state, gid, stage):
    gs = state["games"].setdefault(gid, {"events": []})
    if stage not in gs["events"]:
        gs["events"].append(stage)


def queue_pending_message(state, gid, player_name_en, stage, message):
    if gid not in state["pending"]:
        state["pending"][gid] = {}
    state["pending"][gid][player_name_en] = {
        "stage": stage,
        "message": message,
    }


def flush_pending_messages(state):
    """
    שולח הודעות שנשמרו בזמן שבת/חג.
    שולח רק מה שנשמר, ואז מסמן את ה-stage ככבר נשלח.
    """
    pending = state.get("pending") or {}
    if not pending:
        return

    remaining = {}

    for gid, players_payload in pending.items():
        if not isinstance(players_payload, dict):
            continue

        for player_name_en, payload in players_payload.items():
            try:
                message = payload.get("message")
                stage = payload.get("stage")

                if not message or not stage:
                    continue

                ok = send_player_message(player_name_en, message)
                if ok:
                    mark_stage_sent(state, gid, stage)
                    time.sleep(MESSAGE_DELAY_SECONDS)
                else:
                    if gid not in remaining:
                        remaining[gid] = {}
                    remaining[gid][player_name_en] = payload

            except Exception as e:
                logging.error(f"Failed flushing pending message for {player_name_en}: {e}")
                if gid not in remaining:
                    remaining[gid] = {}
                remaining[gid][player_name_en] = payload

    state["pending"] = remaining
    save_state(state)


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


# ==========================================
# MESSAGE BUILDER
# ==========================================
def build_msg(player, stage_text, game_info):
    full = f"{player.get('firstName', '')} {player.get('familyName', '')}".strip()

    if player.get("status") == "INACTIVE":
        return None

    stats = player.get("statistics") or {}
    mins_raw = stats.get("minutesCalculated")
    played = is_played(mins_raw)

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

    if not played:
        lines.append(rtl("⏳ <b>טרם עלה לפרקט</b>"))
    else:
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


def is_final_stage(stage_text):
    return bool(stage_text) and stage_text.startswith("🏁")


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
            return True

    return telegram_send_message(message)


# ==========================================
# MAIN LOOP
# ==========================================
def run():
    state = load_state()
    logging.info("Bot started...")

    while True:
        state_dirty = False

        try:
            shabbat_or_yom_tov = is_shabbat_or_yom_tov()

            # אם יצאנו משבת/חג ויש הודעות ממתינות – שולחים רק את הסיום שנשמר
            if not shabbat_or_yom_tov and state.get("pending"):
                flush_pending_messages(state)
                state = load_state()

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
                    state_dirty = True

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
                                if shabbat_or_yom_tov:
                                    # בזמן שבת/חג: רק אם זה סיום משחק שומרים להמשך
                                    if is_final_stage(stage):
                                        queue_pending_message(state, gid, full, stage, msg)
                                        state_dirty = True
                                else:
                                    # בזמן חול: שולחים כרגיל
                                    ok = send_player_message(full, msg)
                                    if ok:
                                        sent_any = True
                                    time.sleep(MESSAGE_DELAY_SECONDS)

                if not shabbat_or_yom_tov and sent_any:
                    mark_stage_sent(state, gid, stage)
                    state_dirty = True

            if state_dirty:
                save_state(state)

        except Exception as e:
            logging.error(f"Main loop error: {e}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()

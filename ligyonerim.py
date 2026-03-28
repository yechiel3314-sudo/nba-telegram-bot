import os
import re
import json
import time
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==========================================
# הגדרות
# ==========================================
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
STATE_FILE = "nba_israeli_final_v24.json"

RTL = "\u202B"

PLAYER_HEBREW_NAMES = {
    "Deni Avdija": "דני אבדיה",
    "Ben Saraf": "בן שרף",
    "Danny Wolf": "דני וולף"
}

PLAYER_IMAGES = {
    "Danny Wolf": "https://pbs.twimg.com/media/HCXLU3mbAAAd_Ma?format=jpg&name=small",
    "Ben Saraf": "https://pbs.twimg.com/media/HET8BYNXMAAI9zl?format=jpg&name=small",
    "Deni Avdija": "https://cdn.nba.com/teams/uploads/sites/1610612757/2026/02/GettyImages-2261442744.jpg?im=Resize=(1920)"
}

ISRAELI_PLAYERS = set(PLAYER_HEBREW_NAMES.keys())

SB_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
BOX_URL = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"

logging.basicConfig(level=logging.INFO)

# ==========================================
# SESSION
# ==========================================
def build_session():
    s = requests.Session()
    retry = Retry(total=4, backoff_factor=1,
                  status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s

SESSION = build_session()

def get_json(url):
    try:
        return SESSION.get(url, timeout=20).json()
    except:
        return None

# ==========================================
# STATE
# ==========================================
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE, encoding="utf-8"))
        except:
            pass
    return {"games": {}}

def save_state(s):
    json.dump(s, open(STATE_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

# ==========================================
# דקות
# ==========================================
def format_minutes(raw):
    if not raw:
        return "0:00"
    m = re.match(r"PT(\d+)M(?:(\d+))?", raw)
    if not m:
        return "0:00"
    mins = int(m.group(1))
    secs = int(m.group(2) or 0)
    return f"{mins}:{str(secs).zfill(2)}"

# ==========================================
# בניית הודעה
# ==========================================
def build_msg(p, label):
    full = f"{p.get('firstName')} {p.get('familyName')}"
    if p.get("status") == "INACTIVE":
        return None
    stats = p.get("statistics") or {}
    mins = format_minutes(stats.get("minutesCalculated"))
    name_he = PLAYER_HEBREW_NAMES.get(full, full)
    def g(x): return stats.get(x) or 0
    if mins == "0:00":
        return RTL + (
            f"🇮🇱 <b>{name_he}</b>\n"
            f"📍 <b>{label}</b>\n"
            f"⏱️ טרם עלה לפרקט"
        )
    return RTL + (
        f"🇮🇱 <b>הלגיונרים: {name_he}</b> 🇮🇱\n\n"
        f"🏀 <b>סטטיסטיקה מלאה ({label}):</b>\n"
        f"🎯 <b>נקודות:</b> {g('points')}\n"
        f"🏀 <b>מהשדה:</b> {g('fieldGoalsMade')}/{g('fieldGoalsAttempted')} | "
        f"<b>לשלוש:</b> {g('threePointersMade')}/{g('threePointersAttempted')} | "
        f"<b>מהעונשין:</b> {g('freeThrowsMade')}/{g('freeThrowsAttempted')}\n"
        f"💪 <b>ריבאונדים:</b> {g('reboundsTotal')}\n"
        f"🪄 <b>אסיסטים:</b> {g('assists')}\n"
        f"🧤 <b>חטיפות:</b> {g('steals')}\n"
        f"🚫 <b>חסימות:</b> {g('blocks')}\n"
        f"⚠️ <b>איבודים:</b> {g('turnovers')}\n"
        f"📊 <b>פלוס מינוס:</b> {g('plusMinusPoints') if g('plusMinusPoints') <= 0 else '+' + str(g('plusMinusPoints'))}\n"
        f"⏱️ <b>דקות:</b> {mins}"
    )

# ==========================================
# שליחה
# ==========================================
def send_photo(text, photo_url):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
            json={
                "chat_id": CHAT_ID,
                "photo": photo_url,
                "caption": text,
                "parse_mode": "HTML"
            },
            timeout=15
        )
    except:
        pass

def send(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML"
            },
            timeout=15
        )
    except:
        pass

# ==========================================
# ריצה
# ==========================================
def run():
    state = load_state()
    while True:
        try:
            sb = get_json(SB_URL)
            if not sb:
                time.sleep(30)
                continue
            for g in sb["scoreboard"]["games"]:
                gid = g["gameId"]
                if g["gameStatus"] == 1:
                    continue
                if gid not in state["games"]:
                    state["games"][gid] = {"events": [], "final": False}
                gs = state["games"][gid]

                box = get_json(BOX_URL.format(gid=gid))
                if not box:
                    continue
                game = box["game"]

                # סיום רבע או מחצית או הארכה
                key_base = f"{g['period']}_{g['gameStatusText']}"
                period = g['period']
                txt = g['gameStatusText']

                label = None
                send_event = False

                # רבע 1,2,3,4 רגילים
                if txt.lower() in ["end of period", "end of quarter", "half time", "end of quarter 4"]:
                    if period == 1:
                        label = "סיום רבע 1"
                        send_event = True
                    elif period == 2:
                        label = "מחצית"
                        send_event = True
                    elif period == 3:
                        label = "סיום רבע 3"
                        send_event = True
                    elif period == 4 and g["gameStatus"] != 3:
                        label = "סיום רבע 4"
                        send_event = True
                    # הארכות
                    elif period >= 5 and g["gameStatus"] != 3:
                        label = f"סיום הארכה {period-4}"
                        send_event = True

                # סיום המשחק
                if g["gameStatus"] == 3 and not gs["final"]:
                    label = "סיום המשחק"
                    send_event = True
                    gs["final"] = True

                if send_event and key_base not in gs["events"]:
                    for t in ["awayTeam", "homeTeam"]:
                        for p in game[t]["players"]:
                            full = f"{p['firstName']} {p['familyName']}"
                            if full in ISRAELI_PLAYERS:
                                msg = build_msg(p, label)
                                if msg:
                                    photo = PLAYER_IMAGES.get(full)
                                    if photo:
                                        send_photo(msg, photo)
                                    else:
                                        send(msg)
                    gs["events"].append(key_base)
                    save_state(state)

        except Exception as e:
            print("ERROR:", e)
        time.sleep(30)

if __name__ == "__main__":
    run()

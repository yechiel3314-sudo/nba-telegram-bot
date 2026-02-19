import requests
import time
import json
import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from deep_translator import GoogleTranslator

# =====================================================
# תצורה
# =====================================================

TOKEN = "8514837332:AAFZmyXXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

if not TOKEN or not CHAT_ID:
    raise ValueError("חסר TELEGRAM_TOKEN או TELEGRAM_CHAT_ID במשתני סביבה")

STATE_FILE = "nba_complete_master_v11.json"
SCOREBOARD_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
BOX_URL_TEMPLATE = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"

ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

ISRAELI_PLAYERS = ["Deni Avdija", "Ben Saraf", "Danny Wolf"]

translator = GoogleTranslator(source='auto', target='iw')
name_cache = {}

TEAM_NAMES_HEB = {
    "Celtics": "בוסטון סלטיקס", "Bucks": "מילווקי באקס",
    "Hawks": "אטלנטה הוקס", "Cavaliers": "קליבלנד קאבלירס",
    "Magic": "אורלנדו מג'יק", "76ers": "פילדלפיה 76'",
    "Nets": "ברוקלין נטס", "Knicks": "ניו יורק ניקס",
    "Heat": "מיאמי היט", "Hornets": "שארלוט הורנטס",
    "Bulls": "שיקגו בולס", "Pacers": "אינדיאנה פייסרס",
    "Pistons": "דטרויט פיסטונס", "Raptors": "טורונטו ראפטורס",
    "Wizards": "וושינגטון וויזארדס", "Nuggets": "דנבר נאגטס",
    "Timberwolves": "מינסוטה טימברוולבס", "Thunder": "אוקלהומה סיטי ת'אנדר",
    "Trail Blazers": "פורטלנד טרייל בלייזרס", "Jazz": "יוטה ג'אז",
    "Warriors": "גולדן סטייט ווריורס", "Clippers": "ל.א קליפרס",
    "Lakers": "ל.א לייקרס", "Suns": "פיניקס סאנס",
    "Kings": "סקרמנטו קינגס", "Mavericks": "דאלאס מאבריקס",
    "Rockets": "יוסטון רוקטס", "Grizzlies": "ממפיס גריזליס",
    "Pelicans": "ניו אורלינס פליקנס", "Spurs": "סן אנטוניו ספרס"
}

# =====================================================
# לוגים
# =====================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("nba_bot.log"), logging.StreamHandler()]
)

# =====================================================
# פונקציות תשתית
# =====================================================

def safe_get_json(url, timeout=20):
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code != 200:
            logging.warning(f"שגיאת סטטוס {r.status_code} עבור {url}")
            return None
        return r.json()
    except Exception as e:
        logging.error(f"שגיאה בשליפת {url}: {e}")
        return None


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"שגיאה בטעינת state: {e}")
    return {"games": {}, "dates": {"schedule": "", "summary": ""}}


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"שגיאה בשמירת state: {e}")


def send_msg(text):
    if not text:
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=15)
    except Exception as e:
        logging.error(f"שגיאה בשליחת הודעה: {e}")


def translate_player(name):
    if name in name_cache:
        return name_cache[name]
    try:
        translated = translator.translate(name)
        name_cache[name] = translated
        return translated
    except:
        return name


def get_stats(p):
    return p.get("statistics", {})


def format_minutes(raw):
    if not raw or "PT" not in raw:
        return "0:00"
    raw = raw.replace("PT", "").replace("M", ":").replace("S", "")
    if "." in raw:
        raw = raw.split(".")[0]
    parts = raw.split(":")
    if len(parts) == 2:
        return f"{parts[0]}:{parts[1].zfill(2)}"
    return raw


# =====================================================
# לוגיקת סטטיסטיקות
# =====================================================

def calculate_efficiency(p):
    s = get_stats(p)
    pts = s.get('points', 0)
    reb = s.get('reboundsTotal', 0)
    ast = s.get('assists', 0)
    stl = s.get('steals', 0)
    blk = s.get('blocks', 0)
    miss_fg = s.get('fieldGoalsAttempted', 0) - s.get('fieldGoalsMade', 0)
    miss_ft = s.get('freeThrowsAttempted', 0) - s.get('freeThrowsMade', 0)
    tov = s.get('turnovers', 0)
    return (pts + reb + ast + stl + blk) - (miss_fg + miss_ft + tov)


def get_stat_line(p, extended=False):
    s = get_stats(p)
    full_name = f"{p.get('firstName','')} {p.get('familyName','')}"
    name_heb = f"**{translate_player(full_name)}**"

    line = f"▫️ {name_heb}: {s.get('points',0)} נק', {s.get('reboundsTotal',0)} ריב', {s.get('assists',0)} אס'"

    if extended:
        extras = []
        if s.get('steals',0): extras.append(f"{s['steals']} חט'")
        if s.get('blocks',0): extras.append(f"{s['blocks']} חס'")
        if s.get('turnovers',0): extras.append(f"{s['turnovers']} איב'")
        if extras:
            line += f" ({', '.join(extras)})"

    return line


# =====================================================
# בוני הודעות
# =====================================================

def format_period_update(data, label):
    away = data['awayTeam']
    home = data['homeTeam']

    away_heb = TEAM_NAMES_HEB.get(away['teamName'], away['teamName'])
    home_heb = TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])

    if away['score'] > home['score']:
        score = f"{home['score']} - **{away['score']} {away_heb}**"
    elif home['score'] > away['score']:
        score = f"{away['score']} - **{home['score']} {home_heb}**"
    else:
        score = f"{away['score']} - {home['score']} (שוויון)"

    msg = f"📊 {label}: {away_heb} 🆚 {home_heb}\n"
    msg += f"📈 תוצאה: {score}\n\n"

    for team in [away, home]:
        t_name = TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])
        players = team.get('players', [])
        starters = [p for p in players if p.get('starter') == "1"]
        starters.sort(key=lambda x: get_stats(x).get('points',0), reverse=True)

        msg += f"🔥 *{t_name}*:\n"
        for p in starters[:2]:
            msg += get_stat_line(p) + "\n"
        msg += "\n"

    return msg


def format_final_summary(data, ot_count):
    away = data['awayTeam']
    home = data['homeTeam']

    away_heb = TEAM_NAMES_HEB.get(away['teamName'], away['teamName'])
    home_heb = TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])

    if away['score'] > home['score']:
        score = f"{home['score']} - **{away['score']} {away_heb}**"
    else:
        score = f"{away['score']} - **{home['score']} {home_heb}**"

    msg = f"🏁 **סיום המשחק: {away_heb} 🆚 {home_heb}**\n\n"
    msg += f"🏆 תוצאה סופית: {score}\n\n"

    all_players = away['players'] + home['players']
    mvp = max(all_players, key=calculate_efficiency)
    mvp_name = translate_player(f"{mvp['firstName']} {mvp['familyName']}")
    msg += f"⭐ MVP: {mvp_name}\n"

    if ot_count:
        msg += f"\n(לאחר {ot_count} הארכות)"

    return msg


# =====================================================
# לולאת ניטור ראשית
# =====================================================

def run_bot():
    state = load_state()
    logging.info("NBA Bot v11 התחיל לעבוד...")

    while True:
        try:
            now_il = datetime.now(ISRAEL_TZ)
            date_key = now_il.strftime("%Y-%m-%d")

            sb_data = safe_get_json(SCOREBOARD_URL)
            if not sb_data:
                time.sleep(30)
                continue

            games = sb_data.get("scoreboard", {}).get("games", [])

            for g in games:
                gid = g['gameId']
                status = g['gameStatus']

                if status > 1:
                    if gid not in state["games"]:
                        state["games"][gid] = {"periods_sent": [], "final": False}

                    g_state = state["games"][gid]

                    box_data = safe_get_json(BOX_URL_TEMPLATE.format(gid=gid))
                    if not box_data:
                        continue

                    game = box_data.get("game")
                    if not game:
                        continue

                    status_text = g.get("gameStatusText","")
                    p_key = f"{g['period']}_{status_text}"

                    if ("End" in status_text or "Half" in status_text) and p_key not in g_state["periods_sent"]:
                        label = "מחצית" if "Half" in status_text else f"סיום רבע {g['period']}"
                        send_msg(format_period_update(game, label))
                        g_state["periods_sent"].append(p_key)
                        save_state(state)

                    if status == 3 and not g_state["final"]:
                        ot = g['period'] - 4 if g['period'] > 4 else 0
                        send_msg(format_final_summary(game, ot))
                        g_state["final"] = True
                        save_state(state)

        except Exception as e:
            logging.exception(f"שגיאה כללית: {e}")

        time.sleep(30)


if __name__ == "__main__":
    run_bot()

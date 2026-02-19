import requests
import time
from deep_translator import GoogleTranslator

# =====================================
# CONFIG
# =====================================
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event="

translator = GoogleTranslator(source='en', target='iw')
translation_cache = {}
games_state = {}

# =====================================
# SAFE REQUEST
# =====================================
def safe_get(url):
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("❌ HTTP ERROR:", e)
        return None

# =====================================
# TRANSLATION CACHE
# =====================================
def tr(text):
    if not text:
        return ""
    if text in translation_cache:
        return translation_cache[text]
    try:
        t = translator.translate(text)
        translation_cache[text] = t
        return t
    except:
        return text

# =====================================
# TELEGRAM
# =====================================
def send_message(text):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=10
        )
        return r.json()["result"]["message_id"]
    except Exception as e:
        print("❌ SEND ERROR:", e)
        return None

def edit_message(message_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/editMessageText",
            json={
                "chat_id": CHAT_ID,
                "message_id": message_id,
                "text": text,
                "parse_mode": "Markdown"
            },
            timeout=10
        )
    except Exception as e:
        print("❌ EDIT ERROR:", e)

# =====================================
# PLAYER STATS
# =====================================
def extract_stats(team):
    players = team.get("statistics", [{}])[0].get("athletes", [])
    result = []

    for p in players:
        stats = p.get("stats", [])
        if len(stats) >= 13:
            try:
                result.append({
                    "name": p["athlete"]["displayName"],
                    "pts": int(stats[12]),
                    "reb": int(stats[6]),
                    "ast": int(stats[7]),
                    "stl": int(stats[8]) if len(stats) > 8 else 0,
                    "blk": int(stats[9]) if len(stats) > 9 else 0,
                    "starter": p.get("starter", False)
                })
            except:
                continue

    result.sort(key=lambda x: x["pts"], reverse=True)
    return result

# =====================================
# MESSAGE BUILDERS
# =====================================
def build_update(title, event, summary):

    comp = event["competitions"][0]["competitors"]
    home = next(c for c in comp if c["homeAway"] == "home")
    away = next(c for c in comp if c["homeAway"] == "away")

    home_name = tr(home["team"]["displayName"])
    away_name = tr(away["team"]["displayName"])

    home_score = int(home.get("score", 0))
    away_score = int(away.get("score", 0))

    leader = home_name if home_score > away_score else away_name

    msg = f"🏀 *{title}:* {home_name} 🆚 {away_name} 🏀\n\n"
    msg += f"🔹 {leader} מובילה {home_score}-{away_score}\n\n"

    for team in summary.get("boxscore", {}).get("players", []):
        team_name = tr(team["team"]["displayName"])
        players = extract_stats(team)

        if not players:
            continue

        top1 = players[0]
        top2 = players[1] if len(players) > 1 else None
        bench = next((p for p in players if not p["starter"]), None)

        msg += f"🔥 *{team_name}:*\n"

        # מוביל
        msg += f"• 🔝 קלע מוביל: ▫️ {tr(top1['name'])}: {top1['pts']} נק', {top1['reb']} ריב', {top1['ast']} אס'"
        if top1["stl"] or top1["blk"]:
            msg += f" ({top1['stl']} חט', {top1['blk']} חס')"
        msg += "\n"

        # שני
        if top2:
            msg += f"• 🏀 סקורר שני: ▫️ {tr(top2['name'])}: {top2['pts']} נק', {top2['reb']} ריב', {top2['ast']} אס'\n"

        # ספסל
        if bench:
            msg += f"• ⚡️ מהספסל: ▫️ {tr(bench['name'])}: {bench['pts']} נק', {bench['reb']} ריב', {bench['ast']} אס'"
            if bench["stl"] or bench["blk"]:
                msg += f" ({bench['stl']} חט', {bench['blk']} חס')"
            msg += "\n"

        msg += "\n"

    return msg

def build_final(event, summary):
    msg = build_update("סיום המשחק", event, summary)

    all_players = []
    for team in summary.get("boxscore", {}).get("players", []):
        all_players.extend(extract_stats(team))

    all_players.sort(key=lambda x: x["pts"], reverse=True)

    msg += "\n📊 *שלושת הקלעים המובילים במשחק:*\n"
    for p in all_players[:3]:
        msg += f"• {tr(p['name'])} — {p['pts']} נק', {p['reb']} ריב', {p['ast']} אס'\n"

    return msg

# =====================================
# MAIN LOOP
# =====================================
def check_games():
    data = safe_get(SCOREBOARD_URL)
    if not data:
        return

    print(f"🔍 Found {len(data.get('events', []))} games")

    for ev in data.get("events", []):
        gid = ev["id"]
        state = ev["status"]["type"]["state"]

        if gid not in games_state:
            games_state[gid] = {
                "message_id": None,
                "start": False,
                "first10": False,
                "halftime": False,
                "second10": False,
                "final": False
            }

        g = games_state[gid]

        clock = ev["status"].get("displayClock", "20:00")
        if ":" not in clock:
            clock = "20:00"

        period = ev["status"].get("period", 1)
        minute = int(clock.split(":")[0])

        print(f"🏀 Game {gid} | state={state} | period={period} | clock={clock}")

        if state == "in":
            summary = safe_get(SUMMARY_URL + gid)
            if not summary:
                continue

            # התחלה
            if not g["start"]:
                msg = build_update("המשחק יצא לדרך", ev, summary)
                mid = send_message(msg)
                if mid:
                    g["message_id"] = mid
                    g["start"] = True

            # 10 דקות ראשונות
            if period == 1 and minute <= 10 and not g["first10"]:
                msg = build_update("עברו 10 דקות משחק", ev, summary)
                edit_message(g["message_id"], msg)
                g["first10"] = True

            # מחצית
            if period == 2 and minute == 20 and not g["halftime"]:
                msg = build_update("מחצית", ev, summary)
                edit_message(g["message_id"], msg)
                g["halftime"] = True

            # 10 דקות מחצית שנייה
            if period == 2 and minute <= 10 and not g["second10"]:
                msg = build_update("10 דקות במחצית השנייה", ev, summary)
                edit_message(g["message_id"], msg)
                g["second10"] = True

        if state == "post" and not g["final"]:
            summary = safe_get(SUMMARY_URL + gid)
            if not summary:
                continue
            msg = build_final(ev, summary)
            edit_message(g["message_id"], msg)
            g["final"] = True

# =====================================
# RUN
# =====================================
print("🚀 NCAA LIVE BOT STARTED")

while True:
    try:
        check_games()
    except Exception as e:
        print("🔥 CRITICAL ERROR:", e)

    time.sleep(15)

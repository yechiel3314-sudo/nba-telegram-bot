import requests
import time
from deep_translator import GoogleTranslator

# =============================
# CONFIG
# =============================
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event="

translator = GoogleTranslator(source='en', target='iw')
translation_cache = {}
games_state = {}

# =============================
# TRANSLATION (WITH CACHE)
# =============================
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

# =============================
# TELEGRAM
# =============================
def send_message(text):
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }
    )
    return r.json()["result"]["message_id"]

def edit_message(message_id, text):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/editMessageText",
        json={
            "chat_id": CHAT_ID,
            "message_id": message_id,
            "text": text,
            "parse_mode": "Markdown"
        }
    )

# =============================
# PLAYER STATS
# =============================
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

# =============================
# MESSAGE BUILDERS
# =============================
def build_start_message(event, summary):
    comp = event["competitions"][0]["competitors"]
    home = next(c for c in comp if c["homeAway"] == "home")
    away = next(c for c in comp if c["homeAway"] == "away")

    home_name = tr(home["team"]["displayName"])
    away_name = tr(away["team"]["displayName"])

    msg = f"🔥 *המשחק יצא לדרך!* 🔥\n"
    msg += f"🏟️ {home_name} 🆚 {away_name}\n\n"

    for team in summary["boxscore"]["players"]:
        team_name = tr(team["team"]["displayName"])
        players = team.get("statistics", [{}])[0].get("athletes", [])
        starters = [tr(p["athlete"]["displayName"]) for p in players if p.get("starter")]

        msg += f"📍 *{team_name}:*\n"
        msg += f"• 🏀 חמישייה: {', '.join(starters)}\n"
        msg += f"• ❌ חיסורים: לא דווחו פציעות חדשות\n\n"

    return msg

def build_update_message(title, event, summary):
    comp = event["competitions"][0]["competitors"]
    home = next(c for c in comp if c["homeAway"] == "home")
    away = next(c for c in comp if c["homeAway"] == "away")

    home_name = tr(home["team"]["displayName"])
    away_name = tr(away["team"]["displayName"])

    home_score = int(home["score"])
    away_score = int(away["score"])
    leader = home_name if home_score > away_score else away_name

    msg = f"🏀 *{title}:* {home_name} 🆚 {away_name} 🏀\n\n"
    msg += f"🔹 {leader} מובילה {home_score}-{away_score}\n\n"

    for team in summary["boxscore"]["players"]:
        team_name = tr(team["team"]["displayName"])
        players = extract_stats(team)

        if len(players) == 0:
            continue

        top1 = players[0]
        top2 = players[1] if len(players) > 1 else None
        bench = next((p for p in players if not p["starter"]), None)

        msg += f"🔥 *{team_name}:*\n"

        msg += f"• 🔝 קלע מוביל: ▫️ {tr(top1['name'])}: {top1['pts']} נק', {top1['reb']} ריב', {top1['ast']} אס'"
        if top1["stl"] or top1["blk"]:
            msg += f" ({top1['stl']} חט', {top1['blk']} חס')"
        msg += "\n"

        if top2:
            msg += f"• 🏀 סקורר שני: ▫️ {tr(top2['name'])}: {top2['pts']} נק', {top2['reb']} ריב', {top2['ast']} אס'\n"

        if bench:
            msg += f"• ⚡️ מהספסל: ▫️ {tr(bench['name'])}: {bench['pts']} נק', {bench['reb']} ריב', {bench['ast']} אס'\n"

        msg += "\n"

    return msg

def build_final_message(event, summary):
    msg = build_update_message("סיום המשחק", event, summary)
    msg += "\n📊 *שלושת הקלעים המובילים במשחק:*\n"

    all_players = []
    for team in summary["boxscore"]["players"]:
        all_players.extend(extract_stats(team))

    all_players.sort(key=lambda x: x["pts"], reverse=True)

    for p in all_players[:3]:
        msg += f"• {tr(p['name'])} — {p['pts']} נק', {p['reb']} ריב', {p['ast']} אס'\n"

    return msg

# =============================
# MAIN GAME LOGIC
# =============================
def check_games():
    data = requests.get(SCOREBOARD_URL).json()

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
        period = ev["status"]["period"]
        clock = ev["status"]["displayClock"]

        if state == "in":
            summary = requests.get(SUMMARY_URL + gid).json()

            minute = int(clock.split(":")[0])

            # GAME START
            if not g["start"]:
                msg = build_start_message(ev, summary)
                mid = send_message(msg)
                g["message_id"] = mid
                g["start"] = True

            # 10 MIN FIRST HALF
            if period == 1 and minute <= 10 and not g["first10"]:
                msg = build_update_message("עברו 10 דקות משחק", ev, summary)
                edit_message(g["message_id"], msg)
                g["first10"] = True

            # HALFTIME
            if period == 2 and minute == 20 and not g["halftime"]:
                msg = build_update_message("מחצית", ev, summary)
                edit_message(g["message_id"], msg)
                g["halftime"] = True

            # 10 MIN SECOND HALF
            if period == 2 and minute <= 10 and not g["second10"]:
                msg = build_update_message("10 דקות במחצית השנייה", ev, summary)
                edit_message(g["message_id"], msg)
                g["second10"] = True

        # FINAL
        if state == "post" and not g["final"]:
            summary = requests.get(SUMMARY_URL + gid).json()
            msg = build_final_message(ev, summary)
            edit_message(g["message_id"], msg)
            g["final"] = True

# =============================
# LOOP
# =============================
print("🚀 NCAA LIVE BOT RUNNING")

while True:
    try:
        check_games()
    except Exception as e:
        print("Error:", e)

    time.sleep(15)  # חי - בדיקה כל 15 שניות

import requests
import time
from deep_translator import GoogleTranslator

TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

translator = GoogleTranslator(source='en', target='iw')
translation_cache = {}
games_state = {}

def translate_heb(text):
    if not text:
        return ""
    if text in translation_cache:
        return translation_cache[text]
    try:
        tr = translator.translate(text)
        translation_cache[text] = tr
        return tr
    except:
        return text

def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    })
    return r.json()["result"]["message_id"]

def edit_message(message_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/editMessageText"
    requests.post(url, json={
        "chat_id": CHAT_ID,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown"
    })

def extract_players(team_block):
    players = team_block.get('statistics', [{}])[0].get('athletes', [])
    result = []

    for p in players:
        stats = p.get("stats", [])
        if len(stats) >= 13:
            try:
                pts = int(stats[12])
                starter = p.get("starter", False)
                result.append({
                    "name": p["athlete"]["displayName"],
                    "pts": pts,
                    "starter": starter
                })
            except:
                continue

    result.sort(key=lambda x: x["pts"], reverse=True)
    return result

def build_gossip_message(event, summary):

    comp = event["competitions"][0]["competitors"]

    home = next(c for c in comp if c["homeAway"] == "home")
    away = next(c for c in comp if c["homeAway"] == "away")

    home_name = translate_heb(home["team"]["displayName"])
    away_name = translate_heb(away["team"]["displayName"])

    score = f'{home["score"]}-{away["score"]}'
    clock = event["status"]["displayClock"]
    period = event["status"]["period"]

    msg = f"🏀 *{home_name} מול {away_name}*\n\n"

    for team in summary.get("boxscore", {}).get("players", []):
        team_name = translate_heb(team["team"]["displayName"])
        players = extract_players(team)

        top2 = players[:2]
        bench = next((p for p in players if not p["starter"]), None)

        msg += f"🔥 *אצל {team_name}:*\n"

        for p in top2:
            name = translate_heb(p["name"])
            msg += f"{name} מוביל עם {p['pts']} נק׳.\n"

        if bench:
            bench_name = translate_heb(bench["name"])
            msg += f"\n🪑 מהספסל בולט {bench_name} עם {bench['pts']} נק׳.\n"

        msg += "\n"

    msg += f"📊 *תוצאה:* {score}\n"
    msg += f"⏱ רבע {period} | {clock}"

    return msg

def check_games():
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
    data = requests.get(url).json()

    for ev in data.get("events", []):
        if ev["status"]["type"]["state"] != "in":
            continue

        gid = ev["id"]

        if gid not in games_state:
            games_state[gid] = {"message_id": None}

        summary = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event={gid}"
        ).json()

        msg = build_gossip_message(ev, summary)

        if games_state[gid]["message_id"] is None:
            mid = send_message(msg)
            games_state[gid]["message_id"] = mid
        else:
            edit_message(games_state[gid]["message_id"], msg)

        time.sleep(2)

print("🚀 NCAA Gossip Bot Active")
while True:
    try:
        check_games()
    except Exception as e:
        print("Error:", e)

    time.sleep(600)  # כל 10 דקות

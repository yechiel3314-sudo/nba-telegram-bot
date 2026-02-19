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
        # הוספנו User-Agent כדי ש-ESPN לא יחסום את הבוט
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"❌ HTTP ERROR: {e}")
        return None

# =====================================
# TRANSLATION
# =====================================
def tr(text):
    if not text: return ""
    if text in translation_cache: return translation_cache[text]
    try:
        t = translator.translate(text)
        translation_cache[text] = t
        return t
    except:
        return text

# =====================================
# TELEGRAM FUNCTIONS
# =====================================
def send_message(text):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
        res = r.json()
        if res.get("ok"):
            return res["result"]["message_id"]
        return None
    except Exception as e:
        print(f"❌ SEND ERROR: {e}")
        return None

def edit_message(message_id, text):
    if not message_id: return
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/editMessageText"
        requests.post(url, json={
            "chat_id": CHAT_ID,
            "message_id": message_id,
            "text": text,
            "parse_mode": "Markdown"
        }, timeout=10)
    except Exception as e:
        print(f"❌ EDIT ERROR: {e}")

# =====================================
# STATS EXTRACTION
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
                    "pts": int(stats[12]), # במכללות לרוב זה 12
                    "reb": int(stats[6]),
                    "ast": int(stats[7]),
                    "stl": int(stats[8]) if len(stats) > 8 else 0,
                    "blk": int(stats[9]) if len(stats) > 9 else 0,
                    "starter": p.get("starter", False)
                })
            except: continue
    result.sort(key=lambda x: x["pts"], reverse=True)
    return result

# =====================================
# BUILD MESSAGES
# =====================================
def build_update(title, event, summary):
    comp = event["competitions"][0]["competitors"]
    home = next(c for c in comp if c["homeAway"] == "home")
    away = next(c for c in comp if c["homeAway"] == "away")

    home_name = tr(home["team"]["displayName"])
    away_name = tr(away["team"]["displayName"])
    home_score = home.get("score", 0)
    away_score = away.get("score", 0)

    msg = f"🏀 *{title}:* {home_name} 🆚 {away_name} 🏀\n"
    msg += f"💰 תוצאה: *{home_score} - {away_score}*\n\n"

    for team in summary.get("boxscore", {}).get("players", []):
        team_name = tr(team["team"]["displayName"])
        players = extract_stats(team)
        if not players: continue

        top1 = players[0]
        bench = next((p for p in players if not p["starter"]), None)

        msg += f"🔥 *{team_name}:*\n"
        msg += f"• 🔝 מוביל: {tr(top1['name'])} ({top1['pts']}נ', {top1['reb']}ר')\n"
        if bench:
            msg += f"• ⚡️ ספסל: {tr(bench['name'])} ({bench['pts']}נ', {bench['reb']}ר')\n"
        msg += "\n"
    return msg

# =====================================
# CORE LOGIC
# =====================================
def check_games():
    data = safe_get(SCOREBOARD_URL)
    if not data: return

    for ev in data.get("events", []):
        gid = ev["id"]
        state = ev["status"]["type"]["state"]
        
        if gid not in games_state:
            games_state[gid] = {"message_id": None, "start": False, "10min": False, "halftime": False, "final": False}

        g = games_state[gid]
        clock = ev["status"].get("displayClock", "20:00")
        period = ev["status"].get("period", 1)
        
        # חילוץ דקות (מטפל בפורמט MM:SS)
        try: minute = int(clock.split(":")[0])
        except: minute = 20

        # משחק פעיל
        if state == "in":
            summary = safe_get(SUMMARY_URL + gid)
            if not summary: continue

            # שלב 1: פתיחה
            if not g["start"]:
                mid = send_message(build_update("המשחק יצא לדרך", ev, summary))
                if mid: g["message_id"] = mid; g["start"] = True

            # שלב 2: אחרי 10 דקות (שעון יורד מ-10)
            if period == 1 and minute <= 10 and not g["10min"]:
                edit_message(g["message_id"], build_update("עדכון: 10 דקות ראשונות", ev, summary))
                g["10min"] = True

            # שלב 3: מחצית
            if period == 2 and minute == 20 and not g["halftime"]:
                edit_message(g["message_id"], build_update("מחצית", ev, summary))
                g["halftime"] = True

        # שלב 4: סיום
        if state == "post" and not g["final"]:
            summary = safe_get(SUMMARY_URL + gid)
            if summary:
                edit_message(g["message_id"], build_update("🏁 סיום המשחק", ev, summary))
                g["final"] = True

# =====================================
# RUN
# =====================================
if __name__ == "__main__":
    print("🚀 NCAA BOT IS BACK ONLINE")
    while True:
        try:
            check_games()
        except Exception as e:
            print(f"🔥 Error: {e}")
        time.sleep(30) # 30 שניות זה זמן מצוין לעדכון

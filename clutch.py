import requests
import time
import json
import os
import random
from datetime import datetime
from deep_translator import GoogleTranslator

# ==========================================
# הגדרות
# ==========================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
CACHE_FILE = "nba_cache.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

translator = GoogleTranslator(source='en', target='iw')

# ==========================================
# משפטי סיום מתחלפים
# ==========================================
ENDINGS = [
    "זה היה ערב כדורסל מטורף 🔥",
    "איזה משחק ענק ראינו היום!",
    "כדורסל ברמה הכי גבוהה שיש 💯",
    "ה-NBA לא מאכזבת!",
    "עוד משחק לפנתיאון 📜",
    "איזה דרמה עד הסוף!",
    "לילה של כדורסל משובח 🏀",
    "אי אפשר להפסיק לצפות בזה!",
    "משחק שייזכר להרבה זמן",
    "הצגה של ממש על הפרקט 🎭"
]

def get_random_ending():
    return random.choice(ENDINGS)

# ==========================================
# Cache
# ==========================================
def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "games" not in data:
                    data["games"] = {}
                return data
        except:
            pass
    return {"games": {}}

def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=4, ensure_ascii=False)

cache = load_cache()

# ==========================================
# שליחת טלגרם
# ==========================================
def send_telegram(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML"
            },
            timeout=10
        )
    except Exception as e:
        print("Telegram error:", e)

# ==========================================
# עיצוב הודעה
# ==========================================
def format_msg(game, label, is_final=False):
    away = game['awayTeam']
    home = game['homeTeam']

    a_name = f"{away['teamCity']} {away['teamName']}"
    h_name = f"{home['teamCity']} {home['teamName']}"

    msg = f"🏀 <b>{label}</b>\n\n"
    msg += f"{a_name} 🆚 {h_name}\n\n"

    msg += f"📊 <b>{away['score']} - {home['score']}</b>\n\n"

    if is_final:
        msg += "🏁 <b>סיום המשחק</b>\n\n"
        msg += f"💬 {get_random_ending()}"

    return msg

# ==========================================
# לולאה ראשית
# ==========================================
def run():
    print("🚀 בוט NBA עם משפטי סיום מתחלפים")
    
    while True:
        try:
            resp = requests.get(NBA_URL, headers=HEADERS, timeout=10).json()
            games = resp.get('scoreboard', {}).get('games', [])

            for g in games:
                gid = g['gameId']
                status = g['gameStatus']

                if gid not in cache["games"]:
                    cache["games"][gid] = []

                log = cache["games"][gid]

                # סיום משחק
                if status == 3 and "final" not in log:
                    box = requests.get(
                        f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json",
                        headers=HEADERS
                    ).json()

                    msg = format_msg(box['game'], "סיום המשחק", is_final=True)
                    send_telegram(msg)

                    log.append("final")
                    save_cache()

                    print(f"🏁 נשלח סיום משחק {gid}")

        except Exception as e:
            print("Error:", e)

        time.sleep(10)

if __name__ == "__main__":
    run()

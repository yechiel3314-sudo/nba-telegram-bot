import requests
import time
import json
import os

# ==========================================
# הגדרות מערכת (ENV בלבד!)
# ==========================================

TELEGRAM_TOKEN = os.getenv("8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE")
CHAT_ID = os.getenv("1003808107418")

NBA_SCOREBOARD_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
NBA_BOXSCORE_URL = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{}.json"

CACHE_FILE = "nba_bot_cache.json"
PLAYERS_FILE = "players_db.json"

# ==========================================
# 30 קבוצות NBA בעברית
# ==========================================

TEAMS_HE = {
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
    "Los Angeles Lakers": "לוס אנג'לס לייקרס",
    "Memphis Grizzlies": "ממפיס גריזליס",
    "Miami Heat": "מיאמי היט",
    "Milwaukee Bucks": "מילווקי באקס",
    "Minnesota Timberwolves": "מינסוטה טימברוולבס",
    "New Orleans Pelicans": "ניו אורלינס פליקנס",
    "New York Knicks": "ניו יורק ניקס",
    "Oklahoma City Thunder": "אוקלהומה סיטי ת'אנדר",
    "Orlando Magic": "אורלנדו מג'יק",
    "Philadelphia 76ers": "פילדלפיה סיקסרס",
    "Phoenix Suns": "פיניקס סאנס",
    "Portland Trail Blazers": "פורטלנד טרייל בלייזרס",
    "Sacramento Kings": "סקרמנטו קינגס",
    "San Antonio Spurs": "סן אנטוניו ספרס",
    "Toronto Raptors": "טורונטו ראפטורס",
    "Utah Jazz": "יוטה ג'אז",
    "Washington Wizards": "וושינגטון וויזארדס"
}

# ==========================================
# בניית מסד נתונים 540 שחקנים
# ==========================================

def build_players_db():
    if os.path.exists(PLAYERS_FILE):
        return

    print("בונה מאגר שחקנים...")
    players = {}

    teams = requests.get(
        "https://cdn.nba.com/static/json/staticData/teamRoster.json"
    ).json()["league"]["standard"]

    for team in teams:
        team_id = team["teamId"]
        roster_url = f"https://cdn.nba.com/static/json/staticData/teamRoster_{team_id}.json"
        roster = requests.get(roster_url).json()["league"]["standard"]["players"]

        for p in roster:
            full_name = f"{p['firstName']} {p['lastName']}"
            players[str(p["personId"])] = {
                "fullNameEng": full_name,
                "fullNameHeb": full_name,
                "team": team["fullName"]
            }

    with open(PLAYERS_FILE, "w", encoding="utf-8") as f:
        json.dump(players, f, indent=2, ensure_ascii=False)

    print("✅ מאגר שחקנים נוצר")

# ==========================================
# טעינת קבצים
# ==========================================

def load_players():
    with open(PLAYERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"games": {}}

def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=4, ensure_ascii=False)

# ==========================================
# MVP חכם יותר (לא רק נקודות)
# ==========================================

def calculate_mvp(players):
    def score(p):
        s = p["statistics"]
        return (
            s["points"]
            + s["reboundsTotal"]
            + s["assists"]
            + s["steals"]
            + s["blocks"]
            - s["turnovers"]
        )

    return max(players, key=score)

# ==========================================
# תמונת אקשן
# ==========================================

def get_action_photo(person_id):
    action_url = f"https://a.espncdn.com/photo/2024/r{person_id}_1296x729_16-9.jpg"
    try:
        r = requests.get(action_url, timeout=5)
        if r.status_code == 200:
            return action_url
    except:
        pass

    return f"https://cdn.nba.com/headshots/nba/latest/1040x760/{person_id}.png"

# ==========================================
# שליחה לטלגרם
# ==========================================

def send_telegram(text, photo_url=None):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("חסר TELEGRAM_TOKEN או CHAT_ID")
        return

    if photo_url:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        payload = {
            "chat_id": CHAT_ID,
            "photo": photo_url,
            "caption": text,
            "parse_mode": "Markdown"
        }
    else:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }

    requests.post(url, json=payload, timeout=10)

# ==========================================
# לוגיקה ראשית
# ==========================================

def run():
    print("🚀 הבוט באוויר...")

    while True:
        try:
            data = requests.get(NBA_SCOREBOARD_URL, timeout=10).json()

            for g in data["scoreboard"]["games"]:
                gid = g["gameId"]
                status = g["gameStatus"]

                if gid not in cache["games"]:
                    cache["games"][gid] = []

                if status == 3 and "final_sent" not in cache["games"][gid]:
                    box = requests.get(
                        NBA_BOXSCORE_URL.format(gid),
                        timeout=10
                    ).json()["game"]

                    away = box["awayTeam"]
                    home = box["homeTeam"]

                    all_players = away["players"] + home["players"]
                    mvp = calculate_mvp(all_players)

                    mvp_name = players_db.get(
                        str(mvp["personId"]),
                        {}
                    ).get("fullNameHeb", "Unknown")

                    photo = get_action_photo(mvp["personId"])

                    msg = f"""🏀 סיום המשחק

{away['teamCity']} {away['score']} - {home['score']} {home['teamCity']}

⭐ MVP: {mvp_name}
{mvp['statistics']['points']} נק'
{mvp['statistics']['reboundsTotal']} רב'
{mvp['statistics']['assists']} אס'
"""

                    send_telegram(msg, photo)

                    cache["games"][gid].append("final_sent")
                    save_cache()

        except Exception as e:
            print("Error:", e)

        time.sleep(30)

# ==========================================

if __name__ == "__main__":
    build_players_db()
    players_db = load_players()
    cache = load_cache()
    run()

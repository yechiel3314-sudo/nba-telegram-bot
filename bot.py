import requests
import time
import json
import os

# ==========================================
# הגדרות מערכת
# ==========================================

TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "1003808107418"

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
# בניית מסד נתונים 540 שחקנים (פעם אחת)
# ==========================================

def build_players_db():
    if os.path.exists(PLAYERS_FILE):
        return

    print("בונה מאגר שחקנים...")
    players = {}

    teams = requests.get("https://cdn.nba.com/static/json/staticData/teamRoster.json").json()["league"]["standard"]

    for team in teams:
        team_id = team["teamId"]
        roster_url = f"https://cdn.nba.com/static/json/staticData/teamRoster_{team_id}.json"
        roster = requests.get(roster_url).json()["league"]["standard"]["players"]

        for p in roster:
            full_name = f"{p['firstName']} {p['lastName']}"
            players[str(p["personId"])] = {
                "fullNameEng": full_name,
                "fullNameHeb": full_name,  # אפשר לערוך ידנית כוכבים
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
# תמונת אקשן MVP
# ==========================================

def get_action_photo(person_id):
    # ניסיון לתמונת אקשן
    action_url = f"https://a.espncdn.com/photo/2024/r{person_id}_1296x729_16-9.jpg"
    r = requests.get(action_url)
    if r.status_code == 200:
        return action_url

    # fallback headshot
    return f"https://cdn.nba.com/headshots/nba/latest/1040x760/{person_id}.png"

# ==========================================
# שליחה לטלגרם
# ==========================================

def send_telegram(text, photo_url=None):
    if photo_url:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        payload = {"chat_id": CHAT_ID, "photo": photo_url, "caption": text, "parse_mode": "Markdown"}
    else:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}

    try:
        requests.post(url, json=payload, timeout=10)
    except:
        pass

# ==========================================
# עיצוב הודעה
# ==========================================

def get_stat_line(p):
    s = p["statistics"]
    return f"{s['points']} נק', {s['reboundsTotal']} רב', {s['assists']} אס'"

def format_msg(box, label, is_final=False):
    away = box["awayTeam"]
    home = box["homeTeam"]

    away_name = f"{away['teamCity']} {away['teamName']}"
    home_name = f"{home['teamCity']} {home['teamName']}"

    away_he = TEAMS_HE.get(away_name, away_name)
    home_he = TEAMS_HE.get(home_name, home_name)

    msg = f"🏀 **{label}**\n"
    msg += f"**{away_he} 🆚 {home_he}**\n\n"

    leader = away_he if away["score"] > home["score"] else home_he
    msg += f"🔥 **{leader} {away['score']} - {home['score']}** 🔥\n\n"

    period = box.get("period", 0)
    count = 3 if (period >= 4 or is_final) else 2

    for team in [away, home]:
        team_name = f"{team['teamCity']} {team['teamName']}"
        team_he = TEAMS_HE.get(team_name, team_name)

        msg += f"📍 **{team_he}**\n"
        top = sorted(team["players"], key=lambda x: x["statistics"]["points"], reverse=True)[:count]

        for i, p in enumerate(top):
            medal = ["🥇", "🥈", "🥉"][i]
            name = players_db.get(str(p["personId"]), {}).get("fullNameHeb", p["firstName"] + " " + p["familyName"])
            msg += f"{medal} **{name}**: {get_stat_line(p)}\n"

        msg += "\n"

    photo = None

    if is_final:
        mvp = max(away["players"] + home["players"], key=lambda x: x["statistics"]["points"])
        mvp_name = players_db.get(str(mvp["personId"]), {}).get("fullNameHeb")
        msg += f"⭐ **MVP: {mvp_name}**\n"
        msg += f"{get_stat_line(mvp)}"
        photo = get_action_photo(mvp["personId"])

    return msg, photo

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
                    box = requests.get(NBA_BOXSCORE_URL.format(gid)).json()["game"]
                    msg, photo = format_msg(box, "סיום המשחק", True)
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

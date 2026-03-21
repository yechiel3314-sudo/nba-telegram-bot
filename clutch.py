import requests
import time
import random

TELEGRAM_TOKEN = "8284141482:AAGG1vPtJrLeAvL7kADMeuFGbEydIq08ib0"
CHAT_ID = "-1003714393119"

SCOREBOARD_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
BOXSCORE_URL = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{}.json"

sent_clutch_alerts = {}

# ===== תרגומים (השארתי קצר - תדביק את שלך המלא) =====
NBA_TEAMS_HEBREW = {
    "Los Angeles Lakers": "לוס אנג'לס לייקרס",
    "Golden State Warriors": "גולדן סטייט ווריורס"
}

NBA_PLAYERS_HEB = {
    "LeBron James": "לברון ג'יימס",
    "Stephen Curry": "סטפן קארי"
}

def translate_name(name):
    if name in NBA_PLAYERS_HEB:
        return NBA_PLAYERS_HEB[name]
    for eng, heb in NBA_TEAMS_HEBREW.items():
        name = name.replace(eng, heb)
    return name

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=10)
    except:
        pass

def clean_clock(clock_text):
    try:
        time_part = clock_text.split(' ')[-1]
        if time_part.startswith('0'):
            time_part = time_part[1:]
        return time_part
    except:
        return clock_text

def format_clutch_msg(box, raw_clock):
    away, home = box['awayTeam'], box['homeTeam']

    a_full = translate_name(f"{away['teamCity']} {away['teamName']}")
    h_full = translate_name(f"{home['teamCity']} {home['teamName']}")

    clean_time = clean_clock(raw_clock)

    # קובע מובילה
    if away['score'] > home['score']:
        leader = a_full
    elif home['score'] > away['score']:
        leader = h_full
    else:
        leader = "שוויון"

    score_line = f"<b>{away['score']} - {home['score']}</b>"

    msg = "\u200f🚨 <b>התראת קלאץ'!</b> 🚨\n"
    msg += f"\u200f🏀 <b>{a_full} 🆚 {h_full}</b> 🏀\n\n"

    if leader == "שוויון":
        msg += f"\u200f🔥 <b>שוויון {score_line}</b> 🔥\n\n"
    else:
        msg += f"\u200f🔥 <b>{leader} מובילה {score_line}</b> 🔥\n\n"

    msg += f"\u200f⏱️ <b>זמן נשאר לסיום: {clean_time}</b>\n\n"

    # שחקנים מובילים
    msg += "\u200f📍 <b>קלעים מובילים:</b>\n"

    for team in [home, away]:
        players = [p for p in team['players'] if 'statistics' in p]
        if not players:
            continue

        star = max(players, key=lambda x: x['statistics']['points'])
        full_name = f"{star['firstName']} {star['familyName']}"
        name = translate_name(full_name)
        pts = star['statistics']['points']

        team_name = translate_name(team['teamName'])
        msg += f"\u200f⭐ <b>{team_name}</b>: {name} ({pts})\n"

    return msg

def check_for_clutch():
    try:
        data = requests.get(SCOREBOARD_URL, timeout=10).json()
        games = data.get('scoreboard', {}).get('games', [])

        for game in games:
            gid = game['gameId']
            status = game['gameStatus']
            period = game['period']
            clock = game['gameStatusText']

            if status != 2 or period < 4:
                continue

            try:
                time_part = clock.split(' ')[-1]
                mins = int(time_part.split(':')[0])
                diff = abs(game['homeTeam']['score'] - game['awayTeam']['score'])

                # 🔥 התנאים שלך
                if mins < 4 and diff <= 3:

                    key = f"{gid}_{mins}"
                    if key in sent_clutch_alerts:
                        continue

                    box = requests.get(BOXSCORE_URL.format(gid), timeout=10).json()

                    msg = format_clutch_msg(box['game'], clock)
                    send_telegram(msg)

                    sent_clutch_alerts[key] = True

            except:
                continue

    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    print("🚀 הבוט פועל...")
    while True:
        check_for_clutch()
        time.sleep(10)

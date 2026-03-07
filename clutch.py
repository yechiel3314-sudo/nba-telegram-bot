import requests
import time
import random

# ==========================================
# הגדרות מערכת
# ==========================================
TELEGRAM_TOKEN = "8284141482:AAGG1vPtJrLeAvL7kADMeuFGbEydIq08ib0"
CHAT_ID = "-1003714393119"
SCOREBOARD_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
BOXSCORE_URL = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{}.json"

sent_clutch_alerts = {}

# כאן תדביק את המילון המלא מהקובץ שלך (bot.py)
NBA_PLAYERS_HEB = {
    "Deni Avdija": "דני אבדיה",
    "LeBron James": "לברון ג'יימס",
    "Stephen Curry": "סטפן קרי",
    "Luka Doncic": "לוקה דונצ'יץ'",
    "Kyrie Irving": "קיירי ארווינג",
    "Kevin Durant": "קווין דוראנט",
    "Jayson Tatum": "ג'ייסון טייטום",
    # ... תוסיף כאן את שאר השמות מהמאגר שלך כפי שמופיע בתמונה
}

NBA_TEAMS_HEBREW = {
    "Lakers": "לייקרס", "Celtics": "סלטיקס", "Warriors": "ווריורס",
    "Knicks": "ניקס", "Mavericks": "מאבריקס", "Bulls": "בולס"
    # תוסיף כאן את שמות הקבוצות מהמילון שלך
}

def translate_name(name):
    # קודם בודקים אם זה שם שחקן שקיים במילון הגדול
    if name in NBA_PLAYERS_HEB:
        return NBA_PLAYERS_HEB[name]
    
    # אם לא, בודקים תרגום קבוצות
    for eng, heb in NBA_TEAMS_HEBREW.items():
        name = name.replace(eng, heb)
    return name

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=15)
    except:
        pass

def format_clutch_msg(box, raw_clock):
    away, home = box['awayTeam'], box['homeTeam']
    
    a_full = translate_name(f"{away['teamCity']} {away['teamName']}")
    h_full = translate_name(f"{home['teamCity']} {home['teamName']}")
    
    # ניקוי השעון - מוריד 0 בהתחלה (למשל 03:20 -> 3:20)
    time_part = raw_clock.split(' ')[-1] if ' ' in raw_clock else raw_clock
    clean_clock = time_part.lstrip('0') if (time_part.startswith('0') and ':' in time_part) else time_part
    
    score_str = f"<b>{max(away['score'], home['score'])} - {min(away['score'], home['score'])}</b>"
    if away['score'] > home['score']:
        status_line = f"🔥 <b>{a_full} מובילה {score_str}</b> 🔥"
    elif home['score'] > away['score']:
        status_line = f"🔥 <b>{h_full} מובילה {score_str}</b> 🔥"
    else:
        status_line = f"🔥 <b>שוויון דרמטי {score_str}</b> 🔥"

    ending_phrases = [
        "מתח שיא באולם! 🔥", "כל כדור קובע עכשיו! 🏀", "הדרמה בשיאה, מי תמצמץ ראשונה? 👀",
        "זה הזמן של הכוכבים הגדולים! ✨", "הקהל בטירוף, הולכים לסיום ענק! 🏟️",
        "קרב של ראש בראש עד השנייה האחרונה! ⚔️", "מי תצא עם הניצחון הלילה? 🏆",
        "משחק של עצבים מפלדה! ⛓️", "פשוט תענוג של כדורסל! 🏀🔥", "הכל פתוח בדקות ההכרעה! 🔓"
    ]
    random_ending = random.choice(ending_phrases)

    msg = f"\u200f🚨 <b>התראת קלאץ'!</b> 🚨\n"
    msg += f"\u200f🏀 <b>{a_full} 🆚 {h_full}</b> 🏀\n\n"
    
    msg += f"\u200f{status_line}\n\n"
    
    msg += f"\u200f⏱️ <b>זמן לסיום: {clean_clock}</b>\n\n"
    
    msg += f"\u200f📍 <b>הקלעים הבולטים במשחק:</b>\n"
    
    # קבוצת הבית תמיד ראשונה
    for team in [home, away]:
        t_name = translate_name(team['teamName'])
        active_players = [p for p in team['players'] if 'statistics' in p]
        star = max(active_players, key=lambda x: x['statistics']['points'])
        
        # בניית שם מלא לבדיקה במילון
        full_name_eng = f"{star['firstName']} {star['familyName']}"
        p_name_heb = translate_name(full_name_eng)
        
        pts = star['statistics']['points']
        msg += f"\u200f⭐ <b>{t_name}</b>: {p_name_heb} ({pts} נק')\n"
    
    msg += f"\n\u200f{random_ending}"
    return msg

def check_for_clutch():
    try:
        response = requests.get(SCOREBOARD_URL, timeout=10).json()
        games = response.get('scoreboard', {}).get('games', [])
        
        for game in games:
            gid = game['gameId']
            status = game['gameStatus']
            period = game['period']
            clock_text = game['gameStatusText']
            
            if status == 2 and period >= 4:
                try:
                    time_only = clock_text.split(' ')[-1]
                    mins = int(time_only.split(':')[0]) if ':' in time_only else 0
                    diff = abs(game['homeTeam']['score'] - game['awayTeam']['score'])
                    
                    if diff <= 3 and mins < 4:
                        alert_key = f"{gid}_{mins}"
                        if alert_key not in sent_clutch_alerts:
                            box_data = requests.get(BOXSCORE_URL.format(gid)).json()
                            final_msg = format_clutch_msg(box_data['game'], clock_text)
                            send_telegram(final_msg)
                            sent_clutch_alerts[alert_key] = True
                except:
                    continue
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("🚀 בוט קלאץ' פעיל עם תרגום שחקנים מלא...")
    while True:
        check_for_clutch()
        time.sleep(10)

import requests
import time
import random

# ==========================================
# הגדרות מערכת
# ==========================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
SCOREBOARD_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
BOXSCORE_URL = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{}.json"

sent_clutch_alerts = {}

def translate_name(name):
    # כאן הפונקציה אמורה להתחבר למילון התרגומים שלך
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
    
    # שמות מלאים של הקבוצות
    a_full = translate_name(f"{away['teamCity']} {away['teamName']}")
    h_full = translate_name(f"{home['teamCity']} {home['teamName']}")
    
    # ניקוי השעון: משאיר רק מספרים ונקודתיים
    clean_clock = "".join([c for c in raw_clock if c.isdigit() or c == ':']).strip(': ')
    
    # חישוב מובילה ותוצאה
    score_str = f"<b>{max(away['score'], home['score'])} - {min(away['score'], home['score'])}</b>"
    if away['score'] > home['score']:
        status_line = f"🔥 <b>{a_full} מובילה {score_str}</b> 🔥"
    elif home['score'] > away['score']:
        status_line = f"🔥 <b>{h_full} מובילה {score_str}</b> 🔥"
    else:
        status_line = f"🔥 <b>שוויון דרמטי {score_str}</b> 🔥"

    # רשימת 10 משפטי סיום
    ending_phrases = [
        "מתח שיא באולם! 🔥",
        "כל כדור קובע עכשיו! 🏀",
        "הדרמה בשיאה, מי תמצמץ ראשונה? 👀",
        "זה הזמן של הכוכבים הגדולים! ✨",
        "הקהל בטירוף, הולכים לסיום ענק! 🏟️",
        "קרב של ראש בראש עד השנייה האחרונה! ⚔️",
        "מי תצא עם הניצחון הלילה? 🏆",
        "משחק של עצבים מפלדה! ⛓️",
        "פשוט תענוג של כדורסל! 🏀🔥",
        "הכל פתוח בדקות ההכרעה! 🔓"
    ]
    random_ending = random.choice(ending_phrases)

    # בניית ההודעה
    msg = f"\u200f🚨 <b>התראת קלאץ'!</b> 🚨\n"
    msg += f"\u200f🏀 <b>{a_full} 🆚 {h_full}</b> 🏀\n\n"
    
    msg += f"\u200f{status_line}\n\n"
    
    msg += f"\u200f⏱️ <b>זמן לסיום: {clean_clock}</b>\n\n"
    
    msg += f"\u200f📍 <b>הקלעים הבולטים במשחק:</b>\n"
    
    for team in [home, away]:
        t_full = translate_name(f"{team['teamCity']} {team['teamName']}")
        star = max(team['players'], key=lambda x: x['statistics']['points'])
        p_name = translate_name(f"{star['firstName']} {star['familyName']}")
        pts = star['statistics']['points']
        msg += f"\u200f⭐ <b>{t_full}</b>: {p_name} ({pts} נק')\n"
    
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
            clock = game['gameStatusText']
            
            # תנאי: רבע 4 או הארכה, משחק פעיל
            if status == 2 and period >= 4:
                try:
                    mins = int(clock.split(':')[0]) if ':' in clock else 0
                    diff = abs(game['homeTeam']['score'] - game['awayTeam']['score'])
                    
                    # תנאי קלאץ': הפרש עד 3 נקודות, פחות מ-4 דקות לסיום
                    if diff <= 3 and mins < 4:
                        # מפתח ייחודי כדי לשלוח רק פעם אחת בכל דקה
                        alert_key = f"{gid}_{mins}"
                        if alert_key not in sent_clutch_alerts:
                            box_data = requests.get(BOXSCORE_URL.format(gid)).json()
                            final_msg = format_clutch_msg(box_data['game'], clock)
                            send_telegram(final_msg)
                            sent_clutch_alerts[alert_key] = True
                except:
                    continue
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("🚀 בוט התראות קלאץ' פעיל...")
    while True:
        check_for_clutch()
        time.sleep(20)

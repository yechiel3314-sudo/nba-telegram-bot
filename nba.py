import requests
import time
import pytz
from datetime import datetime

# ==========================================
# הגדרות וטוקנים
# ==========================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"

# שעות שליחה
SCHEDULE_TIME = "15:26"
RESULTS_TIME = "15:26"

TEAM_TRANSLATIONS = {
    "Atlanta Hawks": "אטלנטה הוקס", "Boston Celtics": "בוסטון סלטיקס",
    "Brooklyn Nets": "ברוקלין נטס 🇮🇱", "Charlotte Hornets": "שארלוט הורנטס",
    "Chicago Bulls": "שיקגו בולס", "Cleveland Cavaliers": "קליבלנד קאבלירס",
    "Dallas Mavericks": "דאלאס מאבריקס", "Denver Nuggets": "דנבר נאגטס",
    "Detroit Pistons": "דטרויט פיסטונס", "Golden State Warriors": "גולדן סטייט",
    "Houston Rockets": "יוסטון רוקטס", "Indiana Pacers": "אינדיאנה פייסרס",
    "LA Clippers": "לוס אנג'לס קליפרס", "Los Angeles Lakers": "לוס אנג'לס לייקרס",
    "Memphis Grizzlies": "ממפיס גריזליס", "Miami Heat": "מיאמי היט",
    "Milwaukee Bucks": "מילווקי באקס", "Minnesota Timberwolves": "מינסוטה טימברוולבס",
    "New Orleans Pelicans": "ניו אורלינס פליקנס", "New York Knicks": "ניו יורק ניקס",
    "Oklahoma City Thunder": "אוקלהומה סיטי", "Orlando Magic": "אורלנדו מג'יק",
    "Philadelphia 76ers": "פילדלפיה 76", "Phoenix Suns": "פיניקס סאנס",
    "Portland Trail Blazers": "פורטלנד 🇮🇱", "Sacramento Kings": "סקרמנטו קינגס",
    "San Antonio Spurs": "סן אנטוניו ספרס", "Toronto Raptors": "טורונטו ראפפורטס",
    "Utah Jazz": "יוטה ג'אז", "Washington Wizards": "וושינגטון וויזארדס"
}

def translate_team(city, name):
    full = f"{city} {name}"
    # בדיקה ספציפית לפורטלנד וברוקלין כדי לוודא שהדגל תמיד מופיע
    if "Brooklyn" in full: return TEAM_TRANSLATIONS["Brooklyn Nets"]
    if "Portland" in full: return TEAM_TRANSLATIONS["Portland Trail Blazers"]
    return TEAM_TRANSLATIONS.get(full, full)

def format_nba_time(time_str):
    """המרה אוטומטית לשעון ישראל כולל שעון קיץ"""
    try:
        utc_dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
        israel_tz = pytz.timezone('Asia/Jerusalem')
        israel_dt = utc_dt.astimezone(israel_tz)
        return israel_dt.strftime("%H:%M")
    except:
        return "TBD"

# ==========================================
# פונקציות הודעות
# ==========================================

def get_schedule_msg(games):
    msg = "‏🏀 <b>לוח משחקי הלילה</b> 🏀\n\n"
    found = False
    for g in games:
        # תיקון: מחפש כל משחק שאינו "סופי" (Status 3) כדי להציגו בלו"ז
        if g['gameStatus'] != 3:
            home = translate_team(g['homeTeam']['teamCity'], g['homeTeam']['teamName'])
            away = translate_team(g['awayTeam']['teamCity'], g['awayTeam']['teamName'])
            start_time = format_nba_time(g['gameEt'])
            msg += f"‏⏰ <b>{start_time}</b>\n‏🏀 {home} 🆚 {away}\n\n"
            found = True
    return msg if found else "‏🏀 <b>אין משחקים מתוכננים להלילה.</b>"

def get_results_msg(games):
    msg = "‏🏀 <b>תוצאות משחקי הלילה ב NBA</b> 🏀\n\n"
    found = False
    for g in games:
        if g['gameStatus'] == 3:
            h_name = translate_team(g['homeTeam']['teamCity'], g['homeTeam']['teamName'])
            a_name = translate_team(g['awayTeam']['teamCity'], g['awayTeam']['teamName'])
            h_score = g['homeTeam']['score']
            a_score = g['awayTeam']['score']
            
            if h_score > a_score:
                msg += f"‏🏆 <b>{h_name} {h_score}</b>\n‏▫️ {a_name} {a_score}\n\n"
            else:
                msg += f"‏🏆 <b>{a_name} {a_score}</b>\n‏▫️ {h_name} {h_score}\n\n"
            found = True
    return msg if found else "‏🏀 <b>טרם הסתיימו משחקים הלילה.</b>"

def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    requests.post(url, data=payload, timeout=15)

# ==========================================
# לוגיקת ריצה
# ==========================================

def run():
    print(f"🚀 הבוט הופעל! לו\"ז ב-{SCHEDULE_TIME} | תוצאות ב-{RESULTS_TIME}")
    sent_s = sent_r = False
    
    while True:
        il_tz = pytz.timezone('Asia/Jerusalem')
        now = datetime.now(il_tz).strftime("%H:%M")
        
        if now == "00:00":
            sent_s = sent_r = False

        if now == SCHEDULE_TIME and not sent_s:
            try:
                data = requests.get(NBA_URL).json()
                games = data.get('scoreboard', {}).get('games', [])
                if games:
                    send_to_telegram(get_schedule_msg(games))
                    sent_s = True
            except Exception as e:
                print(f"Error Schedule: {e}")

        if now == RESULTS_TIME and not sent_r:
            try:
                data = requests.get(NBA_URL).json()
                games = data.get('scoreboard', {}).get('games', [])
                if games:
                    send_to_telegram(get_results_msg(games))
                    sent_r = True
            except Exception as e:
                print(f"Error Results: {e}")
        
        time.sleep(30)

if __name__ == "__main__":
    run()

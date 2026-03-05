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

SCHEDULE_TIME = "15:35"
RESULTS_TIME = "15:36"

TEAM_TRANSLATIONS = {
    "Atlanta Hawks": "אטלנטה הוקס", "Boston Celtics": "בוסטון סלטיקס",
    "Brooklyn Nets": "ברוקלין נטס", "Charlotte Hornets": "שארלוט הורנטס",
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
    "Portland Trail Blazers": "פורטלנד טרייל בלייזרס", "Sacramento Kings": "סקרמנטו קינגס",
    "San Antonio Spurs": "סן אנטוניו ספרס", "Toronto Raptors": "טורונטו ראפטורס",
    "Utah Jazz": "יוטה ג'אז", "Washington Wizards": "וושינגטון וויזארדס"
}

def translate_team(city, name, score=None):
    full = f"{city} {name}"
    base_name = TEAM_TRANSLATIONS.get(full, full)
    
    # סידור השורה עם דגל ישראל בסוף (מטפל בבעיית המספרים)
    if "Brooklyn" in full or "Portland" in full:
        if score is not None:
            return f"{base_name} {score} 🇮🇱"
        return f"{base_name} 🇮🇱"
    
    if score is not None:
        return f"{base_name} {score}"
    return base_name

def format_nba_time(time_str):
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
        # לוקח משחקים שטרם הסתיימו
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
            h_score = g['homeTeam']['score']
            a_score = g['awayTeam']['score']
            
            if h_score > a_score:
                win_text = translate_team(g['homeTeam']['teamCity'], g['homeTeam']['teamName'], h_score)
                lose_text = translate_team(g['awayTeam']['teamCity'], g['awayTeam']['teamName'], a_score)
                msg += f"‏🏆 <b>{win_text}</b>\n‏🔹 {lose_text}\n\n"
            else:
                win_text = translate_team(g['awayTeam']['teamCity'], g['awayTeam']['teamName'], a_score)
                lose_text = translate_team(g['homeTeam']['teamCity'], g['homeTeam']['teamName'], h_score)
                msg += f"‏🏆 <b>{win_text}</b>\n‏🔹 {lose_text}\n\n"
            found = True
    return msg if found else "‏🏀 <b>לא נמצאו תוצאות סופיות מהלילה.</b>"

def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, data=payload, timeout=15)
    except:
        pass

# ==========================================
# לוגיקת ריצה
# ==========================================

def run():
    print(f"🚀 בוט NBA פעיל. לו\"ז: {SCHEDULE_TIME} | תוצאות: {RESULTS_TIME}")
    sent_s = sent_r = False
    
    while True:
        il_tz = pytz.timezone('Asia/Jerusalem')
        now = datetime.now(il_tz).strftime("%H:%M")
        
        if now == "00:00":
            sent_s = sent_r = False

        if now == SCHEDULE_TIME and not sent_s:
            try:
                # קריאה ל-API
                resp = requests.get(NBA_URL, timeout=10).json()
                games = resp.get('scoreboard', {}).get('games', [])
                
                # אם ה-API ריק, מנסים שוב אחרי 5 שניות או שולחים הודעת שגיאה ללוג
                if not games:
                    print("⚠️ API returned empty games list")
                
                send_to_telegram(get_schedule_msg(games))
                sent_s = True
            except Exception as e:
                print(f"Error Schedule: {e}")

        if now == RESULTS_TIME and not sent_r:
            try:
                resp = requests.get(NBA_URL, timeout=10).json()
                games = resp.get('scoreboard', {}).get('games', [])
                send_to_telegram(get_results_msg(games))
                sent_r = True
            except Exception as e:
                print(f"Error Results: {e}")
        
        time.sleep(30)

if __name__ == "__main__":
    run()

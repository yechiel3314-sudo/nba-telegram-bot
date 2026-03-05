import requests
import time
import json
from datetime import datetime, timedelta

# ==========================================
# הגדרות מערכת (טוקנים ו-API)
# ==========================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# כאן תשאיר את מילוני התרגום שלך (NBA_TEAMS_HEBREW ו-NBA_PLAYERS_HEB)
# לצורך הקיצור, נשתמש בפונקציית התרגום הקיימת שלך
def translate_name(name):
    # הפונקציה שלך מהקוד הראשי (כולל Cache וגוגל)
    return name 

def format_nba_time(time_str):
    """המרה מזמן NBA (ET) לשעון ישראל"""
    try:
        # בדרך כלל ההפרש הוא 7 שעות קדימה לישראל
        dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ")
        dt_israel = dt + timedelta(hours=7) 
        return dt_israel.strftime("%H:%M")
    except:
        return "TBD"

# ==========================================
# פונקציות עיצוב ההודעות (כפי שביקשת)
# ==========================================

def get_schedule_msg(games):
    """הודעת לו"ז: שעה מודגשת ומתחתיה הקבוצות"""
    msg = "‏🏀 <b>לוח משחקי הלילה</b> 🏀\n\n"
    found = False
    for g in games:
        if g['gameStatus'] == 1: # משחק שטרם החל
            start_time = format_nba_time(g['gameEt'])
            home = translate_name(f"{g['homeTeam']['teamCity']} {g['homeTeam']['teamName']}")
            away = translate_name(f"{g['awayTeam']['teamCity']} {g['awayTeam']['teamName']}")
            
            msg += f"‏⏰ <b>{start_time}</b>\n"
            msg += f"‏🏀 {home} 🆚 {away}\n\n"
            found = True
    return msg if found else "‏🏀 <b>אין משחקים מתוכננים להלילה.</b>"

def get_results_msg(games):
    """הודעת תוצאות: מנצחת למעלה עם גביע, מפסידה עם נקודה"""
    msg = "‏🏀 <b>תוצאות משחקי הלילה</b> 🏀\n\n"
    found = False
    for g in games:
        if g['gameStatus'] == 3: # משחק שהסתיים
            h_name = translate_name(f"{g['homeTeam']['teamCity']} {g['homeTeam']['teamName']}")
            a_name = translate_name(f"{g['awayTeam']['teamCity']} {g['awayTeam']['teamName']}")
            h_score = g['homeTeam']['score']
            a_score = g['awayTeam']['score']
            
            if h_score > a_score:
                msg += f"‏🏆 <b>{h_name} {h_score}</b>\n‏🔹 {a_name} {a_score}\n\n"
            else:
                msg += f"‏🏆 <b>{a_name} {a_score}</b>\n‏🔹 {h_name} {h_score}\n\n"
            found = True
    return msg if found else "‏🏀 <b>טרם הסתיימו משחקים הלילה.</b>"

# ==========================================
# לוגיקת שליחה וזמנים
# ==========================================

def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, data=payload, timeout=15)
    except Exception as e:
        print(f"Error sending to Telegram: {e}")

def run_scheduler():
    print("🚀 בוט NBA (לוז ותוצאות) הופעל!")
    print("⏰ לו"ז יישלח ב-15:01 | תוצאות יישלחו ב-15:02")
    
    sent_schedule = False
    sent_results = False

    while True:
        now = datetime.now().strftime("%H:%M")
        
        # איפוס המערכת בחצות כדי שתוכל לשלוח שוב למחרת
        if now == "00:00":
            sent_schedule = False
            sent_results = False

        # שליחת לו"ז משחקים ב-15:01
        if now == "15:12" and not sent_schedule:
            try:
                resp = requests.get(NBA_URL, headers=HEADERS).json()
                games = resp.get('scoreboard', {}).get('games', [])
                msg = get_schedule_msg(games)
                send_to_telegram(msg)
                print(f"✅ לו\"ז נשלח ב-{now}")
                sent_schedule = True
            except:
                print("❌ שגיאה בשליפת לו\"ז")

        # שליחת תוצאות ב-15:02
        if now == "15:13" and not sent_results:
            try:
                resp = requests.get(NBA_URL, headers=HEADERS).json()
                games = resp.get('scoreboard', {}).get('games', [])
                msg = get_results_msg(games)
                send_to_telegram(msg)
                print(f"✅ תוצאות נשלחו ב-{now}")
                sent_results = True
            except:
                print("❌ שגיאה בשליפת תוצאות")

        time.sleep(30) # בדיקה כל חצי דקה

if __name__ == "__main__":
    run_scheduler()

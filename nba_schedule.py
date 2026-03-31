import requests
import time
import json
import os
from datetime import datetime, timedelta

# הגדרות בוט ו-API
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
STATE_FILE = "nba_bot_state.json"

# מילון שמות קבוצות מלא בעברית
TEAM_NAMES_HEB = {
    "Atlanta Hawks": "אטלנטה הוקס", "Boston Celtics": "בוסטון סלטיקס",
    "Brooklyn Nets": "ברוקלין נטס", "Charlotte Hornets": "שארלוט הורנטס",
    "Chicago Bulls": "שיקגו בולס", "Cleveland Cavaliers": "קליבלנד קאבלירס",
    "Dallas Mavericks": "דאלאס מאבריקס", "Denver Nuggets": "דנבר נאגטס",
    "Detroit Pistons": "דטרויט פיסטונס", "Golden State Warriors": "גולדן סטייט ווריירס",
    "Houston Rockets": "יוסטון רוקטס", "Indiana Pacers": "אינדיאנה פייסרס",
    "LA Clippers": "ל.א קליפרס", "Los Angeles Lakers": "ל.א לייקרס",
    "Memphis Grizzlies": "ממפיס גריזליס", "Miami Heat": "מיאמי היט",
    "Milwaukee Bucks": "מילווקי באקס", "Minnesota Timberwolves": "מינסוטה טימברוולבס",
    "New Orleans Pelicans": "ניו אורלינס פליקנס", "New York Knicks": "ניו יורק ניקס",
    "Oklahoma City Thunder": "אוקלהומה סיטי ת'אנדר", "Orlando Magic": "אורלנדו מג'יק",
    "Philadelphia 76ers": "פילדלפיה 76", "Phoenix Suns": "פיניקס סאנס",
    "Portland Trail Blazers": "פורטלנד טרייל בלייזרס", "Sacramento Kings": "סקרמנטו קינגס",
    "San Antonio Spurs": "סן אנטוניו ספרס", "Toronto Raptors": "טורונטו ראפטורס",
    "Utah Jazz": "יוטה ג'אז", "Washington Wizards": "וושינגטון וויזארדס"
}

def send_telegram_msg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error sending message: {e}")

def get_daily_schedule():
    url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
    try:
        response = requests.get(url).json()
        games = response.get('scoreboard', {}).get('games')
        
        if not games:
            return "🏀 אין משחקים מתוכננים להיום."
        
        msg = "🗓️ <b>לוח משחקי הלילה ב-NBA:</b>\n\n"
        
        for game in games:
            home = game['homeTeam']['teamName']
            away = game['awayTeam']['teamName']
            
            home_h = TEAM_NAMES_HEB.get(home, home)
            away_h = TEAM_NAMES_HEB.get(away, away)
            
            # עיבוד זמן המשחק
            game_time_str = game['gameEt'] # פורמט: 2024-03-30T19:00:00Z
            dt_utc = datetime.strptime(game_time_str, "%Y-%m-%dT%H:%M:%SZ")
            dt_israel = dt_utc + timedelta(hours=2)
            time_str = dt_israel.strftime("%H:%M")
            
            msg += f"⏰ {time_str} | {away_h} 🆚 {home_h}\n"
        
        msg += "\n<b>צפייה מהנה!</b> 🏀"
        return msg
    except Exception as e:
        print(f"Schedule error: {e}")
        return "⚠️ תקלה במשיכת לוח המשחקים."

def monitor_nba():
    print("NBA Monitor Started...")
    sent_today = False
    last_date = ""

    while True:
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        current_date = now.strftime("%Y-%m-%d")

        # איפוס המשתנה ביום חדש
        if current_date != last_date:
            sent_today = False
            last_date = current_date

        # שליחה ב-18:00
        if current_time == "18:00" and not sent_today:
            print("Sending daily schedule...")
            schedule_msg = get_daily_schedule()
            send_telegram_msg(schedule_msg)
            sent_today = True
            time.sleep(60)

        # המתנה קצרה כדי לא להעמיס על המעבד
        time.sleep(30)

if __name__ == "__main__":
    monitor_nba()

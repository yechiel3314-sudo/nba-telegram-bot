import requests
import time
from datetime import datetime, timedelta

# הגדרות בוט
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# מילון שמות קבוצות (גרסה מקוצרת להדגמה, בקוד המלא שלך היו כל ה-30)
TEAM_NAMES_HEB = {
    "Atlanta Hawks": "אטלנטה הוקס", "Boston Celtics": "בוסטון סלטיקס",
    "Brooklyn Nets": "ברוקלין נטס", "Portland Trail Blazers": "פורטלנד טרייל בלייזרס",
    "Washington Wizards": "וושינגטון וויזארדס", "Milwaukee Bucks": "מילווקי באקס",
    "LA Clippers": "לוס אנג'לס קליפרס", "Indiana Pacers": "אינדיאנה פייסרס",
    "Sacramento Kings": "סקרמנטו קינגס", "Charlotte Hornets": "שארלוט הורנטס",
    "Orlando Magic": "אורלנדו מג'יק", "Toronto Raptors": "טורונטו ראפטורס",
    "Houston Rockets": "יוסטון רוקטס", "New Orleans Pelicans": "ניו אורלינס פליקנס",
    "New York Knicks": "ניו יורק ניקס", "Oklahoma City Thunder": "אוקלהומה סיטי ת'אנדר",
    "Golden State Warriors": "גולדן סטייט ווריורס", "Denver Nuggets": "דנבר נאגטס"
}

# קבוצות עם שחקנים ישראלים (דני אבדיה, בן שרף, דני וולף)
ISRAELI_TEAMS = ["Portland Trail Blazers", "Brooklyn Nets", "Washington Wizards"]

def get_formatted_nba_schedule():
    url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
    try:
        response = requests.get(url).json()
        games = response.get('scoreboard', {}).get('games', [])
        
        if not games:
            return "🏀 אין משחקים מתוכננים להיום."
        
        # העיצוב המדויק שביקשת
        msg = "🏀 ══ לוח משחקי הלילה ב NBA ══ 🏀\n\n"
        
        for game in games:
            home = game['homeTeam']['teamName']
            away = game['awayTeam']['teamName']
            
            home_h = TEAM_NAMES_HEB.get(home, home)
            away_h = TEAM_NAMES_HEB.get(away, away)
            
            # הוספת דגל ישראל לקבוצות הרלוונטיות
            flag = " 🇮🇱" if home in ISRAELI_TEAMS or away in ISRAELI_TEAMS else ""
            
            # המרת זמן ל-Israel Time (שימוש ב-2 שעות הפרש או 3 לפי העונה)
            dt_utc = datetime.strptime(game['gameEt'], "%Y-%m-%dT%H:%M:%SZ")
            dt_israel = dt_utc + timedelta(hours=2) 
            time_str = dt_israel.strftime("%H:%M")
            
            # בניית המבנה: שעה בשורה אחת, משחק בשורה מתחת עם אמוג'י
            msg += f"‏⏰ {time_str}\n"
            msg += f"‏🏀 ‏{away_h} 🆚 ‏{home_h}{flag}\n\n"
        
        return msg
    except Exception as e:
        print(f"Error: {e}")
        return "⚠️ תקלה במשיכת לוח המשחקים."

def run_bot():
    print("NBA Schedule Bot is active...")
    sent_today = False
    last_date = ""

    while True:
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        current_date = now.strftime("%Y-%m-%d")

        if current_date != last_date:
            sent_today = False
            last_date = current_date

        # כאן הלוגיקה המקורית - שליחה ב-18:00 בדיוק
        if current_time == "20:28" and not sent_today:
            message = get_formatted_nba_schedule()
            
            # שליחת ההודעה לטלגרם
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
            requests.post(url, json=payload)
            
            sent_today = True
            print(f"Schedule sent successfully at {current_time}")
            
        time.sleep(30)

if __name__ == "__main__":
    run_bot()

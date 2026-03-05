import requests
import time
from datetime import datetime, timedelta

# ==========================================
# הגדרות וטוקנים
# ==========================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"

# שעות שליחה מעודכנות
SCHEDULE_TIME = "15:20"
RESULTS_TIME = "15:21"

# מילון תרגום קבוצות
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

def translate_team(full_name):
    return TEAM_TRANSLATIONS.get(full_name, full_name)

def format_nba_time(time_str):
    """המרה לשעון ישראל (UTC+7)"""
    try:
        dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ")
        dt_israel = dt + timedelta(hours=7) 
        return dt_israel.strftime("%H:%M")
    except:
        return "TBD"

# ==========================================
# פונקציות הודעות
# ==========================================

def get_schedule_msg(games):
    msg = "‏🏀 <b>לוח משחקי הלילה</b> 🏀\n\n"
    found = False
    for g in games:
        if g['gameStatus'] == 1:
            home = translate_team(f"{g['homeTeam']['teamCity']} {g['homeTeam']['teamName']}")
            away = translate_team(f"{g['awayTeam']['teamCity']} {g['awayTeam']['teamName']}")
            start_time = format_nba_time(g['gameEt'])
            msg += f"‏⏰ <b>{start_time}</b>\n‏🏀 {home} 🆚 {away}\n\n"
            found = True
    return msg if found else "‏🏀 <b>אין משחקים מתוכננים להלילה.</b>"

def get_results_msg(games):
    msg = "‏🏀 <b>תוצאות משחקי הלילה</b> 🏀\n\n"
    found = False
    for g in games:
        if g['gameStatus'] == 3:
            h_name = translate_team(f"{g['homeTeam']['teamCity']} {g['homeTeam']['teamName']}")
            a_name = translate_team(f"{g['awayTeam']['teamCity']} {g['awayTeam']['teamName']}")
            h_score = g['homeTeam']['score']
            a_score = g['awayTeam']['score']
            
            if h_score > a_score:
                msg += f"‏🏆 <b>{h_name} {h_score}</b>\n‏🔹 {a_name} {a_score}\n\n"
            else:
                msg += f"‏🏆 <b>{a_name} {a_score}</b>\n‏🔹 {h_name} {h_score}\n\n"
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
    print(f"🚀 הבוט הופעל! לו\"ז: {SCHEDULE_TIME} | תוצאות: {RESULTS_TIME}")
    sent_s = False
    sent_r = False
    
    while True:
        now = datetime.now().strftime("%H:%M")
        
        # איפוס יומי בחצות
        if now == "00:00":
            sent_s = False
            sent_r = False

        # שליחת לו"ז
        if now == SCHEDULE_TIME and not sent_s:
            try:
                data = requests.get(NBA_URL).json()
                send_to_telegram(get_schedule_msg(data['scoreboard']['games']))
                print(f"✅ לו\"ז נשלח ב-{now}")
                sent_s = True
            except:
                print("❌ שגיאה בשליפת לו\"ז")

        # שליחת תוצאות
        if now == RESULTS_TIME and not sent_r:
            try:
                data = requests.get(NBA_URL).json()
                send_to_telegram(get_results_msg(data['scoreboard']['games']))
                print(f"✅ תוצאות נשלחו ב-{now}")
                sent_r = True
            except:
                print("❌ שגיאה בשליפת תוצאות")
        
        time.sleep(20)

if __name__ == "__main__":
    run()

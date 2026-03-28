import requests
import time
import pytz
from datetime import datetime

# ==========================================
# הגדרות
# ==========================================

TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# ה-API המרכזי לתוצאות חיות
NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"

RESULTS_TIME = "09:00"    # זמן שליחת התוצאות

# ==========================================
# לוג
# ==========================================

def log(msg):
    tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(tz).strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

# ==========================================
# תרגום קבוצות
# ==========================================

TEAM_TRANSLATIONS = {
    "Atlanta Hawks":"אטלנטה הוקס",
    "Boston Celtics":"בוסטון סלטיקס",
    "Brooklyn Nets":"ברוקלין נטס",
    "Charlotte Hornets":"שארלוט הורנטס",
    "Chicago Bulls":"שיקגו בולס",
    "Cleveland Cavaliers":"קליבלנד קאבלירס",
    "Dallas Mavericks":"דאלאס מאבריקס",
    "Denver Nuggets":"דנבר נאגטס",
    "Detroit Pistons":"דטרויט פיסטונס",
    "Golden State Warriors":"גולדן סטייט ווריורס",
    "Houston Rockets":"יוסטון רוקטס",
    "Indiana Pacers":"אינדיאנה פייסרס",
    "LA Clippers":"לוס אנג'לס קליפרס",
    "Los Angeles Lakers":"לוס אנג'לס לייקרס",
    "Memphis Grizzlies":"ממפיס גריזליס",
    "Miami Heat":"מיאמי היט",
    "Milwaukee Bucks":"מילווקי באקס",
    "Minnesota Timberwolves":"מינסוטה טימברוולבס",
    "New Orleans Pelicans":"ניו אורלינס פליקנס",
    "New York Knicks":"ניו יורק ניקס",
    "Oklahoma City Thunder":"אוקלהומה סיטי ת'אנדר",
    "Orlando Magic":"אורלנדו מג'יק",
    "Philadelphia 76ers":"פילדלפיה 76",
    "Phoenix Suns":"פיניקס סאנס",
    "Portland Trail Blazers":"פורטלנד טרייל בלייזרס",
    "Sacramento Kings":"סקרמנטו קינגס",
    "San Antonio Spurs":"סן אנטוניו ספרס",
    "Toronto Raptors":"טורונטו ראפטורס",
    "Utah Jazz":"יוטה ג'אז",
    "Washington Wizards":"וושינגטון וויזארדס"
}

def translate_team(city, name, score=None):
    full = f"{city} {name}" if name else city
    base = TEAM_TRANSLATIONS.get(full, full)

    is_special = "Portland" in full or "Brooklyn" in full
    flag = " 🇮🇱" if is_special else ""

    if score is not None:
        return f"{base} {score}{flag}"
    return f"{base}{flag}"

# ==========================================
# שליפת משחקים
# ==========================================

def get_games():
    log("מבקש נתונים מה-API לצורך תוצאות")
    try:
        resp = requests.get(f"{NBA_URL}?cache={int(time.time())}", timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            games = data.get("scoreboard", {}).get("games", [])
            return games
    except Exception as e:
        log(f"שגיאה קריטית בשליפה: {e}")
    return []

# ==========================================
# בניית הודעת תוצאות
# ==========================================

def get_results_msg(games):
    log("בונה הודעת תוצאות")
    msg = "🏀 <b>תוצאות משחקי הלילה ב NBA</b> 🏀\n\n"
    found = False
    
    if not games:
        return None

    for g in games:
        # סטטוס 3 מסמל משחק שהסתיים
        if g["gameStatus"] == 3:
            h_score = int(g["homeTeam"]["score"])
            a_score = int(g["awayTeam"]["score"])

            if h_score > a_score:
                win = translate_team(g["homeTeam"]["teamCity"], g["homeTeam"]["teamName"], h_score)
                lose = translate_team(g["awayTeam"]["teamCity"], g["awayTeam"]["teamName"], a_score)
            else:
                win = translate_team(g["awayTeam"]["teamCity"], g["awayTeam"]["teamName"], a_score)
                lose = translate_team(g["homeTeam"]["teamCity"], g["homeTeam"]["teamName"], h_score)

            msg += f"🏆 <b>{win}</b>\n🔹 {lose}\n\n"
            found = True

    return msg if found else None

# ==========================================
# שליחה לטלגרם
# ==========================================

def send_to_telegram(text):
    if not text: return
    log("שולח הודעה לטלגרם")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
        if r.status_code == 200: 
            log("נשלח בהצלחה")
        else: 
            log(f"שגיאת טלגרם: {r.text}")
    except Exception as e: 
        log(f"שגיאה בשליחה: {e}")

# ==========================================
# לולאה ראשית
# ==========================================

def run():
    log("NBA RESULTS BOT STARTED - RESULTS ONLY MODE")
    tz = pytz.timezone("Asia/Jerusalem")
    last_results_date = None

    while True:
        now = datetime.now(tz)
        current_time = now.strftime("%H:%M")
        today = now.date()

        # בדיקה אם הגיעה השעה לשלוח תוצאות ואם עדיין לא שלחנו היום
        if current_time == RESULTS_TIME and last_results_date != today:
            games = get_games()
            msg = get_results_msg(games)
            if msg:
                send_to_telegram(msg)
                last_results_date = today
                log(f"הודעת תוצאות יומית הושלמה עבור {today}")
            else:
                log("לא נמצאו משחקים שהסתיימו לשליחה")
                # נסמן שבוצעה בדיקה כדי לא לנסות כל 30 שניות בתוך דקת היעד
                last_results_date = today
            
            time.sleep(65) # השהייה כדי למנוע כפילויות בתוך אותה דקה

        time.sleep(30)

if __name__ == "__main__":
    run()

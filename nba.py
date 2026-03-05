import requests
import time
import pytz
import sys
from datetime import datetime, date, timedelta

# ==========================================
# 1. הגדרות וטוקנים
# ==========================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# API מקורות
NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
NBA_SCHEDULE_FULL = "https://data.nba.com/data/10s/v2015/json/mobile/composer/nba/schedules/main_schedule.json"

SCHEDULE_TIME = "01:34"
RESULTS_TIME = "01:34"

# ==========================================
# 2. מערכת לוגים (מתוקנת - מונעת קריסה)
# ==========================================
def log(msg):
    tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(tz).strftime("%H:%M:%S")
    print(f"[{now}] {msg}")
    sys.stdout.flush()

# ==========================================
# 3. מילון כוכבים (פוסטרים)
# ==========================================
STARS_POSTERS = {
    "Lakers": "https://piks.eldesmarque.com/bin/2023/10/25/lebron_james_entrenamiento_lakers.jpg",
    "Warriors": "https://e00-marca.ad.james.net/assets/multimedia/imagenes/2023/05/11/16837943586073.jpg",
    "Nuggets": "https://hoopshype.com/wp-content/uploads/sites/92/2023/06/jokic_finals.jpg",
    "Mavericks": "https://nbatitlechase.com/wp-content/uploads/2023/02/Luka-Doncic-Kyrie-Irving-Dallas-Mavericks.jpg",
    "Celtics": "https://www.si.com/.image/t_share/MTk4MjgyOTk1OTY5MTc5NTI2/jayson-tatum-jaylen-brown.jpg",
    "Bucks": "https://images2.minutemediacdn.com/image/upload/c_crop,w_5342,h_3004,x_0,y_0/c_fill,w_1440,ar_16:9,f_auto,q_auto,g_auto/images/mmsport/6/01hcbmf7j6hbmwre33y6.jpg"
}

# ==========================================
# 4. תרגום קבוצות
# ==========================================
TEAM_TRANSLATIONS = {
    "Atlanta Hawks":"אטלנטה הוקס", "Boston Celtics":"בוסטון סלטיקס",
    "Brooklyn Nets":"ברוקלין נטס", "Charlotte Hornets":"שארלוט הורנטס",
    "Chicago Bulls":"שיקגו בולס", "Cleveland Cavaliers":"קליבלנד קאבלירס",
    "Dallas Mavericks":"דאלאס מאבריקס", "Denver Nuggets":"דנבר נאגטס",
    "Detroit Pistons":"דטרויט פיסטונס", "Golden State Warriors":"גולדן סטייט",
    "Houston Rockets":"יוסטון רוקטס", "Indiana Pacers":"אינדיאנה פייסרס",
    "LA Clippers":"לוס אנג'לס קליפרס", "Los Angeles Lakers":"לוס אנג'לס לייקרס",
    "Memphis Grizzlies":"ממפיס גריזליס", "Miami Heat":"מיאמי היט",
    "Milwaukee Bucks":"מילווקי באקס", "Minnesota Timberwolves":"מינסוטה טימברוולבס",
    "New Orleans Pelicans":"ניו אורלינס פליקנס", "New York Knicks":"ניו יורק ניקס",
    "Oklahoma City Thunder":"אוקלהומה סיטי", "Orlando Magic":"אורלנדו מג'יק",
    "Philadelphia 76ers":"פילדלפיה 76", "Phoenix Suns":"פיניקס סאנס",
    "Portland Trail Blazers":"פורטלנד טרייל בלייזרס", "Sacramento Kings":"סקרמנטו קינגס",
    "San Antonio Spurs":"סן אנטוניו ספרס", "Toronto Raptors":"טורונטו ראפטורס",
    "Utah Jazz":"יוטה ג'אז", "Washington Wizards":"וושינגטון וויזארדס"
}

def translate_team(city, name, score=None):
    full = f"{city} {name}" if name else city
    base = TEAM_TRANSLATIONS.get(full, full)
    flag = " 🇮🇱" if "Portland" in full or "Brooklyn" in full else ""
    if score is not None:
        return f"{base} {score}{flag}"
    return f"{base}{flag}"

# ==========================================
# 5. פונקציות עזר (זמן ושליפה)
# ==========================================
def format_nba_time(time_str):
    try:
        if 'T' in time_str:
            utc_dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
        else:
            utc_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M").replace(tzinfo=pytz.utc)
        israel = pytz.timezone("Asia/Jerusalem")
        return utc_dt.astimezone(israel).strftime("%H:%M")
    except: return "TBD"

def get_games():
    log("שולף נתונים מ-NBA CDN...")
    try:
        resp = requests.get(f"{NBA_URL}?t={int(time.time())}", timeout=15)
        if resp.status_code == 200:
            games = resp.json().get("scoreboard", {}).get("games", [])
            if games: return games
        
        log("API יומי ריק, עובר ללו"ז שנתי...")
        resp_full = requests.get(NBA_SCHEDULE_FULL, timeout=15)
        if resp_full.status_code == 200:
            tz = pytz.timezone("Asia/Jerusalem")
            today_str = datetime.now(tz).strftime("%Y%m%d")
            backup = []
            for month in resp_full.json()['league']['schedules']:
                for g in month['games']:
                    if g['gameDate'] == today_str:
                        backup.append({
                            "gameStatus": 1,
                            "homeTeam": {"teamCity": g['hTeam']['city'], "teamName": g['hTeam']['name'], "score": "0"},
                            "awayTeam": {"teamCity": g['vTeam']['city'], "teamName": g['vTeam']['name'], "score": "0"},
                            "gameEt": g['utctimeUtc']
                        })
            return backup
    except Exception as e: log(f"שגיאת שליפה: {e}")
    return []

# ==========================================
# 6. שליחה לטלגרם (תומך בתמונות)
# ==========================================
def send_telegram(text, photo=None):
    if not text: return
    if photo:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        data = {"chat_id": CHAT_ID, "photo": photo, "caption": text, "parse_mode": "HTML"}
    else:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try: requests.post(url, data=data, timeout=15)
    except Exception as e: log(f"שגיאת טלגרם: {e}")

# ==========================================
# 7. לוגיקת הודעות
# ==========================================
def process_schedule(games):
    log("מעבד לוח משחקים...")
    if not games: 
        send_telegram("🏀 <b>לוח משחקים</b> 🏀\nאין משחקים הלילה.")
        return

    for g in games:
        if g["gameStatus"] != 3:
            home_city = g["homeTeam"]["teamCity"]
            home_name = g["homeTeam"]["teamName"]
            home_translated = translate_team(home_city, home_name)
            away_translated = translate_team(g["awayTeam"]["teamCity"], g["awayTeam"]["teamName"])
            start = format_nba_time(g["gameEt"])
            
            poster = STARS_POSTERS.get(home_name)
            msg = f"⏰ <b>{start}</b>\n🏀 {away_translated} 🆚 {home_translated}"
            send_telegram(msg, photo=poster)

def process_results(games):
    log("מעבד תוצאות...")
    msg = "🏀 <b>תוצאות משחקי הלילה</b> 🏀\n\n"
    found = False
    for g in games:
        if g["gameStatus"] == 3:
            h_score = int(g["homeTeam"].get("score", 0))
            a_score = int(g["awayTeam"].get("score", 0))
            if h_score > a_score:
                win = translate_team(g["homeTeam"]["teamCity"], g["homeTeam"]["teamName"], h_score)
                lose = translate_team(g["awayTeam"]["teamCity"], g["awayTeam"]["teamName"], a_score)
            else:
                win = translate_team(g["awayTeam"]["teamCity"], g["awayTeam"]["teamName"], a_score)
                lose = translate_team(g["homeTeam"]["teamCity"], g["homeTeam"]["teamName"], h_score)
            msg += f"🏆 <b>{win}</b>\n🔹 {lose}\n\n"
            found = True
    
    if not found: msg += "🏁 לא נמצאו תוצאות סופיות כרגע."
    send_telegram(msg)

# ==========================================
# 8. הרצה ראשית
# ==========================================
def run():
    log("המערכת התחילה לפעול...")
    tz = pytz.timezone("Asia/Jerusalem")
    l_sch, l_res = None, None

    while True:
        try:
            now = datetime.now(tz)
            clock = now.strftime("%H:%M")
            day = now.date()

            if clock == SCHEDULE_TIME and l_sch != day:
                log(f"זמן לו''ז: {SCHEDULE_TIME}") # תיקון המירכאות שגרם לקריסה
                process_schedule(get_games())
                l_sch = day
                time.sleep(65)

            if clock == RESULTS_TIME and l_res != today:
                log(f"זמן תוצאות: {RESULTS_TIME}")
                process_results(get_games())
                l_res = day
                time.sleep(65)

            time.sleep(30)
        except Exception as e:
            log(f"שגיאת לולאה: {e}")
            time.sleep(20)

if __name__ == "__main__":
    run()

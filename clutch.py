import requests
import time

# ==============================
# הגדרות טלגרם
# ==============================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

def send_telegram_message(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }

    try:
        response = requests.post(url, json=payload, timeout=10)

        if response.status_code == 200:
            print("✅ הודעה נשלחה בהצלחה לטלגרם")
        else:
            print(f"❌ שגיאה בשליחה לטלגרם: {response.status_code}")
            print(response.text)

    except Exception as e:
        print(f"❌ שגיאה בשליחה לטלגרם: {e}")


# ==============================
# ESPN NBA SCOREBOARD
# ==============================
NBA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
RTL = "\u200f"

# ==============================
# תרגום שמות קבוצות
# ==============================
TEAM_FIXES = {
    "Atlanta Hawks": "אטלנטה הוקס",
    "Boston Celtics": "בוסטון סלטיקס",
    "Brooklyn Nets": "ברוקלין נטס",
    "Charlotte Hornets": "שארלוט הורנטס",
    "Chicago Bulls": "שיקגו בולס",
    "Cleveland Cavaliers": "קליבלנד קאבלירס",
    "Dallas Mavericks": "דאלאס מאבריקס",
    "Denver Nuggets": "דנבר נאגטס",
    "Detroit Pistons": "דטרויט פיסטונס",
    "Golden State Warriors": "גולדן סטייט ווריורס",
    "Houston Rockets": "יוסטון רוקטס",
    "Indiana Pacers": "אינדיאנה פייסרס",
    "LA Clippers": "לוס אנג'לס קליפרס",
    "Los Angeles Clippers": "לוס אנג'לס קליפרס",
    "Los Angeles Lakers": "לוס אנג'לס לייקרס",
    "Memphis Grizzlies": "ממפיס גריזליס",
    "Miami Heat": "מיאמי היט",
    "Milwaukee Bucks": "מילווקי באקס",
    "Minnesota Timberwolves": "מינסוטה טימברוולבס",
    "New Orleans Pelicans": "ניו אורלינס פליקנס",
    "New York Knicks": "ניו יורק ניקס",
    "Oklahoma City Thunder": "אוקלהומה סיטי ת'אנדר",
    "Orlando Magic": "אורלנדו מג'יק",
    "Philadelphia 76ers": "פילדלפיה 76",
    "Phoenix Suns": "פיניקס סאנס",
    "Portland Trail Blazers": "פורטלנד טרייל בלייזרס",
    "Sacramento Kings": "סקרמנטו קינגס",
    "San Antonio Spurs": "סן אנטוניו ספרס",
    "Toronto Raptors": "טורונטו ראפטורס",
    "Utah Jazz": "יוטה ג'אז",
    "Washington Wizards": "וושינגטון וויזארדס"
}

def tr_name(text: str) -> str:
    return TEAM_FIXES.get(text, text)

def clock_to_seconds(clock: str):
    try:
        if ":" not in clock:
            return None
        mm, ss = clock.split(":")
        return int(mm) * 60 + int(ss)
    except:
        return None

def get_competitors(event: dict):
    competition = event.get("competitions", [{}])[0]
    competitors = competition.get("competitors", [])
    if len(competitors) < 2:
        return None, None

    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)

    if away is None or home is None:
        away = competitors[0]
        home = competitors[1]

    return away, home


# ==============================
# זיכרון התראות
# ==============================
sent_clutch = {}
sent_last45 = {}


# ==============================
# בניית הודעה
# ==============================
def build_message(event: dict, alert_type: str):
    status = event.get("status", {})
    status_type = status.get("type", {})

    if status_type.get("state") != "in":
        return None

    clock = status.get("displayClock", "")
    away, home = get_competitors(event)
    if not away or not home:
        return None

    try:
        away_name = tr_name(away["team"]["displayName"])
        home_name = tr_name(home["team"]["displayName"])
        away_score = int(away["score"])
        home_score = int(home["score"])
    except:
        return None

    if away_score > home_score:
        leader_name = away_name
        score_line = f"{away_score} - {home_score}"
    elif home_score > away_score:
        leader_name = home_name
        score_line = f"{home_score} - {away_score}"
    else:
        leader_name = "שוויון"
        score_line = f"{away_score} - {home_score}"

    if alert_type == "clutch":
        title = "🚨 <b>התראת קלאץ'!</b> 🚨"
        ending = "✨ <b>הכל יכול להתהפך עכשיו!</b> ✨"
    else:
        title = "🚨 <b>התראת קלאץ! דקה אחרונה</b> 🚨"
        ending = "⏳ <b>כל מהלך עכשיו מכריע!</b> ⏳"

    msg = ""
    msg += f"{RTL}{title}\n\n"
    msg += f"{RTL}🏀 <b>{away_name} 🆚 {home_name}</b> 🏀\n\n"

    if leader_name == "שוויון":
        msg += f"{RTL}🔥 <b>שוויון {score_line}</b> 🔥\n\n"
    else:
        msg += f"{RTL}🔥 <b>{leader_name} מובילה {score_line}</b> 🔥\n\n"

    msg += f"{RTL}⏱️ <b>זמן לסיום:</b> {clock}\n\n"
    msg += f"{RTL}{ending}"

    return msg


# ==============================
# בדיקת התראות
# ==============================
def check_all_nba_clutch():
    try:
        resp = requests.get(NBA_SCOREBOARD, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        for event in data.get("events", []):
            status = event.get("status", {})
            status_type = status.get("type", {})

            if status_type.get("state") != "in":
                continue

            game_id = event.get("id")
            period = status.get("period", 0)
            clock = status.get("displayClock", "")

            clock_seconds = clock_to_seconds(clock)
            if clock_seconds is None:
                continue

            away, home = get_competitors(event)
            if not away or not home:
                continue

            try:
                score1 = int(away["score"])
                score2 = int(home["score"])
            except:
                continue

            diff = abs(score1 - score2)

            # =========================
            # 45 שניות אחרונות - תמיד
            # =========================
            if period >= 4 and clock_seconds <= 45 and not sent_last45.get(game_id):
                msg = build_message(event, "last45")
                if msg:
                    send_telegram_message(msg)
                    sent_last45[game_id] = True
                    time.sleep(1)

            # =========================
            # קלאץ' - רק אם המשחק צמוד
            # ורק מ-3:30 דקות לסיום
            # =========================
            if diff <= 3 and period == 4 and clock_seconds <= 210 and not sent_clutch.get(game_id):
                msg = build_message(event, "clutch")
                if msg:
                    send_telegram_message(msg)
                    sent_clutch[game_id] = True
                    time.sleep(1)

    except Exception as e:
        print(f"❌ שגיאה כללית: {e}")


# ==============================
# לולאה ראשית
# ==============================
if __name__ == "__main__":
    print("🚀 הבוט התחיל לעבוד...")

    while True:
        check_all_nba_clutch()
        time.sleep(5)

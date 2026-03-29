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


# ==============================
# זיכרון התראות שנשלחו
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

    competition = event.get("competitions", [{}])[0]
    competitors = competition.get("competitors", [])

    if len(competitors) < 2:
        return None

    away = None
    home = None

    for comp in competitors:
        if comp.get("homeAway") == "away":
            away = comp
        elif comp.get("homeAway") == "home":
            home = comp

    if not away or not home:
        away = competitors[0]
        home = competitors[1]

    away_name = tr_name(away["team"]["displayName"])
    home_name = tr_name(home["team"]["displayName"])

    try:
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

    # כותרת + סיום לפי סוג התראה
    if alert_type == "clutch":
        title = "🚨 <b>התראת קלאץ'!</b> 🚨"
        ending = "⚡ <b>הכל יכול להתהפך עכשיו!</b>"
    elif alert_type == "last45":
        title = "🚨 <b>התראת קלאץ' שניות אחרונות!</b> 🚨"
        ending = "⏳ <b>כל מהלך עכשיו מכריע!</b>"
    else:
        return None

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
        data = resp.json()

        for event in data.get("events", []):
            status = event.get("status", {})
            status_type = status.get("type", {})

            # רק משחקים חיים
            if status_type.get("state") != "in":
                continue

            game_id = event.get("id")
            period = status.get("period")
            clock = status.get("displayClock", "")

            clock_seconds = clock_to_seconds(clock)
            if clock_seconds is None:
                continue

            competition = event.get("competitions", [{}])[0]
            competitors = competition.get("competitors", [])

            if len(competitors) < 2:
                continue

            try:
                score1 = int(competitors[0]["score"])
                score2 = int(competitors[1]["score"])
            except:
                continue

            diff = abs(score1 - score2)

            # רק משחק צמוד
            if diff > 3:
                continue

            # =========================
            # 1) התראת קלאץ' רגילה
            # רק רבע 4 (לא הארכה)
            # פחות מ-4 דקות
            # =========================
            if period == 4 and clock_seconds < 240 and not sent_clutch.get(game_id):
                msg = build_message(event, "clutch")
                if msg:
                    send_telegram_message(msg)
                    sent_clutch[game_id] = True

                    print("=" * 80)
                    print("🚨 נשלחה התראת קלאץ'")
                    print(msg)
                    print("=" * 80)

            # =========================
            # 2) התראת שניות אחרונות
            # רבע 4 או הארכה
            # 45 שניות או פחות
            # =========================
            if period >= 4 and clock_seconds <= 45 and not sent_last45.get(game_id):
                msg = build_message(event, "last45")
                if msg:
                    send_telegram_message(msg)
                    sent_last45[game_id] = True

                    print("=" * 80)
                    print("⏳ נשלחה התראת שניות אחרונות")
                    print(msg)
                    print("=" * 80)

    except Exception as e:
        print(f"❌ שגיאה כללית: {e}")


# ==============================
# לולאה ראשית
# ==============================
if __name__ == "__main__":
    print("🚀 הבוט התחיל לעבוד...")

    while True:
        check_all_nba_clutch()
        time.sleep(10)

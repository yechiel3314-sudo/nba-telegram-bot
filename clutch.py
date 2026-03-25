import requests
import time

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
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"שגיאה בשליחה לטלגרם: {e}")

NBA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
RTL = "\u200f"

# 🏀 כל 30 הקבוצות מתורגמות
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

sent_clutch = {}

def build_clutch_message(event: dict):
    status = event.get("status", {})
    status_type = status.get("type", {})

    # רק משחקים חיים
    if status_type.get("state") != "in":
        return None

    game_id = event.get("id")
    period = status.get("period")
    clock = status.get("displayClock", "")

    clock_seconds = clock_to_seconds(clock)
    if clock_seconds is None:
        return None

    # קלאץ' = רבע 4 או הארכה + פחות מ-4 דקות
    if period < 4 or clock_seconds >= 240:
        return None

    # מניעת ספאם (רק פעם אחת לכל משחק)
    if sent_clutch.get(game_id):
        return None

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

    diff = abs(away_score - home_score)

    # רק משחק צמוד
    if diff > 3:
        return None

    # סימון שנשלח
    sent_clutch[game_id] = True

    if away_score > home_score:
        leader_name = away_name
        score_line = f"{away_score} - {home_score}"
    elif home_score > away_score:
        leader_name = home_name
        score_line = f"{home_score} - {away_score}"
    else:
        leader_name = "שוויון"
        score_line = f"{away_score} - {home_score}"

    msg = ""
    msg += f"{RTL}🚨 <b>התראת קלאץ'!</b> 🚨\n"
    msg += f"{RTL}🏀 <b>{away_name} 🆚 {home_name}</b> 🏀\n\n"

    if leader_name == "שוויון":
        msg += f"{RTL}🔥 <b>שוויון {score_line}</b> 🔥\n\n"
    else:
        msg += f"{RTL}🔥 <b>{leader_name} מובילה {score_line}</b> 🔥\n\n"

    msg += f"{RTL}⏱️ <b>זמן לסיום:</b> {clock}\n\n"
    msg += f"{RTL}🚨 <b>כנסו עכשיו למשחק!</b>"

    return msg

def check_all_nba_clutch():
    try:
        resp = requests.get(NBA_SCOREBOARD, timeout=10)
        data = resp.json()

        for event in data.get("events", []):
            msg = build_clutch_message(event)
            if msg:
                send_telegram_message(msg)

                print("=" * 80)
                print(msg)
                print("=" * 80)

    except Exception as e:
        print(f"שגיאה: {e}")

# 🔁 בדיקה כל 10 שניות
if __name__ == "__main__":
    while True:
        check_all_nba_clutch()
        time.sleep(10)

import requests
import time
import pytz
import sys
import json
from datetime import datetime, date, timedelta

# ==============================================================================
# 1. הגדרות מערכת וטוקנים - הגדרות יציבות ל-Railway
# ==============================================================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# זמני שליחה מעודכנים לבדיקה מיידית
RESULTS_TIME = "01:43"   
SCHEDULE_TIME = "01:43"  

# מקורות נתונים רשמיים
NBA_API_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
NBA_BACKUP_URL = "https://data.nba.com/data/10s/v2015/json/mobile/composer/nba/schedules/main_schedule.json"

# ==============================================================================
# 2. מערכת לוגים מפורטת לכל שלב (Log System)
# ==============================================================================
def log_step(step_number, message):
    """מדפיס לוג ממוספר ומפורט לניטור ב-Railway"""
    tz_isr = pytz.timezone("Asia/Jerusalem")
    current_time = datetime.now(tz_isr).strftime("%H:%M:%S")
    full_log = f"[{current_time}] >> שלב {step_number}: {message}"
    print(full_log)
    sys.stdout.flush()

# ==============================================================================
# 3. מילון תרגומים מלא ויישור טקסט (RTL)
# ==============================================================================
TEAM_MAP = {
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

def translate_team_rtl(city, name, score=None):
    """מתרגם ומסדר את הטקסט מימין לשמאל עם דגשים"""
    full_en = f"{city} {name}" if name else city
    translated = TEAM_MAP.get(full_en, full_en)
    
    # הוספת דגל לקבוצות עם זיקה ישראלית
    special_flag = " 🇮🇱" if "Portland" in full_en or "Brooklyn" in full_en else ""
    
    if score is not None:
        # בפורמט תוצאה: השם קודם, אז הניקוד
        return f"<b>{translated}</b> {score}{special_flag}"
    return f"<b>{translated}</b>{special_flag}"

# ==============================================================================
# 4. ניהול זמנים והמרות (שעון ישראל)
# ==============================================================================
def get_israel_time(utc_string):
    """ממירה זמן UTC לשעון ישראל בצורה תקינה (HH:MM)"""
    try:
        if 'T' in utc_string:
            dt = datetime.strptime(utc_string, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
        else:
            dt = datetime.strptime(utc_string, "%Y-%m-%d %H:%M").replace(tzinfo=pytz.utc)
        
        isr_tz = pytz.timezone("Asia/Jerusalem")
        return dt.astimezone(isr_tz).strftime("%H:%M")
    except Exception as e:
        log_step("שגיאה", f"כשל בהמרת זמן: {e}")
        return "TBD"

# ==============================================================================
# 5. מנוע שליפת נתונים (CDN + Backup)
# ==============================================================================
def get_all_games_data():
    """שולפת נתונים ומדווחת על כל שלב בלוג"""
    log_step(1, "פנייה לשרתי ה-NBA לקבלת נתונים חיים")
    try:
        # מניעת Cache ב-Railway
        api_call = f"{NBA_API_URL}?update={int(time.time())}"
        resp = requests.get(api_call, timeout=20)
        
        if resp.status_code == 200:
            games_list = resp.json().get("scoreboard", {}).get("games", [])
            if games_list:
                log_step(2, f"נמצאו {len(games_list)} משחקים ב-CDN")
                return games_list
        
        log_step(2, "CDN ריק או לא זמין, עובר ללוח הגיבוי השנתי")
        resp_full = requests.get(NBA_BACKUP_URL, timeout=20)
        if resp_full.status_code == 200:
            all_schedules = resp_full.json()
            isr_tz = pytz.timezone("Asia/Jerusalem")
            today_str = datetime.now(isr_tz).strftime("%Y%m%d")
            
            backup_games = []
            for month in all_schedules['league']['schedules']:
                for g in month['games']:
                    if g['gameDate'] == today_str:
                        backup_games.append({
                            "gameStatus": 1,
                            "gameEt": g['utctimeUtc'],
                            "homeTeam": {"teamCity": g['hTeam']['city'], "teamName": g['hTeam']['name'], "score": "0"},
                            "awayTeam": {"teamCity": g['vTeam']['city'], "teamName": g['vTeam']['name'], "score": "0"}
                        })
            log_step(3, f"נמצאו {len(backup_games)} משחקים בגיבוי")
            return backup_games
            
    except Exception as e:
        log_step("שגיאה", f"כשל במנוע השליפה: {e}")
    return []

# ==============================================================================
# 6. בניית הודעות עם דגשים (Bolding) ויישור לימין
# ==============================================================================
def create_results_report(games):
    """בונה הודעת תוצאות סופיות מיושרת לימין"""
    log_step(4, "מתחיל עיבוד תוצאות משחקים שנסתיימו")
    msg = "🏀 <b>תוצאות משחקי הלילה ב NBA</b> 🏀\n\n"
    has_final = False
    
    if not games: return None

    for g in games:
        if g.get("gameStatus") == 3: # 3 = Final
            h, a = g["homeTeam"], g["awayTeam"]
            h_s, a_s = int(h.get("score", 0)), int(a.get("score", 0))
            
            if h_s > a_s:
                winner = translate_team_rtl(h["teamCity"], h["teamName"], h_s)
                loser = translate_team_rtl(a["teamCity"], a["teamName"], a_s)
            else:
                winner = translate_team_rtl(a["teamCity"], a["teamName"], a_s)
                loser = translate_team_rtl(h["teamCity"], h["teamName"], h_s)
            
            msg += f"🏆 {winner}\n🔹 {loser}\n\n"
            has_final = True
            
    if has_final:
        return msg
    return "🏀 <b>תוצאות משחקי הלילה</b> 🏀\n\n🏁 לא נמצאו תוצאות סופיות כרגע."

def create_schedule_report(games):
    """בונה הודעת לו''ז עם שעות מיושרות נכון"""
    log_step(4, "מתחיל עיבוד לו''ז משחקים קרובים")
    msg = "🏀 <b>לוח משחקי הלילה ב NBA</b> 🏀\n\n"
    has_upcoming = False
    
    if not games: return "🏀 אין משחקים מתוכננים להלילה."

    # מיון לפי זמן כדי שההודעה תהיה מסודרת
    for g in games:
        if g.get("gameStatus") != 3:
            h_name = translate_team_rtl(g["homeTeam"]["teamCity"], g["homeTeam"]["teamName"])
            a_name = translate_team_rtl(g["awayTeam"]["teamCity"], g["awayTeam"]["teamName"])
            game_time = get_israel_time(g["gameEt"])
            
            # הדגשת זמן והצבה מימין
            status_line = "🔥 <b>חי עכשיו</b>" if g["gameStatus"] == 2 else f"⏰ <b>{game_time}</b>"
            msg += f"{status_line}\n🏀 {a_name} 🆚 {h_name}\n\n"
            has_upcoming = True
            
    if has_upcoming:
        return msg
    return "🏀 אין משחקים מתוכננים לשעות הקרובות."

# ==============================================================================
# 7. פונקציית שליחה סופית לטלגרם
# ==============================================================================
def send_telegram_broadcast(text):
    """שולחת הודעה ומוודאת הצלחה בלוגים"""
    if not text: return
    
    log_step(5, f"שולח הודעה לטלגרם (אורך: {len(text)} תווים)")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    
    try:
        r = requests.post(url, data=payload, timeout=15)
        if r.status_code == 200:
            log_step(6, "הודעה נשלחה בהצלחה לקבוצה!")
        else:
            log_step("שגיאה", f"טלגרם החזיר שגיאה: {r.text}")
    except Exception as e:
        log_step("שגיאה", f"כשל טכני בשליחה: {e}")

# ==============================================================================
# 8. ניהול הרצה (Main Orchestrator)
# ==============================================================================
def start_bot():
    """הלולאה הראשית של הבוט"""
    log_step(0, "NBA BOT הופעל בהצלחה - ממתין לזמני שידור")
    tz = pytz.timezone("Asia/Jerusalem")
    
    # משתני זיכרון למניעת כפילויות
    sent_sch_today = None
    sent_res_today = None

    while True:
        try:
            now = datetime.now(tz)
            clock = now.strftime("%H:%M")
            today = now.date()

            # שליחת תוצאות (01:54)
            if clock == RESULTS_TIME and sent_res_today != today:
                data = get_all_games_data()
                final_msg = create_results_report(data)
                send_telegram_broadcast(final_msg)
                sent_res_today = today
                time.sleep(65)

            # שליחת לו"ז (01:55)
            if clock == SCHEDULE_TIME and sent_sch_today != today:
                data = get_all_games_data()
                final_msg = create_schedule_report(data)
                send_telegram_broadcast(final_msg)
                sent_sch_today = today
                time.sleep(65)

            time.sleep(30) # בדיקה כל חצי דקה
            
        except Exception as e:
            log_step("שגיאה", f"קריסה בלולאה הראשית: {e}")
            time.sleep(60)

if __name__ == "__main__":
    start_bot()

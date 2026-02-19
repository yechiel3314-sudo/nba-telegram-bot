import requests
import time
from datetime import datetime
import pytz
from deep_translator import GoogleTranslator

# --- הגדרות טכניות ---
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
NCAA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
NBA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

translator = GoogleTranslator(source='en', target='iw')
RTL_MARK = "\u200f" 
status_cache = {} # שומר את מצב השחקנים כדי לדעת מתי לשלוח עדכון סופי

# --- בסיסי נתונים - כל השחקנים שביקשת ---
NBA_DATABASE = {
    "Deni Avdija": ["דני אבדיה", "פורטלנד", "Trail Blazers"],
    "Danny Wolf": ["דני וולף", "ברוקלין", "Nets"],
    "Ben Saraf": ["בן שרף", "ברוקלין", "Nets"]
}

GLEAGUE_DATABASE = {
    "Ben Saraf": ["בן שרף", "לונג איילנד", "Long Island Nets", "Blue Coats", "Squadron"]
}

NCAA_DATABASE = {
    "Emanuel Sharp": ["עמנואל שארפ", "יוסטון", "Houston"],
    "Yoav Berman": ["יואב ברמן", "קווינס", "Queens"],
    "Ofri Naveh": ["עופרי נווה", "אורל רוברטס", "Oral Roberts"],
    "Eytan Burg": ["איתן בורג", "טנסי", "Tennessee"],
    "Omer Mayer": ["עומר מאייר", "פורדו", "Purdue"],
    "Noam Dovrat": ["נועם דוברת", "מיאמי", "Miami"],
    "Or Ashkenazi": ["אור אשכנזי", "ליפסקומב", "Lipscomb"],
    "Alon Michaeli": ["אלון מיכאלי", "קולורדו", "Colorado"],
    "Yonatan Levi": ["יונתן לוי", "פפרדיין", "Pepperdine"],
    "Yuval Levin": ["יובל לוין", "פרדו פורט וויין", "Purdue Fort Wayne"],
    "Omer Hamama": ["עומר חממה", "קנט סטייט", "Kent State"],
    "Or Paran": ["אור פארן", "מרסיהרסט", "Mercyhurst"],
    "Daniel Gueta": ["דניאל גואטה", "אוקלהומה סטייט", "Oklahoma State"]
}

# --- פונקציות עזר ---

def tr(text):
    """תרגום שמות קבוצות ותיקון שמות נפוצים"""
    try:
        translated = translator.translate(text)
        return translated.replace("שבילים בלייזרים", "פורטלנד").replace("רשתות", "ברוקלין").replace("לוחמים", "ווריורס")
    except:
        return text

def get_player_status_info(ev, player_name_en):
    """מושך את הסטטוס הרפואי של השחקן מתוך נתוני המשחק"""
    try:
        for competition in ev.get("competitions", []):
            for team in competition.get("competitors", []):
                for injury_detail in team.get("injuries", []):
                    # בדיקה אם שם השחקן מופיע בתיאור הפציעה
                    if player_name_en in injury_detail.get("shortName", "") or player_name_en in injury_detail.get("displayName", ""):
                        return injury_detail.get("status", "").upper()
    except:
        pass
    return "ACTIVE"

def send_telegram(text):
    """שליחת הודעה לטלגרם"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except:
        pass

def check_final_updates():
    """פונקציה שרצה ברקע ובודקת אם סטטוס 'סימן שאלה' הפך להחלטה סופית"""
    global status_cache
    for api_url in [NBA_SCOREBOARD, NCAA_SCOREBOARD]:
        try:
            response = requests.get(api_url, timeout=10).json()
            for event in response.get("events", []):
                # בודק רק משחקים שטרם התחילו
                if event["status"]["type"]["state"] != "pre":
                    continue
                
                # איחוד כל בסיסי הנתונים לבדיקה כללית
                all_players_combined = {**NBA_DATABASE, **GLEAGUE_DATABASE, **NCAA_DATABASE}
                teams_in_game = [t["team"]["displayName"] for t in event["competitions"][0]["competitors"]]
                
                for p_en, info in all_players_combined.items():
                    if any(info[2] in t_name for t_name in teams_in_game):
                        current_status = get_player_status_info(event, p_en)
                        cache_key = f"{p_en}_{event['id']}"
                        
                        # אם בלו"ז המקורי הוא היה בסימן שאלה ועכשיו יש החלטה
                        if status_cache.get(cache_key) == "QUESTIONABLE":
                            if current_status == "ACTIVE" or "PROBABLE" in current_status:
                                update_msg = f"{RTL_MARK}🇮🇱 **עדכון סופי: הוא משחק!** 🇮🇱\n\n"
                                update_msg += f"{RTL_MARK}🏀 *{info[0]}* כשיר ויופיע הלילה במדי {info[1]}! ✅"
                                send_telegram(update_msg)
                                status_cache[cache_key] = "FINAL"
                            elif "OUT" in current_status:
                                update_msg = f"{RTL_MARK}🇮🇱 **עדכון סופי: לא ישחק** 🇮🇱\n\n"
                                update_msg += f"{RTL_MARK}🏀 *{info[0]}* בחוץ למשחק הלילה (מדי {info[1]}). ❌"
                                send_telegram(update_msg)
                                status_cache[cache_key] = "FINAL"
        except:
            pass

def get_combined_schedule():
    """הפונקציה המרכזית שבונה את הלו"ז היומי"""
    all_games = {"NBA": [], "GLEAGUE": [], "NCAA": []}
    players_handled_today = set() # למניעת כפילויות של אותו שחקן
    global status_cache
    
    # 1. סריקת NBA
    try:
        nba_response = requests.get(NBA_SCOREBOARD, timeout=10).json()
        for event in nba_response.get("events", []):
            teams = [t["team"]["displayName"] for t in event["competitions"][0]["competitors"]]
            for p_en, info in NBA_DATABASE.items():
                if any(info[2] in t_name for t_name in teams):
                    # יצירת שורת המשחק
                    vs_team = [t for t in teams if info[2] not in t][0]
                    status = get_player_status_info(event, p_en)
                    
                    status_note = ""
                    if "QUESTIONABLE" in status or "GTD" in status:
                        status_note = " ⚠️ (בסימן שאלה)"
                        status_cache[f"{p_en}_{event['id']}"] = "QUESTIONABLE"
                    elif "OUT" in status:
                        status_note = " ❌ (פצוע)"
                    
                    time_utc = datetime.strptime(event["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    time_il = time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    
                    line = (time_il, f"{RTL_MARK}🏀 *{info[0]}*{status_note} ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs_team)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*")
                    all_games["NBA"].append(line)
                    players_handled_today.add(p_en)
    except:
        pass

    # 2. סריקת NCAA וליגת הפיתוח
    try:
        ncaa_response = requests.get(NCAA_SCOREBOARD, timeout=10).json()
        for event in ncaa_response.get("events", []):
            teams = [t["team"]["displayName"] for t in event["competitions"][0]["competitors"]]
            
            # בדיקת G-League
            for p_en, info in GLEAGUE_DATABASE.items():
                if p_en in players_handled_today: continue
                if any(k in t_name for k in info[2:] for t_name in teams):
                    vs_team = [t for t in teams if not any(k in t for k in info[2:])][0]
                    status = get_player_status_info(event, p_en)
                    status_note = " ⚠️ (בסימן שאלה)" if ("QUESTIONABLE" in status or "GTD" in status) else (" ❌ (פצוע)" if "OUT" in status else "")
                    if "QUESTIONABLE" in status or "GTD" in status: status_cache[f"{p_en}_{event['id']}"] = "QUESTIONABLE"
                    
                    time_utc = datetime.strptime(event["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    time_il = time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    all_games["GLEAGUE"].append((time_il, f"{RTL_MARK}🏀 *{info[0]}*{status_note} ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs_team)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"))
                    players_handled_today.add(p_en)

            # בדיקת מכללות
            for p_en, info in NCAA_DATABASE.items():
                if p_en in players_handled_today: continue
                if any(info[2] in t_name for t_name in teams):
                    vs_team = [t for t in teams if info[2] not in t][0]
                    status = get_player_status_info(event, p_en)
                    status_note = " ⚠️ (בסימן שאלה)" if ("QUESTIONABLE" in status or "GTD" in status) else (" ❌ (פצוע)" if "OUT" in status else "")
                    if "QUESTIONABLE" in status or "GTD" in status: status_cache[f"{p_en}_{event['id']}"] = "QUESTIONABLE"
                    
                    time_utc = datetime.strptime(event["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    time_il = time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    all_games["NCAA"].append((time_il, f"{RTL_MARK}🏀 *{info[0]}*{status_note} ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs_team)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"))

    except:
        pass

    # בניית ההודעה הסופית
    full_message = ""
    
    # NBA
    if all_games["NBA"]:
        sorted_nba = sorted(all_games["NBA"], key=lambda x: x[0])
        full_message += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה ב-NBA** 🇮🇱\n\n"
        full_message += "\n\n".join([g[1] for g in sorted_nba]) + "\n\n"

    # G-League
    if all_games["GLEAGUE"]:
        sorted_gleague = sorted(all_games["GLEAGUE"], key=lambda x: x[0])
        full_message += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה בליגת הפיתוח (ג'י ליג)** 🇮🇱\n\n"
        full_message += "\n\n".join([g[1] for g in sorted_gleague]) + "\n\n"

    # מכללות
    if all_games["NCAA"]:
        sorted_ncaa = sorted(all_games["NCAA"], key=lambda x: x[0])
        full_message += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה במכללות** 🇮🇱\n\n"
        full_message += "\n\n".join([g[1] for g in sorted_ncaa]) + "\n\n"

    if full_message:
        send_telegram(full_message)
    else:
        send_telegram(f"{RTL_MARK}🇮🇱 **אין משחקי לגיונרים הלילה** 😴")

# --- לולאה ראשית ---

if __name__ == "__main__":
    print("🚀 בוט לגיונרים מאוחד פועל...")
    last_sent_day = ""
    
    while True:
        try:
            now_il = datetime.now(pytz.timezone('Asia/Jerusalem'))
            today_str = now_il.strftime("%Y-%m-%d")

            # בדיקה לשליחת לו"ז (כאן שיניתי ל-14:22 כפי שביקשת לניסוי)
            if now_il.hour == 14 and now_il.minute == 30 and last_sent_day != today_str:
                get_combined_schedule()
                last_sent_day = today_str
            
            # בדיקת עדכוני סטטוס סופיים (משחק/לא משחק) כל 10 דקות
            if now_il.minute % 10 == 0:
                check_final_updates()

        except Exception as error:
            print(f"שגיאה בלולאה הראשית: {error}")
            
        time.sleep(30)

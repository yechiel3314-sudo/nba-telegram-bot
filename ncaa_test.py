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
status_cache = {} 

# --- בסיסי נתונים ---
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

def tr(text):
    try:
        t = translator.translate(text)
        return t.replace("שבילים בלייזרים", "פורטלנד").replace("רשתות", "ברוקלין").replace("לוחמים", "ווריורס")
    except: return text

def get_player_status_info(ev, player_name_en):
    try:
        for comp in ev.get("competitions", []):
            for team in comp.get("competitors", []):
                for detail in team.get("injuries", []):
                    if player_name_en in detail.get("shortName", "") or player_name_en in detail.get("displayName", ""):
                        return detail.get("status", "").upper()
    except: pass
    return "ACTIVE"

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def check_final_updates():
    global status_cache
    for url in [NBA_SCOREBOARD, NCAA_SCOREBOARD]:
        try:
            resp = requests.get(url, timeout=10).json()
            for ev in resp.get("events", []):
                if ev["status"]["type"]["state"] != "pre": continue
                all_p = {**NBA_DATABASE, **GLEAGUE_DATABASE, **NCAA_DATABASE}
                teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
                for p_en, info in all_p.items():
                    if any(info[2] in t for t in teams):
                        status = get_player_status_info(ev, p_en)
                        key = f"{p_en}_{ev['id']}"
                        if status_cache.get(key) == "QUESTIONABLE":
                            if status == "ACTIVE" or "PROBABLE" in status:
                                send_telegram(f"{RTL_MARK}🇮🇱 **עדכון סופי: הוא משחק!** 🇮🇱\n\n{RTL_MARK}🏀 *{info[0]}* כשיר ויופיע הלילה במדי {info[1]}! ✅")
                                status_cache[key] = "FINAL"
                            elif "OUT" in status:
                                send_telegram(f"{RTL_MARK}🇮🇱 **עדכון סופי: לא ישחק** 🇮🇱\n\n{RTL_MARK}🏀 *{info[0]}* בחוץ למשחק הלילה (מדי {info[1]}). ❌")
                                status_cache[key] = "FINAL"
        except: pass

def get_combined_schedule():
    all_games = {"NBA": [], "GLEAGUE": [], "NCAA": []}
    players_handled = set() # למניעת כפילויות של אותו שחקן באותו לילה
    global status_cache
    
    # 1. סריקת NBA (עדיפות ראשונה)
    try:
        nba_resp = requests.get(NBA_SCOREBOARD, timeout=10).json()
        for ev in nba_resp.get("events", []):
            teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
            for p_en, info in NBA_DATABASE.items():
                if any(info[2] in t for t in teams):
                    vs = [t for t in teams if info[2] not in t][0]
                    status = get_player_status_info(ev, p_en)
                    note = " ⚠️ (בסימן שאלה)" if ("QUESTIONABLE" in status or "GTD" in status) else (" ❌ (פצוע)" if "OUT" in status else "")
                    if "QUESTIONABLE" in status or "GTD" in status: status_cache[f"{p_en}_{ev['id']}"] = "QUESTIONABLE"
                    
                    time_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    time_il = time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    all_games["NBA"].append((time_il, f"{RTL_MARK}🏀 *{info[0]}*{note} ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"))
                    players_handled.add(p_en)
    except: pass

    # 2. סריקת NCAA ו-G-League
    try:
        ncaa_resp = requests.get(NCAA_SCOREBOARD, timeout=10).json()
        for ev in ncaa_resp.get("events", []):
            teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
            
            # בדיקת G-League
            for p_en, info in GLEAGUE_DATABASE.items():
                if p_en in players_handled: continue
                if any(k in t for k in info[2:] for t in teams):
                    vs = [t for t in teams if not any(k in t for k in info[2:])][0]
                    status = get_player_status_info(ev, p_en)
                    note = " ⚠️ (בסימן שאלה)" if ("QUESTIONABLE" in status or "GTD" in status) else (" ❌ (פצוע)" if "OUT" in status else "")
                    if "QUESTIONABLE" in status or "GTD" in status: status_cache[f"{p_en}_{ev['id']}"] = "QUESTIONABLE"
                    
                    time_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    time_il = time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    all_games["GLEAGUE"].append((time_il, f"{RTL_MARK}🏀 *{info[0]}*{note} ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"))
                    players_handled.add(p_en)

            # בדיקת מכללות
            for p_en, info in NCAA_DATABASE.items():
                if p_en in players_handled: continue
                if any(info[2] in t for t in teams):
                    vs = [t for t in teams if info[2] not in t][0]
                    status = get_player_status_info(ev, p_en)
                    note = " ⚠️ (בסימן שאלה)" if ("QUESTIONABLE" in status or "GTD" in status) else (" ❌ (פצוע)" if "OUT" in status else "")
                    if "QUESTIONABLE" in status or "GTD" in status: status_cache[f"{p_en}_{ev['id']}"] = "QUESTIONABLE"
                    
                    time_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    time_il = time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    all_games["NCAA"].append((time_il, f"{RTL_MARK}🏀 *{info[0]}*{note} ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"))
    except: pass

    # בניית הודעה סופית לפי סדר
    full_msg = ""
    categories = [
        ("NBA", "🇮🇱 משחקי לגיונרים הלילה ב-NBA 🇮🇱"),
        ("GLEAGUE", "🇮🇱 משחקי לגיונרים הלילה בליגת הפיתוח (ג'י ליג) 🇮🇱"),
        ("NCAA", "🇮🇱 משחקי לגיונרים הלילה במכללות 🇮🇱")
    ]
    
    for cat, title in categories:
        if all_games[cat]:
            sorted_list = sorted(all_games[cat], key=lambda x: x[0])
            full_msg += f"{RTL_MARK}{title}\n\n" + "\n\n".join([g[1] for g in sorted_list]) + "\n\n"
    
    send_telegram(full_msg if full_msg else f"{RTL_MARK}🇮🇱 **אין משחקי לגיונרים הלילה** 😴")

if __name__ == "__main__":
    print("🚀 בוט ניסוי (14:22) פועל...")
    last_day = ""
    while True:
        now = datetime.now(pytz.timezone('Asia/Jerusalem'))
        if now.hour == 14 and now.minute == 22 and last_day != now.strftime("%Y-%m-%d"):
            get_combined_schedule()
            last_day = now.strftime("%Y-%m-%d")
        if now.minute % 10 == 0: check_final_updates()
        time.sleep(30)

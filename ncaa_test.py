import requests
import time
from datetime import datetime
import pytz
from deep_translator import GoogleTranslator

# --- הגדרות טכניות ---
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# API של ESPN לתוצאות וסטטוסים
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

# --- פונקציות לוגיות ---

def tr(text):
    """תרגום שמות קבוצות ותיקון עברית"""
    try:
        t = translator.translate(text)
        return t.replace("שבילים בלייזרים", "פורטלנד").replace("רשתות", "ברוקלין").replace("לוחמים", "ווריורס")
    except: return text

def get_detailed_injury(ev, player_name_en):
    """מושך סטטוס וסיבת פציעה מפורטת"""
    try:
        for comp in ev.get("competitions", []):
            for team in comp.get("competitors", []):
                for injury in team.get("injuries", []):
                    if player_name_en in injury.get("displayName", ""):
                        return {
                            "status": injury.get("status", "").upper(),
                            "reason": injury.get("reason", "")
                        }
    except: pass
    return {"status": "ACTIVE", "reason": ""}

def send_telegram(text):
    """שליחת הודעה לטלגרם"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def check_final_updates():
    """בדיקת עדכונים בכל דקה - האם סימן שאלה הפך לסופי"""
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
                        inj = get_detailed_injury(ev, p_en)
                        key = f"{p_en}_{ev['id']}"
                        
                        if status_cache.get(key) == "QUESTIONABLE":
                            if inj["status"] == "ACTIVE" or "PROBABLE" in inj["status"]:
                                send_telegram(f"{RTL_MARK}🇮🇱 **עדכון סופי: הוא משחק!** 🇮🇱\n\n{RTL_MARK}🏀 *{info[0]}* כשיר ויופיע הלילה במדי {info[1]}! ✅")
                                status_cache[key] = "FINAL"
                            elif "OUT" in inj["status"]:
                                reason_str = f" ({inj['reason']})" if inj['reason'] else ""
                                send_telegram(f"{RTL_MARK}🇮🇱 **עדכון סופי: לא ישחק** 🇮🇱\n\n{RTL_MARK}🏀 *{info[0]}* בחוץ למשחק הלילה{reason_str}. ❌")
                                status_cache[key] = "FINAL"
        except: pass

def get_combined_schedule():
    """בניית לו''ז יומי עם בדיקת ירידה לליגת הפיתוח"""
    all_games = {"NBA": [], "GLEAGUE": [], "NCAA": []}
    players_handled = set()
    global status_cache
    
    # 1. סריקת NBA
    try:
        resp = requests.get(NBA_SCOREBOARD, timeout=10).json()
        for ev in resp.get("events", []):
            teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
            for p_en, info in NBA_DATABASE.items():
                if any(info[2] in t for t in teams):
                    inj = get_detailed_injury(ev, p_en)
                    
                    # בדיקה אם השחקן ירד לליגת הפיתוח (G-League)
                    if "G League" in inj["reason"] or "Assignment" in inj["reason"]:
                        print(f"Skipping {p_en} in NBA - down to GLeague")
                        continue 
                    
                    vs = [t for t in teams if info[2] not in t][0]
                    status_note = ""
                    if "QUESTIONABLE" in inj["status"] or "GTD" in inj["status"]:
                        status_note = " ⚠️ (בסימן שאלה)"
                        status_cache[f"{p_en}_{ev['id']}"] = "QUESTIONABLE"
                    elif "OUT" in inj["status"]:
                        status_note = " ❌ (פצוע)"
                    
                    time_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    time_il = time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    
                    all_games["NBA"].append((time_il, f"{RTL_MARK}🏀 *{info[0]}*{status_note} ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"))
                    players_handled.add(p_en)
    except: pass

    # 2. סריקת G-League ומכללות
    try:
        resp = requests.get(NCAA_SCOREBOARD, timeout=10).json()
        for ev in resp.get("events", []):
            teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
            
            # G-League
            for p_en, info in GLEAGUE_DATABASE.items():
                if any(k in t for k in info[2:] for t in teams):
                    vs = [t for t in teams if not any(k in t for k in info[2:])][0]
                    inj = get_detailed_injury(ev, p_en)
                    
                    status_note = ""
                    # אם הוא ירד מה-NBA, נוסיף הערה מיוחדת
                    if p_en == "Ben Saraf": status_note = " ⬇️ (ירד לסגל ליגת הפיתוח)"
                    
                    if "QUESTIONABLE" in inj["status"] or "GTD" in inj["status"]:
                        status_note = " ⚠️ (בסימן שאלה)"
                        status_cache[f"{p_en}_{ev['id']}"] = "QUESTIONABLE"
                    
                    time_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    time_il = time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    all_games["GLEAGUE"].append((time_il, f"{RTL_MARK}🏀 *{info[0]}*{status_note} ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"))
                    players_handled.add(p_en)

            # מכללות
            for p_en, info in NCAA_DATABASE.items():
                if p_en in players_handled: continue
                if any(info[2] in t for t in teams):
                    vs = [t for t in teams if info[2] not in t][0]
                    inj = get_detailed_injury(ev, p_en)
                    status_note = " ⚠️ (בסימן שאלה)" if ("QUESTIONABLE" in inj["status"] or "GTD" in inj["status"]) else ""
                    
                    time_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    time_il = time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    all_games["NCAA"].append((time_il, f"{RTL_MARK}🏀 *{info[0]}*{status_note} ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"))
    except: pass

    full_msg = ""
    if all_games["NBA"]:
        full_msg += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה ב-NBA** 🇮🇱\n\n" + "\n\n".join([g[1] for g in sorted(all_games["NBA"])]) + "\n\n"
    if all_games["GLEAGUE"]:
        full_msg += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה בליגת הפיתוח (ג'י ליג)** 🇮🇱\n\n" + "\n\n".join([g[1] for g in sorted(all_games["GLEAGUE"])]) + "\n\n"
    if all_games["NCAA"]:
        full_msg += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה במכללות** 🇮🇱\n\n" + "\n\n".join([g[1] for g in sorted(all_games["NCAA"])]) + "\n\n"
    
    send_telegram(full_msg if full_msg else f"{RTL_MARK}🇮🇱 **אין משחקי לגיונרים הלילה** 😴")

# --- הרצה ובדיקה כל דקה ---

if __name__ == "__main__":
    print("🚀 בוט מאוחד - בדיקה בכל דקה פועלת...")
    last_day = ""
    while True:
        now = datetime.now(pytz.timezone('Asia/Jerusalem'))
        
        # 1. שליחת הלו"ז היומי (שעה 14:40 לניסוי הנוכחי)
        if now.hour == 14 and now.minute == 40 and last_day != now.strftime("%Y-%m-%d"):
            get_combined_schedule()
            last_day = now.strftime("%Y-%m-%d")
        
        # 2. בדיקה בכל דקה של סטטוסים רפואיים
        check_final_updates()
        
        # הדפסה קטנה ללוג כדי לדעת שהבוט חי
        if now.second == 0:
            print(f"🔎 סריקת דקה: {now.strftime('%H:%M')}")
            
        time.sleep(60) # המתנה של דקה אחת בדיוק

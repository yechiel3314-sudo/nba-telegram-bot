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

# --- פונקציות עזר ---

def tr(text):
    try:
        t = translator.translate(text)
        return t.replace("שבילים בלייזרים", "פורטלנד").replace("רשתות", "ברוקלין").replace("לוחמים", "ווריורס")
    except: return text

def get_detailed_injury(ev, player_name_en):
    try:
        for comp in ev.get("competitions", []):
            for team in comp.get("competitors", []):
                for injury in team.get("injuries", []):
                    if player_name_en in injury.get("displayName", ""):
                        return {"status": injury.get("status", "").upper(), "reason": injury.get("reason", "")}
    except: pass
    return {"status": "ACTIVE", "reason": ""}

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def check_final_updates():
    """בודק רק אם יש שחקנים בזיכרון שהם בסימן שאלה"""
    global status_cache
    # אם אין אף אחד בסימן שאלה כרגע בזיכרון, אל תפנה בכלל ל-API
    if not any(v == "QUESTIONABLE" for v in status_cache.values()):
        return

    for url in [NBA_SCOREBOARD, NCAA_SCOREBOARD]:
        try:
            resp = requests.get(url, timeout=10).json()
            for ev in resp.get("events", []):
                all_p = {**NBA_DATABASE, **GLEAGUE_DATABASE, **NCAA_DATABASE}
                teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
                
                for p_en, info in all_p.items():
                    key = f"{p_en}_{ev['id']}"
                    if status_cache.get(key) == "QUESTIONABLE":
                        if any(info[2] in t for t in teams):
                            inj = get_detailed_injury(ev, p_en)
                            if inj["status"] == "ACTIVE" or "PROBABLE" in inj["status"]:
                                send_telegram(f"{RTL_MARK}🇮🇱 **עדכון סופי: הוא משחק!** 🇮🇱\n\n{RTL_MARK}🏀 *{info[0]}* כשיר ויופיע הלילה! ✅")
                                status_cache[key] = "FINAL"
                            elif "OUT" in inj["status"]:
                                r = f" ({inj['reason']})" if inj['reason'] else ""
                                send_telegram(f"{RTL_MARK}🇮🇱 **עדכון סופי: לא ישחק** 🇮🇱\n\n{RTL_MARK}🏀 *{info[0]}* בחוץ למשחק הלילה{r}. ❌")
                                status_cache[key] = "FINAL"
        except: pass

def get_combined_schedule():
    all_games = {"NBA": [], "GLEAGUE": [], "NCAA": []}
    players_handled = set()
    global status_cache
    status_cache = {} # איפוס הזיכרון בתחילת יום חדש
    
    # בדיקת NBA
    try:
        resp = requests.get(NBA_SCOREBOARD, timeout=10).json()
        for ev in resp.get("events", []):
            teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
            for p_en, info in NBA_DATABASE.items():
                if any(info[2] in t for t in teams):
                    inj = get_detailed_injury(ev, p_en)
                    if "G League" in inj["reason"] or "Assignment" in inj["reason"]: continue
                    
                    vs = [t for t in teams if info[2] not in t][0]
                    status_note = ""
                    if "QUESTIONABLE" in inj["status"] or "GTD" in inj["status"]:
                        status_note = " ⚠️ (בסימן שאלה)"
                        status_cache[f"{p_en}_{ev['id']}"] = "QUESTIONABLE"
                    
                    time_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    time_il = time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    all_games["NBA"].append((time_il, f"{RTL_MARK}🏀 *{info[0]}*{status_note} ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"))
                    players_handled.add(p_en)
    except: pass

    # בדיקת G-League ומכללות (דומה למה שכתבנו קודם)
    try:
        resp = requests.get(NCAA_SCOREBOARD, timeout=10).json()
        for ev in resp.get("events", []):
            teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
            for p_en, info in GLEAGUE_DATABASE.items():
                if any(k in t for k in info[2:] for t in teams):
                    vs = [t for t in teams if not any(k in t for k in info[2:])][0]
                    inj = get_detailed_injury(ev, p_en)
                    status_note = " ⬇️ (ירד לסגל ליגת הפיתוח)" if p_en == "Ben Saraf" else ""
                    if "QUESTIONABLE" in inj["status"] or "GTD" in inj["status"]:
                        status_note = " ⚠️ (בסימן שאלה)"
                        status_cache[f"{p_en}_{ev['id']}"] = "QUESTIONABLE"
                    time_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    time_il = time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    all_games["GLEAGUE"].append((time_il, f"{RTL_MARK}🏀 *{info[0]}*{status_note} ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"))
                    players_handled.add(p_en)

            for p_en, info in NCAA_DATABASE.items():
                if p_en in players_handled: continue
                if any(info[2] in t for t in teams):
                    vs = [t for t in teams if info[2] not in t][0]
                    inj = get_detailed_injury(ev, p_en)
                    status_note = ""
                    if "QUESTIONABLE" in inj["status"] or "GTD" in inj["status"]:
                        status_note = " ⚠️ (בסימן שאלה)"
                        status_cache[f"{p_en}_{ev['id']}"] = "QUESTIONABLE"
                    time_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    time_il = time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    all_games["NCAA"].append((time_il, f"{RTL_MARK}🏀 *{info[0]}*{status_note} ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"))
    except: pass

    full_msg = ""
    if all_games["NBA"]: full_msg += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה ב-NBA** 🇮🇱\n\n" + "\n\n".join([g[1] for g in sorted(all_games["NBA"])]) + "\n\n"
    if all_games["GLEAGUE"]: full_msg += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה בליגת הפיתוח** 🇮🇱\n\n" + "\n\n".join([g[1] for g in sorted(all_games["GLEAGUE"])]) + "\n\n"
    if all_games["NCAA"]: full_msg += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה במכללות** 🇮🇱\n\n" + "\n\n".join([g[1] for g in sorted(all_games["NCAA"])]) + "\n\n"
    send_telegram(full_msg if full_msg else f"{RTL_MARK}🇮🇱 **אין משחקי לגיונרים הלילה** 😴")

# --- לולאה מרכזית עם הגבלת שעות ---

if __name__ == "__main__":
    print("🚀 בוט מאוחד פועל...")
    last_day = ""
    while True:
        now = datetime.now(pytz.timezone('Asia/Jerusalem'))
        
        # 1. שליחת לו"ז יומי ב-14:40
        if now.hour == 14 and now.minute == 41 and last_day != now.strftime("%Y-%m-%d"):
            get_combined_schedule()
            last_day = now.strftime("%Y-%m-%d")
        
        # 2. בדיקת עדכונים רק בשעות רלוונטיות (מ-18:00 עד 09:00 למחרת)
        # זה מונע בדיקות סתם כשאף אחד לא מעדכן פציעות בארה"ב
        if now.hour >= 18 or now.hour <= 9:
            check_final_updates()
            if now.second == 0:
                print(f"🔎 סורק סטטוסים בשעה רלוונטית: {now.strftime('%H:%M')}")
        
        time.sleep(60)

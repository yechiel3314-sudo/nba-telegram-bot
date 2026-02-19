import requests
import time
from datetime import datetime
import pytz
from deep_translator import GoogleTranslator

# ==========================================
# --- הגדרות טכניות ומפתחות ---
# ==========================================
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

NCAA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
NBA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

translator = GoogleTranslator(source='en', target='iw')
RTL_MARK = "\u200f" 
status_cache = {} 

# ==========================================
# --- בסיסי נתונים ---
# ==========================================
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

# ==========================================
# --- פונקציות עזר תרגום ופציעות ---
# ==========================================

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
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

# ==========================================
# --- סיכום בוקר (09:15) ---
# ==========================================

def get_morning_summary():
    leagues = [
        (NBA_SCOREBOARD, "NBA", NBA_DATABASE),
        (NCAA_SCOREBOARD, "ליגת הפיתוח", GLEAGUE_DATABASE),
        (NCAA_SCOREBOARD, "המכללות", NCAA_DATABASE)
    ]
    
    for url, title, db in leagues:
        msg = f"{RTL_MARK}🇮🇱 **סיכום לגיונרים - {title}** 🇮🇱\n\n"
        found_any = False
        try:
            resp = requests.get(url, timeout=10).json()
            for ev in resp.get("events", []):
                if ev["status"]["type"]["state"] != "post": continue
                comp = ev["competitions"][0]
                teams = comp["competitors"]
                for p_en, info in db.items():
                    for team in teams:
                        if (isinstance(info[2], list) and any(k in team["team"]["displayName"] for k in info[2:])) or (not isinstance(info[2], list) and info[2] in team["team"]["displayName"]):
                            try:
                                bs_url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/{'nba' if 'nba' in url else 'mens-college-basketball'}/summary?event={ev['id']}"
                                bs_data = requests.get(bs_url, timeout=10).json()
                                for t_stats in bs_data.get("players", []):
                                    for p_stats in t_stats.get("athletes", []):
                                        if p_en in p_stats["athlete"]["displayName"]:
                                            s = p_stats["stats"]
                                            pts, reb, ast, stl = s[0], s[1], s[2], s[3]
                                            mins = p_stats.get("minutes", "0")
                                            my_s, opp_s = int(team["score"]), int([t["score"] for t in teams if t["id"] != team["id"]][0])
                                            opp_n = tr([t["team"]["shortDisplayName"] for t in teams if t["id"] != team["id"]][0])
                                            res = "✅ ניצחון" if my_s > opp_s else "❌ הפסד"
                                            msg += f"{RTL_MARK}🏀 **{info[0]}** ({info[1]})\n{RTL_MARK}{res} {my_s} - {opp_s} על {opp_n}\n{RTL_MARK}📊 סטטיסטיקה: {pts} נק', {reb} ריב', {ast} אס', {stl} חט'\n{RTL_MARK}⏱️ דקות: {mins}\n\n"
                                            found_any = True
                            except: pass
            if found_any: send_telegram(msg)
        except: pass

# ==========================================
# --- לו''ז יומי (15:00) ---
# ==========================================

def get_combined_schedule():
    all_games = {"NBA": [], "GLEAGUE": [], "NCAA": []}
    saraf_training_msg = ""
    players_handled = set()
    global status_cache
    status_cache = {}

    # 1. סריקת ליגת הפיתוח (עדיפות ראשונה)
    try:
        resp_ncaa = requests.get(NCAA_SCOREBOARD, timeout=10).json()
        for ev in resp_ncaa.get("events", []):
            teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
            for p_en, info in GLEAGUE_DATABASE.items():
                if any(k in team_name for k in info[2:] for team_name in teams):
                    vs = [t for t in teams if not any(k in t for k in info[2:])][0]
                    time_il = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
                    all_games["GLEAGUE"].append((time_il, f"{RTL_MARK}🏀 *{info[0]}* ⬇️ (ירד לסגל ליגת הפיתוח) ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"))
                    players_handled.add(p_en)
    except: pass

    # 2. סריקת NBA ומכללות
    for url, key, db in [(NBA_SCOREBOARD, "NBA", NBA_DATABASE), (NCAA_SCOREBOARD, "NCAA", NCAA_DATABASE)]:
        try:
            resp = requests.get(url, timeout=10).json()
            for ev in resp.get("events", []):
                teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
                for p_en, info in db.items():
                    if p_en in players_handled: continue
                    if info[2] in str(teams):
                        # חוק בן שרף - אם הוא ב-NBA אך לא נמצא לו משחק פיתוח
                        if p_en == "Ben Saraf" and key == "NBA":
                            saraf_training_msg = f"⬇️ **עדכון: {info[0]}** לא משחק (ירד להתאמן בג'י ליג - לונג איילנד)"
                            continue 
                        
                        vs = [t for t in teams if info[2] not in t][0]
                        inj = get_detailed_injury(ev, p_en)
                        status_note = " ⚠️ (בסימן שאלה)" if "QUESTIONABLE" in inj["status"] or "GTD" in inj["status"] else ""
                        if status_note: status_cache[f"{p_en}_{ev['id']}"] = "QUESTIONABLE"
                        
                        time_il = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
                        all_games[key].append((time_il, f"{RTL_MARK}🏀 *{info[0]}*{status_note} ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"))
        except: pass

    # בניית ההודעה לפי הסדר המבוקש
    full_msg = ""
    
    # חלק 1: NBA וליגת הפיתוח
    for k in ["NBA", "GLEAGUE"]:
        if all_games[k]:
            title_name = "NBA" if k == "NBA" else "ליגת הפיתוח"
            full_msg += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה ב-{title_name}** 🇮🇱\n\n" + "\n\n".join([g[1] for g in sorted(all_games[k])]) + "\n\n\n"
    
    # חלק 2: עדכון בן שרף (מופיע כאן, לפני המכללות)
    if saraf_training_msg:
        full_msg += saraf_training_msg + "\n\n\n"

    # חלק 3: מכללות
    if all_games["NCAA"]:
        full_msg += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה בהמכללות** 🇮🇱\n\n" + "\n\n".join([g[1] for g in sorted(all_games["NCAA"])]) + "\n\n"

    send_telegram(full_msg if full_msg else f"{RTL_MARK}🇮🇱 אין משחקי לגיונרים הלילה 😴")

# ==========================================
# --- עדכוני פציעות בזמן אמת ---
# ==========================================

def check_final_updates():
    global status_cache
    if not any(v == "QUESTIONABLE" for v in status_cache.values()): return
    for url in [NBA_SCOREBOARD, NCAA_SCOREBOARD]:
        try:
            resp = requests.get(url, timeout=10).json()
            for ev in resp.get("events", []):
                if ev["status"]["type"]["state"] != "pre": continue
                all_p = {**NBA_DATABASE, **GLEAGUE_DATABASE, **NCAA_DATABASE}
                teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
                for p_en, info in all_p.items():
                    key = f"{p_en}_{ev['id']}"
                    if status_cache.get(key) == "QUESTIONABLE":
                        if info[2] in str(teams):
                            inj = get_detailed_injury(ev, p_en)
                            if inj["status"] == "ACTIVE" or "PROBABLE" in inj["status"]:
                                send_telegram(f"{RTL_MARK}🇮🇱 **עדכון סופי: הוא משחק!** 🇮🇱\n\n{RTL_MARK}🏀 *{info[0]}* כשיר ויופיע הלילה! ✅")
                                status_cache[key] = "FINAL"
                            elif "OUT" in inj["status"]:
                                r = f" ({inj['reason']})" if inj['reason'] else ""
                                send_telegram(f"{RTL_MARK}🇮🇱 **עדכון סופי: לא ישחק** 🇮🇱\n\n{RTL_MARK}🏀 *{info[0]}* בחוץ למשחק הלילה{r}. ❌")
                                status_cache[key] = "FINAL"
        except: pass

# ==========================================
# --- הרצה ראשית ---
# ==========================================

if __name__ == "__main__":
    last_sch, last_sum = "", ""
    while True:
        now = datetime.now(pytz.timezone('Asia/Jerusalem'))
        today = now.strftime("%Y-%m-%d")
        if now.hour == 15 and now.minute == 40 and last_sch != today:
            get_combined_schedule(); last_sch = today
        if now.hour == 9 and now.minute == 15 and last_sum != today:
            get_morning_summary(); last_sum = today
        if now.hour >= 18 or now.hour <= 9:
            check_final_updates()
        time.sleep(60)

import requests
import time
from datetime import datetime, timedelta
import pytz
from deep_translator import GoogleTranslator

# ==========================================
# --- הגדרות טכניות ומפתחות ---
# ==========================================
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

NBA_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
NCAA_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
GLEAGUE_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba-ght/scoreboard"

translator = GoogleTranslator(source='en', target='iw')
RTL_MARK = "\u200f"
status_cache = {} # מעקב פצועים בזמן אמת

# --- בסיס נתונים - לגיונרים ---
PLAYERS = {
    "NBA": {
        "Deni Avdija": ["דני אבדיה", "פורטלנד", "Trail Blazers"],
        "Danny Wolf": ["דני וולף", "מישיגן", "Michigan"],
        "Ben Saraf": ["בן שרף", "ברוקלין", "Nets"]
    },
    "GLEAGUE": {
        "Ben Saraf": ["בן שרף", "לונג איילנד", "Long Island"]
    },
    "NCAA": {
        "Emanuel Sharp": ["עמנואל שארפ", "יוסטון", "Houston"],
        "Yoav Berman": ["יואב ברמן", "קווינס", "Queens"],
        "Ofri Naveh": ["עופרי נווה", "אורל רוברטס", "Oral Roberts"],
        "Eytan Burg": ["איתן בורג", "טנסי", "Tennessee"],
        "Omer Mayer": ["עומר מאייר", "פורדו", "Purdue"],
        "Noam Dovrat": ["נועם דוברת", "מיאמי", "Miami"],
        "Or Ashkenazi": ["אור אשכנזי", "ליפסקומב", "Lipscomb"],
        "Alon Michaeli": ["אלון מיכאלי", "קולורדו", "Colorado"],
        "Yonatan Levi": ["יונתן לוי", "פפרדיין", "Pepperdine"],
        "Yuval Levin": ["יובל לוין", "פרדו פורט וויין", "Fort Wayne"],
        "Omer Hamama": ["עומר חממה", "קנט סטייט", "Kent State"],
        "Or Paran": ["אור פארן", "מרסיהרסט", "Mercyhurst"],
        "Daniel Gueta": ["דניאל גואטה", "אוקלהומה סטייט", "Oklahoma State"],
        "Erez Foren": ["ארז פורן", "צפון אריזונה", "Northern Arizona"],
        "Shon Abaev": ["שון אבייב", "סינסינטי", "Cincinnati"]
    }
}

# ==========================================
# --- פונקציות עזר ---
# ==========================================

def tr(text):
    try:
        t = translator.translate(text)
        return t.replace("שבילים בלייזרים", "פורטלנד").replace("רשתות", "ברוקלין").replace("לוחמים", "ווריורס")
    except: return text

def send_telegram(text):
    if not text or len(text) < 10: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def get_injury_status(ev, p_en):
    try:
        for comp in ev.get("competitions", []):
            for team in comp.get("competitors", []):
                for injury in team.get("injuries", []):
                    if p_en.lower() in injury.get("displayName", "").lower():
                        return {"status": injury.get("status", "").upper(), "reason": injury.get("reason", "")}
    except: pass
    return {"status": "ACTIVE", "reason": ""}

def check_saraf_location():
    try:
        gl_data = requests.get(GLEAGUE_API, timeout=10).json()
        for ev in gl_data.get("events", []):
            teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
            if any("Long Island" in t for t in teams): return "GLEAGUE"
    except: pass
    return "NBA"

# ==========================================
# --- 1. סיכום בוקר מאוחד (15:32) ---
# ==========================================

def get_morning_summary():
    sections = {"NBA": "", "GLEAGUE": "", "NCAA": ""}
    configs = [(NBA_API, "NBA", PLAYERS["NBA"], "nba"), 
               (GLEAGUE_API, "GLEAGUE", PLAYERS["GLEAGUE"], "nba-ght"), 
               (NCAA_API, "NCAA", PLAYERS["NCAA"], "mens-college-basketball")]

    for api_url, key, db, path in configs:
        try:
            data = requests.get(api_url, timeout=10).json()
            for ev in data.get("events", []):
                if ev["status"]["type"]["state"] != "post": continue
                teams = ev["competitions"][0]["competitors"]
                team_names = [t["team"]["displayName"] for t in teams]
                
                for p_en, info in db.items():
                    if any(info[2] in name for name in team_names):
                        sum_url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/{path}/summary?event={ev['id']}"
                        summary = requests.get(sum_url, timeout=10).json()
                        p_played = False
                        
                        for team_box in summary.get("players", []):
                            for athlete in team_box.get("athletes", []):
                                if p_en.lower() in athlete["athlete"]["displayName"].lower():
                                    p_played = True
                                    s = athlete["stats"]
                                    pts, reb, ast = (s[14], s[13], s[15]) if len(s) > 15 else (s[0], s[1], s[2])
                                    my_t = [t for t in teams if info[2] in t["team"]["displayName"]][0]
                                    opp_t = [t for t in teams if t["id"] != my_t["id"]][0]
                                    res = "✅" if int(my_t["score"]) > int(opp_t["score"]) else "❌"
                                    sections[key] += f"{RTL_MARK}🏀 **{info[0]}**\n{RTL_MARK}{res} {my_t['score']} - {opp_t['score']} על {tr(opp_t['team']['shortDisplayName'])}\n{RTL_MARK}📊 {pts} נק', {reb} ריב', {ast} אס'\n\n"
                        
                        if not p_played and p_en == "Ben Saraf" and key == "NBA":
                            sections["NBA"] += f"{RTL_MARK}🏀 **בן שרף**\n{RTL_MARK}⬇️ לא שיחק ב-NBA (ירד לסגל הג'י ליג)\n\n"
        except: continue

    final_msg = ""
    for k in ["NBA", "GLEAGUE", "NCAA"]:
        if sections[k]:
            title = "NBA" if k == "NBA" else ("G-LEAGUE" if k == "GLEAGUE" else "מכללות")
            final_msg += f"{RTL_MARK}🇮🇱 **סיכום לגיונרים - {title}** 🇮🇱\n\n{sections[k]}\n"
    send_telegram(final_msg)

# ==========================================
# --- 2. לו''ז לגיונרים + מעקב פצועים (15:33) ---
# ==========================================

def get_upcoming_israelis():
    sections = {"NBA": "", "GLEAGUE": "", "NCAA": ""}
    saraf_loc = check_saraf_location()
    global status_cache
    status_cache = {}

    configs = [(NBA_API, "NBA", PLAYERS["NBA"]), (GLEAGUE_API, "GLEAGUE", PLAYERS["GLEAGUE"]), (NCAA_API, "NCAA", PLAYERS["NCAA"])]
    
    for api_url, key, db in configs:
        try:
            data = requests.get(api_url, timeout=10).json()
            for ev in data.get("events", []):
                if ev["status"]["type"]["state"] == "post": continue
                teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
                for p_en, info in db.items():
                    if any(info[2] in t for t in teams):
                        if p_en == "Ben Saraf" and key != saraf_loc: continue
                        
                        inj = get_injury_status(ev, p_en)
                        note = " ⚠️ (בסימן שאלה)" if "QUESTIONABLE" in inj["status"] or "GTD" in inj["status"] else ""
                        if note: status_cache[f"{p_en}_{ev['id']}"] = "QUESTIONABLE"
                        
                        vs = [t for t in teams if info[2] not in t][0]
                        tm = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
                        down = " ⬇️ (ירד לג'י ליג)" if p_en == "Ben Saraf" and saraf_loc == "GLEAGUE" else ""
                        
                        sections[key] += f"{RTL_MARK}🏀 **{info[0]}**{note}{down}\n{RTL_MARK}🆚 נגד: {tr(vs)}\n{RTL_MARK}⏰ שעה: **{tm.strftime('%H:%M')}**\n\n"
        except: continue

    final_msg = ""
    for k in ["NBA", "GLEAGUE", "NCAA"]:
        if sections[k]:
            title = "NBA" if k == "NBA" else ("G-LEAGUE" if k == "GLEAGUE" else "מכללות")
            final_msg += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה - {title}** 🇮🇱\n\n{sections[k]}\n"
    send_telegram(final_msg if final_msg else f"{RTL_MARK}🇮🇱 אין משחקי לגיונרים הלילה")

# ==========================================
# --- 3. לוח NBA כללי (15:40) ---
# ==========================================

def get_nba_full_schedule():
    try:
        data = requests.get(NBA_API, timeout=10).json()
        games = []
        for ev in data.get("events", []):
            tm = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
            t_data = ev["competitions"][0]["competitors"]
            away, home = t_data[1]["team"]["displayName"], t_data[0]["team"]["displayName"]
            isr = ["Nets", "Trail Blazers", "Michigan"]
            a_s = f"{tr(away)} 🇮🇱" if any(x in away for x in isr) else tr(away)
            h_s = f"{tr(home)} 🇮🇱" if any(x in home for x in isr) else tr(home)
            games.append((tm, f"{RTL_MARK}⏰ **{tm.strftime('%H:%M')}**\n{RTL_MARK}🏀 {a_s} 🆚 {h_s}"))
        
        if games:
            games.sort(key=lambda x: x[0])
            msg = f"{RTL_MARK}🏀 ══ לוח המשחקים להיום בלילה ══ 🏀\n\n" + "\n\n".join([g[1] for g in games]) + f"\n\n{RTL_MARK}צפייה מהנה! 📺"
            send_telegram(msg)
    except: pass

# ==========================================
# --- 4. עדכוני פציעות בזמן אמת ---
# ==========================================

def check_final_updates():
    global status_cache
    if not status_cache: return
    for url in [NBA_API, NCAA_API, GLEAGUE_API]:
        try:
            resp = requests.get(url, timeout=10).json()
            for ev in resp.get("events", []):
                teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
                all_db = {**PLAYERS["NBA"], **PLAYERS["GLEAGUE"], **PLAYERS["NCAA"]}
                for p_en, info in all_db.items():
                    key = f"{p_en}_{ev['id']}"
                    if status_cache.get(key) == "QUESTIONABLE":
                        if any(info[2] in t for t in teams):
                            inj = get_injury_status(ev, p_en)
                            if inj["status"] in ["ACTIVE", "PROBABLE"]:
                                send_telegram(f"{RTL_MARK}🇮🇱 **עדכון סופי: הוא משחק!** 🇮🇱\n\n{RTL_MARK}🏀 *{info[0]}* כשיר ויופיע הלילה! ✅")
                                status_cache[key] = "FINAL"
                            elif "OUT" in inj["status"]:
                                r = f" ({inj['reason']})" if inj['reason'] else ""
                                send_telegram(f"{RTL_MARK}🇮🇱 **עדכון סופי: לא ישחק** 🇮🇱\n\n{RTL_MARK}🏀 *{info[0]}* בחוץ הלילה{r}. ❌")
                                status_cache[key] = "FINAL"
        except: pass

# ==========================================
# --- לולאת הרצה ---
# ==========================================

if __name__ == "__main__":
    while True:
        now = datetime.now(pytz.timezone('Asia/Jerusalem'))
        if now.hour == 16 and now.minute == 4: get_morning_summary(); time.sleep(61)
        if now.hour == 16 and now.minute == 4: get_upcoming_israelis(); time.sleep(61)
        if now.hour == 16 and now.minute == 4: get_nba_full_schedule(); time.sleep(61)
        if now.hour >= 18 or now.hour <= 9: check_final_updates()
        time.sleep(30)

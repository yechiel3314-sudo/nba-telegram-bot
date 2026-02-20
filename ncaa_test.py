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

NBA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
NCAA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
GLEAGUE_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba-ght/scoreboard"

translator = GoogleTranslator(source='en', target='iw')
RTL_MARK = "\u200f" 
status_cache = {} # מנגנון מעקב פצועים

# ==========================================
# --- בסיס נתונים ---
# ==========================================
NBA_DATABASE = {
    "Deni Avdija": ["דני אבדיה", "פורטלנד", "Trail Blazers"],
    "Danny Wolf": ["דני וולף", "מישיגן", "Michigan"],
    "Ben Saraf": ["בן שרף", "ברוקלין", "Nets"]
}

GLEAGUE_DATABASE = {
    "Ben Saraf": ["בן שרף", "לונג איילנד", "Long Island"]
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
    "Yuval Levin": ["יובל לוין", "פרדו פורט וויין", "Fort Wayne"],
    "Omer Hamama": ["עומר חממה", "קנט סטייט", "Kent State"],
    "Or Paran": ["אור פארן", "מרסיהרסט", "Mercyhurst"],
    "Daniel Gueta": ["דניאל גואטה", "אוקלהומה סטייט", "Oklahoma State"],
    "Erez Foren": ["ארז פורן", "צפון אריזונה", "Northern Arizona"],
    "Shon Abaev": ["שון אבייב", "סינסינטי", "Cincinnati"]
}

# ==========================================
# --- פונקציות ליבה ---
# ==========================================

def tr(text):
    try:
        t = translator.translate(text)
        return t.replace("שבילים בלייזרים", "פורטלנד").replace("רשתות", "ברוקלין").replace("לוחמים", "ווריורס")
    except: return text

def send_telegram(text):
    if not text or len(text) < 5: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def get_detailed_injury(ev, player_name_en):
    try:
        for comp in ev.get("competitions", []):
            for team in comp.get("competitors", []):
                for injury in team.get("injuries", []):
                    if player_name_en in injury.get("displayName", ""):
                        return {"status": injury.get("status", "").upper(), "reason": injury.get("reason", "")}
    except: pass
    return {"status": "ACTIVE", "reason": ""}

# ==========================================
# --- 1. סיכום לגיונרים (15:32) ---
# ==========================================

def get_morning_summary():
    report = f"{RTL_MARK}🇮🇱 **סיכום לגיונרים הלילה** 🇮🇱\n\n"
    found_any = False
    leagues = [(NBA_SCOREBOARD, "nba", NBA_DATABASE), (GLEAGUE_SCOREBOARD, "nba-ght", GLEAGUE_DATABASE), (NCAA_SCOREBOARD, "mens-college-basketball", NCAA_DATABASE)]

    for url, path, db in leagues:
        try:
            resp = requests.get(url, timeout=10).json()
            for ev in resp.get("events", []):
                if ev["status"]["type"]["state"] != "post": continue
                teams = ev["competitions"][0]["competitors"]
                team_names = [t["team"]["displayName"] for t in teams]

                for p_en, info in db.items():
                    if any(info[2].lower() in name.lower() for name in team_names):
                        bs = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/{path}/summary?event={ev['id']}").json()
                        p_played = False
                        for t_stats in bs.get("players", []):
                            for athlete in t_stats.get("athletes", []):
                                if p_en.lower() in athlete["athlete"]["displayName"].lower():
                                    p_played = True
                                    s = athlete["stats"]
                                    pts, reb, ast = (s[14], s[13], s[15]) if len(s) > 15 else (s[0], s[1], s[2])
                                    my_t = [t for t in teams if info[2].lower() in t["team"]["displayName"].lower()][0]
                                    opp_t = [t for t in teams if t["id"] != my_t["id"]][0]
                                    res = "✅" if int(my_t["score"]) > int(opp_t["score"]) else "❌"
                                    report += f"{RTL_MARK}🏀 **{info[0]}** ({info[1]})\n{RTL_MARK}{res} {my_t['score']} - {opp_t['score']} על {tr(opp_t['team']['shortDisplayName'])}\n{RTL_MARK}📊 {pts} נק', {reb} ריב', {ast} אס'\n\n"
                                    found_any = True
                        if not p_played and p_en == "Ben Saraf" and path == "nba":
                            report += f"{RTL_MARK}🏀 **בן שרף**\n{RTL_MARK}⬇️ לא שיחק ב-NBA הלילה (ירד לסגל הג'י ליג)\n\n"
                            found_any = True
        except: pass
    if found_any: send_telegram(report)

# ==========================================
# --- 2. לו''ז לגיונרים + פצועים (15:33) ---
# ==========================================

def get_combined_schedule():
    msg = f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה** 🇮🇱\n\n"
    found = False
    global status_cache
    status_cache = {} 

    for url, db in [(NBA_SCOREBOARD, NBA_DATABASE), (GLEAGUE_SCOREBOARD, GLEAGUE_DATABASE), (NCAA_SCOREBOARD, NCAA_DATABASE)]:
        try:
            resp = requests.get(url, timeout=10).json()
            for ev in resp.get("events", []):
                if ev["status"]["type"]["state"] == "post": continue
                teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
                for p_en, info in db.items():
                    if any(info[2].lower() in t.lower() for t in teams):
                        vs = [t for t in teams if info[2].lower() not in t.lower()][0]
                        tm = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
                        inj = get_detailed_injury(ev, p_en)
                        note = " ⚠️ (בסימן שאלה)" if "QUESTIONABLE" in inj["status"] or "GTD" in inj["status"] else ""
                        if note: status_cache[f"{p_en}_{ev['id']}"] = "QUESTIONABLE"
                        msg += f"{RTL_MARK}🏀 **{info[0]}**{note} ({info[1]})\n{RTL_MARK}🆚 נגד: {tr(vs)}\n{RTL_MARK}⏰ שעה: **{tm.strftime('%H:%M')}**\n\n"
                        found = True
        except: pass
    if found: send_telegram(msg)

# ==========================================
# --- 3. לוח NBA כללי (15:40) ---
# ==========================================

def get_all_nba_games():
    try:
        resp = requests.get(NBA_SCOREBOARD, timeout=10).json()
        games = []
        for ev in resp.get("events", []):
            tm = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
            teams = ev["competitions"][0]["competitors"]
            away, home = teams[1]["team"]["displayName"], teams[0]["team"]["displayName"]
            isr = ["Nets", "Trail Blazers", "Michigan"]
            a_s = f"{tr(away)} 🇮🇱" if any(x in away for x in isr) else tr(away)
            h_s = f"{tr(home)} 🇮🇱" if any(x in home for x in isr) else tr(home)
            games.append((tm, f"{RTL_MARK}⏰ **{tm.strftime('%H:%M')}**\n{RTL_MARK}🏀 {a_s} 🆚 {h_s}"))
        if games:
            games.sort(key=lambda x: x[0])
            send_telegram(f"{RTL_MARK}🏀 ══ לוח המשחקים להיום בלילה ══ 🏀\n\n" + "\n\n".join([g[1] for g in games]) + f"\n\n{RTL_MARK}צפייה מהנה! 📺")
    except: pass

# ==========================================
# --- 4. מנגנון מעקב פצועים בזמן אמת ---
# ==========================================

def check_final_updates():
    global status_cache
    if not status_cache: return
    for url in [NBA_SCOREBOARD, NCAA_SCOREBOARD, GLEAGUE_SCOREBOARD]:
        try:
            resp = requests.get(url, timeout=10).json()
            for ev in resp.get("events", []):
                teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
                all_db = {**NBA_DATABASE, **GLEAGUE_DATABASE, **NCAA_DATABASE}
                for p_en, info in all_db.items():
                    key = f"{p_en}_{ev['id']}"
                    if status_cache.get(key) == "QUESTIONABLE":
                        if any(info[2].lower() in t.lower() for t in teams):
                            inj = get_detailed_injury(ev, p_en)
                            if inj["status"] in ["ACTIVE", "PROBABLE"]:
                                send_telegram(f"{RTL_MARK}🇮🇱 **עדכון סופי: הוא משחק!** 🇮🇱\n\n{RTL_MARK}🏀 *{info[0]}* כשיר ויופיע הלילה! ✅")
                                status_cache[key] = "FINAL"
                            elif "OUT" in inj["status"]:
                                r = f" ({inj['reason']})" if inj['reason'] else ""
                                send_telegram(f"{RTL_MARK}🇮🇱 **עדכון סופי: לא ישחק** 🇮🇱\n\n{RTL_MARK}🏀 *{info[0]}* בחוץ הלילה{r}. ❌")
                                status_cache[key] = "FINAL"
        except: pass

# ==========================================
# --- לולאה ראשית ---
# ==========================================

if __name__ == "__main__":
    while True:
        now = datetime.now(pytz.timezone('Asia/Jerusalem'))
        if now.hour == 15 and now.minute == 57: get_morning_summary()
        if now.hour == 15 and now.minute == 57: get_combined_schedule()
        if now.hour == 15 and now.minute == 57: get_all_nba_games()
        if now.hour >= 18 or now.hour <= 9: check_final_updates()
        time.sleep(30)

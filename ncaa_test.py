import requests
import time
from datetime import datetime, timedelta
import pytz
from deep_translator import GoogleTranslator

# ==========================================
# --- הגדרות טכניות ---
# ==========================================
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

NBA_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
NCAA_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
GLEAGUE_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba-ght/scoreboard"

translator = GoogleTranslator(source='en', target='iw')
RTL_MARK = "\u200f"
status_cache = {}

PLAYERS = {
    "NBA": {
        "Deni Avdija": ["דני אבדיה", "פורטלנד טרייל בלייזרס", "Trail Blazers"],
        "Danny Wolf": ["דני וולף", "מישיגן", "Michigan"],
        "Ben Saraf": ["בן שרף", "ברוקלין נטס", "Nets"]
    },
    "GLEAGUE": {
        "Ben Saraf": ["בן שרף", "לונג איילנד נטס", "Long Island"]
    },
    "NCAA": {
        "Danny Wolf": ["דני וולף", "מישיגן", "Michigan"],
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

def tr(text):
    try:
        t = translator.translate(text)
        corrections = {
            "שבילים בלייזרים": "פורטלנד טרייל בלייזרס", "רשתות": "ברוקלין נטס", 
            "לוחמים": "גולדן סטייט ווריורס", "בוכנות": "דטרויט פיסטונס", 
            "חום": "מיאמי היט", "מלכים": "סקרמנטו קינגס", "ג'אז ביוטה": "יוטה ג'אז"
        }
        for eng, heb in corrections.items(): t = t.replace(eng, heb)
        return t
    except: return text

def send_telegram(text):
    if not text or len(text) < 5: return
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

# --- הודעה 18:37: סיכום תוצאות כללי ---
def get_nba_scores_summary():
    results = []
    try:
        date_str = (datetime.now() - timedelta(hours=15)).strftime("%Y%m%d")
        data = requests.get(f"{NBA_API}?dates={date_str}").json()
        for ev in data.get("events", []):
            if ev["status"]["type"]["state"] == "post":
                t = ev["competitions"][0]["competitors"]
                h_f, a_f = tr(t[0]["team"]["displayName"]), tr(t[1]["team"]["displayName"])
                h_s, a_s = int(t[0]["score"]), int(t[1]["score"])
                win_icon = "🏆"
                if h_s > a_s:
                    l1, l2 = f"{win_icon} ** {h_f} {h_s} **", f"🏀 {a_f} {a_s}"
                else:
                    l1, l2 = f"{win_icon} ** {a_f} {a_s} **", f"🏀 {h_f} {h_s}"
                results.append(f"{RTL_MARK}{l1}\n{RTL_MARK}{l2}")
        if results:
            send_telegram(f"{RTL_MARK}🏁 ** סיכום תוצאות הלילה - NBA ** 🏁\n\n" + "\n\n".join(results))
    except: pass

# --- הודעה 18:36: סיכום ביצועי לגיונרים ---
def get_morning_summary():
    sections = {"NBA": "", "GLEAGUE": "", "NCAA": ""}
    found_players = set()
    leagues = [(NBA_API, "NBA", PLAYERS["NBA"], "nba"), (GLEAGUE_API, "GLEAGUE", PLAYERS["GLEAGUE"], "nba-ght"), (NCAA_API, "NCAA", PLAYERS["NCAA"], "mens-college-basketball")]
    for api_url, key, db, path in leagues:
        try:
            date_str = (datetime.now() - timedelta(hours=15)).strftime("%Y%m%d")
            data = requests.get(f"{api_url}?dates={date_str}").json()
            for ev in data.get("events", []):
                if ev["status"]["type"]["state"] == "post":
                    summary = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/{path}/summary?event={ev['id']}").json()
                    for p_en, info in db.items():
                        if f"{p_en}_{ev['id']}" in found_players: continue
                        for t_box in summary.get("players", []):
                            for athlete in t_box.get("athletes", []):
                                if p_en.lower() in athlete["athlete"]["displayName"].lower():
                                    found_players.add(f"{p_en}_{ev['id']}")
                                    s = athlete["stats"]
                                    try: pts, reb, ast = (s[0], s[1], s[2]) if key == "NCAA" else (s[14], s[13], s[15])
                                    except: pts, reb, ast = s[0], s[1], s[2]
                                    teams = ev["competitions"][0]["competitors"]
                                    my_t = [t for t in teams if t["team"]["id"] == t_box["team"]["id"]][0]
                                    opp_t = [t for t in teams if t["team"]["id"] != t_box["team"]["id"]][0]
                                    res = "✅" if int(my_t["score"]) > int(opp_t["score"]) else "❌"
                                    sections[key] += f"{RTL_MARK}🏀 ** {info[0]} **\n{RTL_MARK}{res} {my_t['score']} - {opp_t['score']} נגד {tr(opp_t['team']['displayName'])}\n{RTL_MARK}📊 ** {pts} נק', {reb} ריב', {ast} אס' **\n\n"
        except: continue
    for k, title in [("NBA", "NBA"), ("GLEAGUE", "G-LEAGUE"), ("NCAA", "מכללות")]:
        if sections[k]: send_telegram(f"{RTL_MARK}🇮🇱 ** סיכום לגיונרים - {title} ** 🇮🇱\n\n{sections[k]}")

# --- הודעה 18:35: לו"ז לגיונרים להלילה ---
def get_upcoming_israelis():
    sections = {"NBA": "", "GLEAGUE": "", "NCAA": ""}
    now_isr = datetime.now(pytz.timezone('Asia/Jerusalem'))
    saraf_in_gleague = False
    try:
        g_data = requests.get(GLEAGUE_API).json()
        saraf_in_gleague = any("Long Island" in t["team"]["displayName"] for ev in g_data.get("events", []) for t in ev["competitions"][0]["competitors"])
    except: pass
    configs = [(NBA_API, "NBA", PLAYERS["NBA"]), (GLEAGUE_API, "GLEAGUE", PLAYERS["GLEAGUE"]), (NCAA_API, "NCAA", PLAYERS["NCAA"])]
    for api_url, key, db in configs:
        try:
            data = requests.get(api_url).json()
            for ev in data.get("events", []):
                if ev["status"]["type"]["state"] == "pre":
                    tm = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
                    if now_isr <= tm <= now_isr + timedelta(hours=24):
                        teams = ev["competitions"][0]["competitors"]
                        for p_en, info in db.items():
                            if p_en == "Ben Saraf" and key == "NBA" and saraf_in_gleague: continue
                            if any(info[2].lower() in t["team"]["displayName"].lower() for t in teams):
                                vs = [t["team"]["displayName"] for t in teams if info[2].lower() not in t["team"]["displayName"].lower()][0]
                                inj = get_injury_status(ev, p_en)
                                note = f" {RTL_MARK}⚠️ (בסימן שאלה)" if "QUESTIONABLE" in inj["status"] or "GTD" in inj["status"] else ""
                                if note: status_cache[f"{p_en}_{ev['id']}"] = "QUESTIONABLE"
                                sections[key] += f"{RTL_MARK}🏀 ** {info[0]} ** {note}\n{RTL_MARK}🆚 נגד: ** {tr(vs)} **\n{RTL_MARK}⏰ שעה: ** {tm.strftime('%H:%M')} **\n\n"
        except: continue
    for k, title in [("NBA", "NBA"), ("GLEAGUE", "G-LEAGUE"), ("NCAA", "מכללות")]:
        if sections[k]: send_telegram(f"{RTL_MARK}🇮🇱 ** משחקי לגיונרים הלילה - {title} ** 🇮🇱\n\n{sections[k]}")

# --- הודעה 18:34: לו"ז כללי NBA ---
def get_nba_full_schedule():
    now_isr = datetime.now(pytz.timezone('Asia/Jerusalem'))
    games = []
    try:
        data = requests.get(NBA_API).json()
        for ev in data.get("events", []):
            tm = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
            if now_isr <= tm <= now_isr + timedelta(hours=24):
                t = ev["competitions"][0]["competitors"]
                a, h = tr(t[1]["team"]["displayName"]), tr(t[0]["team"]["displayName"])
                games.append((tm, f"{RTL_MARK}⏰ ** {tm.strftime('%H:%M')} **\n{RTL_MARK}🏀 {a} 🆚 {h}"))
        if games:
            games.sort(key=lambda x: x[0])
            send_telegram(f"{RTL_MARK}🏀 ══ ** לוח המשחקים להיום בלילה ** ══ 🏀\n\n" + "\n\n".join([g[1] for g in games]))
    except: pass

def check_final_updates():
    global status_cache
    if not status_cache: return
    for url in [NBA_API, NCAA_API, GLEAGUE_API]:
        try:
            resp = requests.get(url).json()
            for ev in resp.get("events", []):
                all_p = {**PLAYERS["NBA"], **PLAYERS["GLEAGUE"], **PLAYERS["NCAA"]}
                for p_en, info in all_p.items():
                    key = f"{p_en}_{ev['id']}"
                    if status_cache.get(key) == "QUESTIONABLE":
                        inj = get_injury_status(ev, p_en)
                        if inj["status"] in ["ACTIVE", "PROBABLE"]:
                            send_telegram(f"{RTL_MARK}🇮🇱 ** עדכון סופי: {info[0]} משחק! ** ✅")
                            status_cache[key] = "FINAL"
                        elif "OUT" in inj["status"]:
                            send_telegram(f"{RTL_MARK}🇮🇱 ** עדכון סופי: {info[0]} בחוץ ** ❌")
                            status_cache[key] = "FINAL"
        except: pass

# ==========================================
# --- לולאה ראשית - זמני שליחה ---
# ==========================================
if __name__ == "__main__":
    print("הבוט התחיל לעבוד...")
    while True:
        now = datetime.now(pytz.timezone('Asia/Jerusalem'))
        curr = now.strftime("%H:%M")

        # 1. לו"ז NBA כללי ב-18:34
        if curr == "18:45":
            get_nba_full_schedule()
            time.sleep(61)

        # 2. לו"ז לגיונרים ב-18:35
        elif curr == "18:45":
            get_upcoming_israelis()
            time.sleep(61)

        # 3. סיכום ביצועי לגיונרים מהבוקר ב-18:36
        elif curr == "18:45":
            get_morning_summary()
            time.sleep(61)

        # 4. סיכום תוצאות כללי מהבוקר ב-18:37
        elif curr == "18:45":
            get_nba_scores_summary()
            time.sleep(61)

        # בדיקת פציעות כל דקה מ-18:40
        if (now.hour == 18 and now.minute >= 40) or (now.hour > 18) or (now.hour <= 9):
            check_final_updates()
            
        time.sleep(30)

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
        "Deni Avdija": ["דני אבדיה", "פורטלנד", "Trail Blazers"],
        "Danny Wolf": ["דני וולף", "מישיגן", "Michigan"],
        "Ben Saraf": ["בן שרף", "ברוקלין", "Nets"]
    },
    "GLEAGUE": {
        "Ben Saraf": ["בן שרף", "לונג איילנד", "Long Island"]
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
        corrections = {"שבילים בלייזרים": "פורטלנד", "רשתות": "ברוקלין", "לוחמים": "ווריורס", "בוכנות": "פיסטונס"}
        for eng, heb in corrections.items(): t = t.replace(eng, heb)
        return t
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

# ==========================================
# --- 1. סיכום לגיונרים ---
# ==========================================
def get_morning_summary():
    sections = {"NBA": "", "GLEAGUE": "", "NCAA": ""}
    now_utc = datetime.now(pytz.utc)
    found_players = set()
    leagues = [(NBA_API, "NBA", PLAYERS["NBA"], "nba"), 
               (GLEAGUE_API, "GLEAGUE", PLAYERS["GLEAGUE"], "nba-ght"), 
               (NCAA_API, "NCAA", PLAYERS["NCAA"], "mens-college-basketball")]

    for api_url, key, db, path in leagues:
        try:
            for date_offset in [-1, 0]:
                date_str = (datetime.now() + timedelta(days=date_offset)).strftime("%Y%m%d")
                data = requests.get(f"{api_url}?dates={date_str}", timeout=10).json()
                for ev in data.get("events", []):
                    game_time = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    if ev["status"]["type"]["state"] == "post" and (now_utc - timedelta(hours=28)) <= game_time <= now_utc:
                        sum_url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/{path}/summary?event={ev['id']}"
                        summary = requests.get(sum_url, timeout=10).json()
                        teams = ev["competitions"][0]["competitors"]
                        for p_en, info in db.items():
                            p_key = f"{p_en}_{ev['id']}"
                            if p_key in found_players: continue
                            for t_box in summary.get("players", []):
                                for athlete in t_box.get("athletes", []):
                                    if p_en.lower() in athlete["athlete"]["displayName"].lower():
                                        found_players.add(p_key)
                                        s = athlete["stats"]
                                        try:
                                            pts = s[0] if key == "NCAA" else s[14]
                                            reb = s[1] if key == "NCAA" else s[13]
                                            ast = s[2] if key == "NCAA" else s[15]
                                        except: pts, reb, ast = s[0], s[1], s[2]
                                        my_t = [t for t in teams if t["team"]["id"] == t_box["team"]["id"]][0]
                                        opp_t = [t for t in teams if t["team"]["id"] != t_box["team"]["id"]][0]
                                        res = "✅" if int(my_t["score"]) > int(opp_t["score"]) else "❌"
                                        sections[key] += f"{RTL_MARK}🏀 **{info[0]}**\n{RTL_MARK}{res} {my_t['score']} - {opp_t['score']} נגד {tr(opp_t['team']['shortDisplayName'])} ({tr(my_t['team']['displayName'])})\n{RTL_MARK}📊 **{pts} נק', {reb} ריב', {ast} אס'**\n\n"
        except: continue
    final_msg = ""
    for k in ["NBA", "GLEAGUE", "NCAA"]:
        if sections[k]:
            title = "NBA" if k == "NBA" else ("G-LEAGUE" if k == "GLEAGUE" else "מכללות")
            final_msg += f"{RTL_MARK}🇮🇱 **סיכום לגיונרים - {title}** 🇮🇱\n\n{sections[k]}\n"
    send_telegram(final_msg)

# ==========================================
# --- 2. תוצאות הלילה (הודעה חדשה) ---
# ==========================================
def get_nba_scores_summary():
    now_utc = datetime.now(pytz.utc)
    results = []
    try:
        date_str = (datetime.now() - timedelta(hours=12)).strftime("%Y%m%d")
        data = requests.get(f"{NBA_API}?dates={date_str}", timeout=10).json()
        for ev in data.get("events", []):
            if ev["status"]["type"]["state"] == "post":
                t = ev["competitions"][0]["competitors"]
                home = t[0]
                away = t[1]
                h_name = tr(home["team"]["displayName"])
                a_name = tr(away["team"]["displayName"])
                h_score = int(home["score"])
                a_score = int(away["score"])
                
                h_prefix = "🔹 " if h_score > a_score else ""
                a_prefix = "🔹 " if a_score > h_score else ""
                
                results.append(f"{RTL_MARK}{a_prefix}{a_name} {a_score}\n{RTL_MARK}{h_prefix}{h_name} {h_score}")
        
        if results:
            msg = f"{RTL_MARK}🏁 **תוצאות משחקי הלילה ב-NBA** 🏁\n\n" + "\n\n".join(results)
            send_telegram(msg)
    except: pass

# ==========================================
# --- 3. לו''ז לגיונרים ---
# ==========================================
def get_upcoming_israelis():
    sections = {"NBA": "", "GLEAGUE": "", "NCAA": ""}
    now_isr = datetime.now(pytz.timezone('Asia/Jerusalem'))
    saraf_in_gleague = False
    try:
        g_data = requests.get(f"{GLEAGUE_API}", timeout=10).json()
        for ev in g_data.get("events", []):
            if any("Long Island" in t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]): saraf_in_gleague = True
    except: pass

    configs = [(NBA_API, "NBA", PLAYERS["NBA"]), (GLEAGUE_API, "GLEAGUE", PLAYERS["GLEAGUE"]), (NCAA_API, "NCAA", PLAYERS["NCAA"])]
    for api_url, key, db in configs:
        try:
            for date_offset in [0, 1]:
                date_str = (datetime.now() + timedelta(days=date_offset)).strftime("%Y%m%d")
                data = requests.get(f"{api_url}?dates={date_str}", timeout=10).json()
                for ev in data.get("events", []):
                    if ev["status"]["type"]["state"] != "pre": continue
                    tm = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
                    if now_isr <= tm <= now_isr + timedelta(hours=24):
                        teams = ev["competitions"][0]["competitors"]
                        for p_en, info in db.items():
                            if p_en == "Ben Saraf" and key == "NBA" and saraf_in_gleague: continue
                            if any(info[2].lower() in t["team"]["displayName"].lower() for t in teams):
                                vs = [t["team"]["displayName"] for t in teams if info[2].lower() not in t["team"]["displayName"].lower()][0]
                                inj = get_injury_status(ev, p_en)
                                note = " ⚠️ (בסימן שאלה)" if "QUESTIONABLE" in inj["status"] or "GTD" in inj["status"] else ""
                                if note: status_cache[f"{p_en}_{ev['id']}"] = "QUESTIONABLE"
                                sections[key] += f"{RTL_MARK}🏀 **{info[0]}**{note}\n{RTL_MARK}🆚 נגד: **{tr(vs)}**\n{RTL_MARK}⏰ שעה: **{tm.strftime('%H:%M')}**\n\n"
        except: continue
    final_msg = ""
    for k in ["NBA", "GLEAGUE", "NCAA"]:
        if sections[k]:
            title = "NBA" if k == "NBA" else ("G-LEAGUE" if k == "GLEAGUE" else "מכללות")
            final_msg += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה - {title}** 🇮🇱\n\n{sections[k]}\n"
    send_telegram(final_msg)

# ==========================================
# --- 4. לוח NBA כללי ---
# ==========================================
def get_nba_full_schedule():
    now_isr = datetime.now(pytz.timezone('Asia/Jerusalem'))
    games = []
    try:
        for date_offset in [0, 1]:
            date_str = (datetime.now() + timedelta(days=date_offset)).strftime("%Y%m%d")
            data = requests.get(f"{NBA_API}?dates={date_str}", timeout=10).json()
            for ev in data.get("events", []):
                tm = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
                if now_isr <= tm <= now_isr + timedelta(hours=24):
                    t_data = ev["competitions"][0]["competitors"]
                    away, home = t_data[1]["team"]["displayName"], t_data[0]["team"]["displayName"]
                    isr_teams = ["Nets", "Trail Blazers", "Michigan", "Long Island"]
                    a_s = f"{tr(away)} 🇮🇱" if any(x in away for x in isr_teams) else tr(away)
                    h_s = f"{tr(home)} 🇮🇱" if any(x in home for x in isr_teams) else tr(home)
                    games.append((tm, f"{RTL_MARK}⏰ **{tm.strftime('%H:%M')}**\n{RTL_MARK}🏀 {a_s} 🆚 {h_s}"))
        if games:
            games.sort(key=lambda x: x[0])
            msg = f"{RTL_MARK}🏀 ══ **לוח המשחקים להיום בלילה** ══ 🏀\n\n" + "\n\n".join([g[1] for g in games]) + f"\n\n{RTL_MARK}צפייה מהנה! 📺"
            send_telegram(msg)
    except: pass

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
                        if any(info[2].lower() in t.lower() for t in teams):
                            inj = get_injury_status(ev, p_en)
                            if inj["status"] in ["ACTIVE", "PROBABLE"]:
                                send_telegram(f"{RTL_MARK}🇮🇱 **עדכון סופי: הוא משחק!** 🇮🇱\n\n{RTL_MARK}🏀 **{info[0]}** כשיר ויופיע הלילה! ✅")
                                status_cache[key] = "FINAL"
                            elif "OUT" in inj["status"]:
                                send_telegram(f"{RTL_MARK}🇮🇱 **עדכון סופי: לא ישחק** 🇮🇱\n\n{RTL_MARK}🏀 **{info[0]}** בחוץ הלילה. ❌")
                                status_cache[key] = "FINAL"
        except: pass

if __name__ == "__main__":
    while True:
        now = datetime.now(pytz.timezone('Asia/Jerusalem'))
        # הכל מכוון לשעה 16:22 כבקשתך
        if now.hour == 16 and now.minute == 22: 
            get_nba_scores_summary()  # ההודעה החדשה של תוצאות הלילה
            get_morning_summary()
            get_upcoming_israelis()
            get_nba_full_schedule()
            time.sleep(61)
        if now.hour >= 18 or now.hour <= 9: check_final_updates()
        time.sleep(30)

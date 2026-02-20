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

NCAA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
NBA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
GLEAGUE_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba-ght/scoreboard"

translator = GoogleTranslator(source='en', target='iw')
RTL_MARK = "\u200f" 
status_cache = {} 

# ==========================================
# --- בסיסי נתונים מאוחדים ---
# ==========================================
NBA_DATABASE = {
    "Deni Avdija": ["דני אבדיה", "פורטלנד", "Trail Blazers"],
    "Danny Wolf": ["דני וולף", "מישיגן", "Michigan"],
    "Ben Saraf": ["בן שרף", "ברוקלין", "Nets"]
}

GLEAGUE_DATABASE = {
    "Ben Saraf": ["בן שרף", "לונג איילנד", "Long Island Nets", "Blue Coats", "Squadron"]
}

NCAA_DATABASE = {
    "Emanuel Sharp": ["עמנואל שארפ", "יוסטון", "Houston"],
    "Yoav Berman": ["יואב ברמן", "קווינס", "Queens"],
    "Ofri Naveh": ["עופרי נווה", "אורל רוברטס", "Oral Roberts"],
    "Eytan Burg": ["איתן בורג", "טנסי", "Tennessee Volunteers"],
    "Omer Mayer": ["עומר מאייר", "פורדו", "Purdue"],
    "Noam Dovrat": ["נועם דוברת", "מיאמי", "Miami"],
    "Or Ashkenazi": ["אור אשכנזי", "ליפסקומב", "Lipscomb"],
    "Alon Michaeli": ["אלון מיכאלי", "קולורדו", "Colorado"],
    "Yonatan Levi": ["יונתן לוי", "פפרדיין", "Pepperdine"],
    "Yuval Levin": ["יובל לוין", "פרדו פורט וויין", "Purdue Fort Wayne"],
    "Omer Hamama": ["עומר חממה", "קנט סטייט", "Kent State"],
    "Or Paran": ["אור פארן", "מרסיהרסט", "Mercyhurst"],
    "Daniel Gueta": ["דניאל גואטה", "אוקלהומה סטייט", "Oklahoma State"],
    "Erez Foren": ["ארז פורן", "צפון אריזונה", "Northern Arizona"],
    "Shon Abaev": ["שון אבייב", "סינסינטי", "Cincinnati"]
}

# ==========================================
# --- פונקציות עזר ---
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
# --- 1. סיכום בוקר (15:32) ---
# ==========================================

def get_morning_summary():
    leagues = [
        (NBA_SCOREBOARD, "NBA", NBA_DATABASE, "nba"),
        (GLEAGUE_SCOREBOARD, "ליגת הפיתוח", GLEAGUE_DATABASE, "nba-ght"),
        (NCAA_SCOREBOARD, "המכללות", NCAA_DATABASE, "mens-college-basketball")
    ]
    
    for url, title, db, sport_path in leagues:
        msg = f"{RTL_MARK}🇮🇱 **סיכום לגיונרים - {title}** 🇮🇱\n\n"
        found_any = False
        try:
            resp = requests.get(url, timeout=10).json()
            for ev in resp.get("events", []):
                if ev["status"]["type"]["state"] != "post": continue
                comp = ev["competitions"][0]
                teams = comp["competitors"]
                team_names = [t["team"]["displayName"] for t in teams]

                for p_en, info in db.items():
                    target_team = info[2]
                    # חיפוש גמיש למניעת פספוסים (כמו דני וולף וטנסי)
                    if (isinstance(target_team, list) and any(k in str(team_names) for k in target_team)) or (target_team in str(team_names)):
                        try:
                            bs_url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/{sport_path}/summary?event={ev['id']}"
                            bs_data = requests.get(bs_url, timeout=10).json()
                            player_found_in_stats = False

                            for t_stats in bs_data.get("players", []):
                                for p_stats in t_stats.get("athletes", []):
                                    if p_en.lower() in p_stats["athlete"]["displayName"].lower():
                                        player_found_in_stats = True
                                        s = p_stats["stats"]
                                        pts, reb, ast = (s[14], s[13], s[15]) if len(s) > 15 else (s[0], s[1], s[2])
                                        mins = p_stats.get("minutes", "0")
                                        
                                        my_team = [t for t in teams if info[2] in t["team"]["displayName"] or any(k in t["team"]["displayName"] for k in info[2:] if isinstance(info[2], list))][0]
                                        opp_team = [t for t in teams if t["id"] != my_team["id"]][0]
                                        res = "✅ ניצחון" if int(my_team["score"]) > int(opp_team["score"]) else "❌ הפסד"
                                        
                                        msg += f"{RTL_MARK}🏀 **{info[0]}** ({info[1]})\n{RTL_MARK}{res} {my_team['score']} - {opp_team['score']} על {tr(opp_team['team']['shortDisplayName'])}\n{RTL_MARK}📊 סטטיסטיקה: {pts} נק', {reb} ריב', {ast} אס'\n{RTL_MARK}⏱️ דקות: {mins}\n\n"
                                        found_any = True

                            if not player_found_in_stats and p_en == "Ben Saraf" and title == "NBA":
                                msg += f"{RTL_MARK}🏀 **{info[0]}**\n{RTL_MARK}⬇️ לא שיחק ב-NBA הלילה (ירד לסגל הג'י ליג)\n\n"
                                found_any = True
                        except: pass
            if found_any: send_telegram(msg)
        except: pass

# ==========================================
# --- 2. לו''ז לגיונרים (15:33) ---
# ==========================================

def get_combined_schedule():
    all_games = {"NBA": [], "GLEAGUE": [], "NCAA": []}
    players_handled = set()
    global status_cache
    status_cache = {}

    # סריקת ג'י ליג
    try:
        resp_gl = requests.get(GLEAGUE_SCOREBOARD, timeout=10).json()
        for ev in resp_gl.get("events", []):
            teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
            for p_en, info in GLEAGUE_DATABASE.items():
                if any(k in str(teams) for k in info[2:] if isinstance(info[2], list)) or (info[2] in str(teams)):
                    vs = [t for t in teams if info[2] not in t][0]
                    time_il = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
                    all_games["GLEAGUE"].append((time_il, f"{RTL_MARK}🏀 *{info[0]}* ⬇️ (ירד לסגל הג'י ליג)\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"))
                    players_handled.add(p_en)
    except: pass

    # סריקת NBA ומכללות
    for url, key, db in [(NBA_SCOREBOARD, "NBA", NBA_DATABASE), (NCAA_SCOREBOARD, "NCAA", NCAA_DATABASE)]:
        try:
            resp = requests.get(url, timeout=10).json()
            for ev in resp.get("events", []):
                teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
                for p_en, info in db.items():
                    if p_en in players_handled: continue
                    if info[2] in str(teams):
                        if p_en == "Ben Saraf" and key == "NBA":
                            update_msg = f"\n\n⬇️ **עדכון: {info[0]}** לא משחק (ירד להתאמן בג'י ליג)"
                            for i, (g_time, g_str) in enumerate(all_games["NBA"]):
                                if "ברוקלין" in g_str: all_games["NBA"][i] = (g_time, g_str + update_msg)
                            continue
                        vs = [t for t in teams if info[2] not in t][0]
                        inj = get_detailed_injury(ev, p_en)
                        status_note = " ⚠️ (בסימן שאלה)" if "QUESTIONABLE" in inj["status"] or "GTD" in inj["status"] else ""
                        if status_note: status_cache[f"{p_en}_{ev['id']}"] = "QUESTIONABLE"
                        time_il = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
                        game_str = f"{RTL_MARK}🏀 *{info[0]}*{status_note} ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"
                        all_games[key].append((time_il, game_str))
        except: pass

    full_msg = ""
    for k in ["NBA", "GLEAGUE", "NCAA"]:
        if all_games[k]:
            t_title = "NBA" if k == "NBA" else ("ליגת הפיתוח" if k == "GLEAGUE" else "מכללות")
            full_msg += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה ב{t_title}** 🇮🇱\n\n"
            full_msg += "\n\n".join([g[1] for g in sorted(all_games[k], key=lambda x: x[0])])
            full_msg += "\n\n\n"
    send_telegram(full_msg.strip() if full_msg else f"{RTL_MARK}🇮🇱 אין משחקי לגיונרים הלילה 😴")

# ==========================================
# --- 3. לוח משחקים כללי (15:40) ---
# ==========================================

def get_all_nba_games():
    try:
        resp = requests.get(NBA_SCOREBOARD, timeout=10).json()
        games = []
        for ev in resp.get("events", []):
            time_il = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
            t1 = ev["competitions"][0]["competitors"][0]["team"]["displayName"]
            t2 = ev["competitions"][0]["competitors"][1]["team"]["displayName"]
            isr = ["Nets", "Trail Blazers", "Michigan"]
            t1_s = f"{tr(t1)} 🇮🇱" if any(x in t1 for x in isr) else tr(t1)
            t2_s = f"{tr(t2)} 🇮🇱" if any(x in t2 for x in isr) else tr(t2)
            games.append((time_il, f"{RTL_MARK}‏⏰ **{time_il.strftime('%H:%M')}**\n{RTL_MARK}‏🏀 {t1_s} 🆚 {t2_s}"))
        if games:
            games.sort(key=lambda x: x[0])
            msg = f"{RTL_MARK}🏀 ══ לוח המשחקים להיום בלילה ══ 🏀\n\n" + "\n\n".join([g[1] for g in games]) + f"\n\n{RTL_MARK}צפייה מהנה! 📺"
            send_telegram(msg)
    except: pass

# ==========================================
# --- עדכוני פציעות (המקורי) ---
# ==========================================

def check_final_updates():
    global status_cache
    if not any(v == "QUESTIONABLE" for v in status_cache.values()): return
    for url in [NBA_SCOREBOARD, NCAA_SCOREBOARD, GLEAGUE_SCOREBOARD]:
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
# --- לולאת הרצה ---
# ==========================================

if __name__ == "__main__":
    last_sum, last_sch, last_all = "", "", ""
    while True:
        now = datetime.now(pytz.timezone('Asia/Jerusalem'))
        today = now.strftime("%Y-%m-%d")
        if now.hour == 15 and now.minute == 44 and last_sum != today:
            get_morning_summary(); last_sum = today
        if now.hour == 15 and now.minute == 45 and last_sch != today:
            get_combined_schedule(); last_sch = today
        if now.hour == 15 and now.minute == 45 and last_all != today:
            get_all_nba_games(); last_all = today
        if now.hour >= 18 or now.hour <= 9:
            check_final_updates()
        time.sleep(30)

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
GLEAGUE_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba-ght/scoreboard"

translator = GoogleTranslator(source='en', target='iw')
RTL_MARK = "\u200f" 
status_cache = {} 

# ==========================================
# --- בסיסי נתונים מעודכנים (שמות מלאים למניעת כפילויות) ---
# ==========================================
NBA_DATABASE = {
    "Deni Avdija": ["דני אבדיה", "פורטלנד", "Portland Trail Blazers"],
    "Danny Wolf": ["דני וולף", "ברוקלין", "Brooklyn Nets"],
    "Ben Saraf": ["בן שרף", "ברוקלין", "Brooklyn Nets"]
}

GLEAGUE_DATABASE = {
    "Ben Saraf": ["בן שרף", "לונג איילנד", "Long Island Nets", "Delaware Blue Coats", "Birmingham Squadron"]
}

NCAA_DATABASE = {
    "Emanuel Sharp": ["עמנואל שארפ", "יוסטון", "Houston Cougars"],
    "Yoav Berman": ["יואב ברמן", "קווינס", "Queens University Royals"],
    "Ofri Naveh": ["עופרי נווה", "אורל רוברטס", "Oral Roberts Golden Eagles"],
    "Eytan Burg": ["איתן בורג", "טנסי", "Tennessee Volunteers"],
    "Omer Mayer": ["עומר מאייר", "פורדו", "Purdue Boilermakers"],
    "Noam Dovrat": ["נועם דוברת", "מיאמי", "Miami Hurricanes"],
    "Or Ashkenazi": ["אור אשכנזי", "ליפסקומב", "Lipscomb Bisons"],
    "Alon Michaeli": ["אלון מיכאלי", "קולורדו", "Colorado Buffaloes"],
    "Yonatan Levi": ["יונתן לוי", "פפרדיין", "Pepperdine Waves"],
    "Yuval Levin": ["יובל לוין", "פרדו פורט וויין", "Purdue Fort Wayne Mastodons"],
    "Omer Hamama": ["עומר חממה", "קנט סטייט", "Kent State Golden Flashes"],
    "Or Paran": ["אור פארן", "מרסיהרסט", "Mercyhurst Lakers"],
    "Daniel Gueta": ["דניאל גואטה", "אוקלהומה סטייט", "Oklahoma State Cowboys"],
    "Erez Foren": ["ארז פורן", "צפון אריזונה", "Northern Arizona Lumberjacks"],
    "Shon Abaev": ["שון אבייב", "סינסינטי", "Cincinnati Bearcats"]
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
# --- סיכום בוקר ---
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
                    # בדיקת התאמה מדויקת לקבוצה
                    if any(target_team == name for name in team_names):
                        try:
                            bs_url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/{sport_path}/summary?event={ev['id']}"
                            bs_data = requests.get(bs_url, timeout=10).json()
                            for t_stats in bs_data.get("players", []):
                                for p_stats in t_stats.get("athletes", []):
                                    if p_en.lower() in p_stats["athlete"]["displayName"].lower():
                                        s = p_stats["stats"]
                                        # שליפה לפי אינדקסים מעודכנים של ESPN
                                        pts = s[14] if len(s) > 14 else (s[0] if len(s) > 0 else "0")
                                        reb = s[13] if len(s) > 13 else (s[1] if len(s) > 1 else "0")
                                        ast = s[15] if len(s) > 15 else (s[2] if len(s) > 2 else "0")
                                        stl = s[16] if len(s) > 16 else "0"
                                        mins = p_stats.get("minutes", "0")
                                        
                                        my_team_data = [t for t in teams if t["team"]["displayName"] == target_team][0]
                                        opp_team_data = [t for t in teams if t["team"]["displayName"] != target_team][0]
                                        
                                        my_s, opp_s = int(my_team_data["score"]), int(opp_team_data["score"])
                                        opp_n = tr(opp_team_data["team"]["shortDisplayName"])
                                        res = "✅ ניצחון" if my_s > opp_s else "❌ הפסד"
                                        
                                        msg += f"{RTL_MARK}🏀 **{info[0]}** ({info[1]})\n{RTL_MARK}{res} {my_s} - {opp_s} על {opp_n}\n{RTL_MARK}📊 סטטיסטיקה: {pts} נק', {reb} ריב', {ast} אס', {stl} חט'\n{RTL_MARK}⏱️ דקות: {mins}\n\n"
                                        found_any = True
                        except: pass
            if found_any: send_telegram(msg)
        except: pass

# ==========================================
# --- לו''ז יומי ---
# ==========================================

def get_combined_schedule():
    all_games = {"NBA": [], "GLEAGUE": [], "NCAA": []}
    players_handled = set()
    global status_cache
    status_cache = {}

    scan_configs = [
        (GLEAGUE_SCOREBOARD, "GLEAGUE", GLEAGUE_DATABASE),
        (NBA_SCOREBOARD, "NBA", NBA_DATABASE),
        (NCAA_SCOREBOARD, "NCAA", NCAA_DATABASE)
    ]

    for url, key, db in scan_configs:
        try:
            resp = requests.get(url, timeout=10).json()
            for ev in resp.get("events", []):
                teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
                for p_en, info in db.items():
                    if p_en in players_handled: continue
                    target_team = info[2]
                    
                    if target_team in teams:
                        # טיפול מיוחד בבן שרף ב-NBA
                        if p_en == "Ben Saraf" and key == "NBA":
                            update_msg = f"\n\n⬇️ **עדכון: {info[0]}** לא משחק (ירד להתאמן בג'י ליג)"
                            for i, (g_time, g_str) in enumerate(all_games["NBA"]):
                                if "ברוקלין" in g_str:
                                    all_games["NBA"][i] = (g_time, g_str + update_msg)
                            continue

                        vs = [t for t in teams if t != target_team][0]
                        inj = get_detailed_injury(ev, p_en)
                        status_note = " ⚠️ (בסימן שאלה)" if "QUESTIONABLE" in inj["status"] or "GTD" in inj["status"] else ""
                        if status_note: status_cache[f"{p_en}_{ev['id']}"] = "QUESTIONABLE"
                        
                        time_il = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
                        
                        prefix = ""
                        if key == "GLEAGUE": prefix = " ⬇️ (סגל הג'י ליג)"
                        
                        game_str = f"{RTL_MARK}🏀 *{info[0]}*{status_note}{prefix} ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"
                        all_games[key].append((time_il, game_str))
                        players_handled.add(p_en)
        except: pass

    full_msg = ""
    titles = {"NBA": "NBA", "GLEAGUE": "ליגת הפיתוח", "NCAA": "מכללות"}
    for k in ["NBA", "GLEAGUE", "NCAA"]:
        if all_games[k]:
            full_msg += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה ב{titles[k]}** 🇮🇱\n\n"
            full_msg += "\n\n".join([g[1] for g in sorted(all_games[k], key=lambda x: x[0])])
            full_msg += "\n\n\n"
    
    send_telegram(full_msg.strip() if full_msg else f"{RTL_MARK}🇮🇱 אין משחקי לגיונרים הלילה 😴")

# ==========================================
# --- עדכוני פציעות בזמן אמת ---
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
                        if info[2] in teams:
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
        
        # סיכום אתמול ב-15:32 כפי שביקשת
        if now.hour == 15 and now.minute == 32 and last_sum != today:
            get_morning_summary()
            last_sum = today
            
        # לו"ז הלילה ב-15:33 כפי שביקשת
        if now.hour == 15 and now.minute == 33 and last_sch != today:
            get_combined_schedule()
            last_sch = today
            
        # בדיקת פציעות רציפה
        if now.hour >= 18 or now.hour <= 9:
            check_final_updates()
            
        time.sleep(30)

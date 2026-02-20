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
# --- בסיסי נתונים מלאים ---
# ==========================================
NBA_DATABASE = {
    "Deni Avdija": ["דני אבדיה", "פורטלנד", "Trail Blazers"],
    "Danny Wolf": ["דני וולף", "מישיגן", "Michigan"],
    "Ben Saraf": ["בן שרף", "ברוקלין", "Nets"]
}

GLEAGUE_DATABASE = {
    "Ben Saraf": ["בן שרף", "לונג איילנד", "Long Island Nets"]
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
# --- פונקציות עזר ותרגום ---
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
    if not text or not text.strip(): return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

# ==========================================
# --- 1. סיכום מאוחד מושלם (15:32) ---
# ==========================================

def get_morning_summary():
    report = f"{RTL_MARK}🇮🇱 **סיכום לגיונרים הלילה ב-NBA** 🇮🇱\n\n"
    found_any = False
    
    # סריקה של כל הליגות לתוך הודעה אחת
    configs = [
        (NBA_SCOREBOARD, "NBA", NBA_DATABASE, "nba"),
        (GLEAGUE_SCOREBOARD, "ליגת הפיתוח", GLEAGUE_DATABASE, "nba-ght"),
        (NCAA_SCOREBOARD, "מכללות", NCAA_DATABASE, "mens-college-basketball")
    ]

    for url, title, db, sport_path in configs:
        league_header_added = False
        try:
            resp = requests.get(url, timeout=10).json()
            for ev in resp.get("events", []):
                if ev["status"]["type"]["state"] != "post": continue
                
                teams = ev["competitions"][0]["competitors"]
                team_names = [t["team"]["displayName"] for t in teams]

                for p_en, info in db.items():
                    if any(info[2] in name for name in team_names):
                        if not league_header_added and title != "NBA":
                            report += f"\n{RTL_MARK}🇮🇱 **סיכום לגיונרים - {title}** 🇮🇱\n\n"
                            league_header_added = True
                        
                        try:
                            bs_url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/{sport_path}/summary?event={ev['id']}"
                            bs_data = requests.get(bs_url, timeout=10).json()
                            p_played = False

                            for t_stats in bs_data.get("players", []):
                                for p_stats in t_stats.get("athletes", []):
                                    if p_en.lower() in p_stats["athlete"]["displayName"].lower():
                                        p_played = True
                                        s = p_stats["stats"]
                                        pts, reb, ast = (s[14], s[13], s[15]) if len(s) > 15 else (s[0], s[1], s[2])
                                        mins = p_stats.get("minutes", "0")
                                        
                                        my_t = [t for t in teams if info[2] in t["team"]["displayName"]][0]
                                        opp_t = [t for t in teams if t["id"] != my_t["id"]][0]
                                        res = "✅ ניצחון" if int(my_t["score"]) > int(opp_t["score"]) else "❌ הפסד"
                                        
                                        report += f"{RTL_MARK}🏀 **{info[0]}** ({info[1]})\n{RTL_MARK}{res} {my_t['score']} - {opp_t['score']} על {tr(opp_t['team']['shortDisplayName'])}\n{RTL_MARK}📊 {pts} נק', {reb} ריב', {ast} אס' | ⏱️ {mins} דק'\n\n"
                                        found_any = True

                            if not p_played and p_en == "Ben Saraf" and title == "NBA":
                                report += f"{RTL_MARK}🏀 **בן שרף**\n{RTL_MARK}⬇️ לא שיחק ב-NBA הלילה (ירד לסגל הג'י ליג)\n\n"
                                found_any = True
                        except: pass
        except: pass

    if found_any:
        send_telegram(report)

# ==========================================
# --- 2. לו''ז לגיונרים מאוחד (15:33) ---
# ==========================================

def get_combined_schedule():
    all_games = {"NBA": [], "GLEAGUE": [], "NCAA": []}
    players_handled = set()
    global status_cache
    status_cache = {}

    configs = [
        (GLEAGUE_SCOREBOARD, "GLEAGUE", GLEAGUE_DATABASE),
        (NBA_SCOREBOARD, "NBA", NBA_DATABASE),
        (NCAA_SCOREBOARD, "NCAA", NCAA_DATABASE)
    ]

    for url, key, db in configs:
        try:
            resp = requests.get(url, timeout=10).json()
            for ev in resp.get("events", []):
                if ev["status"]["type"]["state"] == "post": continue
                teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
                for p_en, info in db.items():
                    if p_en in players_handled: continue
                    if info[2] in str(teams):
                        # טיפול מיוחד בבן שרף בלו"ז
                        if p_en == "Ben Saraf" and key == "NBA":
                            # בדיקה אם הוא כבר מופיע בג'י ליג הלילה
                            continue 
                            
                        vs = [t for t in teams if info[2] not in t][0]
                        inj = get_detailed_injury(ev, p_en)
                        status_note = " ⚠️ (בסימן שאלה)" if "QUESTIONABLE" in inj["status"] or "GTD" in inj["status"] else ""
                        if status_note: status_cache[f"{p_en}_{ev['id']}"] = "QUESTIONABLE"
                        
                        time_il = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
                        
                        prefix = " ⬇️ (ירד לסגל הג'י ליג)" if key == "GLEAGUE" else ""
                        game_str = f"{RTL_MARK}🏀 **{info[0]}**{status_note}{prefix} ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: **{time_il.strftime('%H:%M')}**"
                        all_games[key].append((time_il, game_str))
                        players_handled.add(p_en)
        except: pass

    full_msg = f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה** 🇮🇱\n\n"
    found = False
    for k in ["NBA", "GLEAGUE", "NCAA"]:
        if all_games[k]:
            full_msg += "\n".join([g[1] for g in sorted(all_games[k], key=lambda x: x[0])]) + "\n\n"
            found = True
            
    if found:
        send_telegram(full_msg.strip())

# ==========================================
# --- 3. לוח NBA כללי מעוצב (15:40) ---
# ==========================================

def get_all_nba_games():
    try:
        resp = requests.get(NBA_SCOREBOARD, timeout=10).json()
        games = []
        for ev in resp.get("events", []):
            tm = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
            teams = ev["competitions"][0]["competitors"]
            t1 = teams[0]["team"]["displayName"]
            t2 = teams[1]["team"]["displayName"]
            
            isr = ["Nets", "Trail Blazers", "Michigan"]
            t1_s = f"{tr(t1)} 🇮🇱" if any(x in t1 for x in isr) else tr(t1)
            t2_s = f"{tr(t2)} 🇮🇱" if any(x in t2 for x in isr) else tr(t2)
            
            games.append((tm, f"{RTL_MARK}‏⏰ **{tm.strftime('%H:%M')}**\n{RTL_MARK}‏🏀 {t2_s} 🆚 {t1_s}"))
        
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

# ==========================================
# --- לולאת הרצה ראשית ---
# ==========================================

if __name__ == "__main__":
    last_sum, last_sch, last_all = "", "", ""
    print("הבוט פועל...")
    
    while True:
        now = datetime.now(pytz.timezone('Asia/Jerusalem'))
        today = now.strftime("%Y-%m-%d")
        
        # 1. סיכום לגיונרים מאוחד
        if now.hour == 15 and now.minute == 50 and last_sum != today:
            get_morning_summary()
            last_sum = today
            
        # 2. לו"ז לגיונרים להלילה
        if now.hour == 15 and now.minute == 50 and last_sch != today:
            get_combined_schedule()
            last_sch = today
            
        # 3. לוח NBA כללי
        if now.hour == 15 and now.minute == 50 and last_all != today:
            get_all_nba_games()
            last_all = today
            
        # 4. בדיקת פציעות (רצה לאורך הלילה)
        if now.hour >= 18 or now.hour <= 9:
            check_final_updates()
            
        time.sleep(30)

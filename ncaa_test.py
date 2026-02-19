import requests
import time
from datetime import datetime
import pytz
from deep_translator import GoogleTranslator

# ==========================================
# --- הגדרות טכניות ומפתחות גישה ---
# ==========================================
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# APIs של ESPN
NCAA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
NBA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

translator = GoogleTranslator(source='en', target='iw')
RTL_MARK = "\u200f" # תו ליישור טקסט לימין (RTL)

# ==========================================
# --- בסיסי נתונים - רשימת הלגיונרים ---
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
# --- פונקציות עזר ---
# ==========================================

def tr(text):
    """תרגום שמות קבוצות לעברית תקינה"""
    try:
        t = translator.translate(text)
        return t.replace("שבילים בלייזרים", "פורטלנד").replace("רשתות", "ברוקלין").replace("לוחמים", "ווריורס")
    except: return text

def send_telegram(text):
    """שליחת ההודעה לטלגרם"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

# ==========================================
# --- לוגיקת סיכום בוקר (09:15) ---
# ==========================================

def get_morning_summary():
    """סורק תוצאות ושולח סיכום סטטיסטיקה מפורט"""
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
                        # בדיקה אם השחקן שייך לקבוצה (תומך גם ברשימת כינויים)
                        is_match = False
                        if isinstance(info[2], list):
                            if any(k in team["team"]["displayName"] for k in info[2:]): is_match = True
                        elif info[2] in team["team"]["displayName"]: is_match = True
                        
                        if is_match:
                            try:
                                # משיכת נתוני Boxscore מפורטים
                                bs_url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/{'nba' if 'nba' in url else 'mens-college-basketball'}/summary?event={ev['id']}"
                                bs_data = requests.get(bs_url, timeout=10).json()
                                
                                for t_stats in bs_data.get("players", []):
                                    for p_stats in t_stats.get("athletes", []):
                                        if p_en in p_stats["athlete"]["displayName"]:
                                            s = p_stats["stats"]
                                            pts, reb, ast, stl = s[0], s[1], s[2], s[3]
                                            mins = p_stats.get("minutes", "0")
                                            
                                            my_score = int(team["score"])
                                            opp_score = int([t["score"] for t in teams if t["id"] != team["id"]][0])
                                            opp_name = tr([t["team"]["shortDisplayName"] for t in teams if t["id"] != team["id"]][0])
                                            
                                            res_icon = "✅ ניצחון" if my_score > opp_score else "❌ הפסד"
                                            
                                            msg += f"{RTL_MARK}🏀 **{info[0]}** ({info[1]})\n"
                                            msg += f"{RTL_MARK}{res_icon} {my_score} - {opp_score} על {opp_name}\n"
                                            msg += f"{RTL_MARK}📊 סטטיסטיקה: {pts} נק', {reb} ריב', {ast} אס', {stl} חט'\n"
                                            msg += f"{RTL_MARK}⏱️ דקות: {mins}\n\n"
                                            found_any = True
                            except: pass
            if found_any: 
                send_telegram(msg)
                time.sleep(2) # מניעת עומס על ה-API של טלגרם
        except: pass

# ==========================================
# --- לוגיקת לו''ז יומי (15:00) ---
# ==========================================

def get_combined_schedule():
    """בונה לו''ז יומי עם פתרון חסימת כפילויות לבן שרף"""
    all_games = {"NBA": [], "GLEAGUE": [], "NCAA": []}
    blocked_players = set() # שחקנים שכבר אותרו בגי-ליג ולא יופיעו ב-NBA

    # 1. סריקת ליגת הפיתוח (עדיפות ראשונה לחסימת כפילויות)
    try:
        resp_ncaa = requests.get(NCAA_SCOREBOARD, timeout=10).json()
        for ev in resp_ncaa.get("events", []):
            teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
            for p_en, info in GLEAGUE_DATABASE.items():
                if any(k in t_name for k in info[2:] for t_name in teams):
                    vs = [t for t in teams if not any(k in t for k in info[2:])][0]
                    time_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    time_il = time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    
                    all_games["GLEAGUE"].append((time_il, f"{RTL_MARK}🏀 *{info[0]}* ⬇️ (ירד לסגל ליגת הפיתוח) ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"))
                    blocked_players.add(p_en) # השחקן נמצא בגי-ליג, נחסום אותו מה-NBA
    except: pass

    # 2. סריקת NBA (עם בדיקת חסימת בן שרף)
    try:
        resp_nba = requests.get(NBA_SCOREBOARD, timeout=10).json()
        for ev in resp_nba.get("events", []):
            teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
            for p_en, info in NBA_DATABASE.items():
                if p_en in blocked_players: continue # הפתרון: אם הוא בגיליג, הוא לא ייכנס ל-NBA
                
                if info[2] in str(teams):
                    vs = [t for t in teams if info[2] not in t][0]
                    time_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    time_il = time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    all_games["NBA"].append((time_il, f"{RTL_MARK}🏀 *{info[0]}* ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"))
    except: pass

    # 3. סריקת מכללות
    try:
        for ev in resp_ncaa.get("events", []):
            teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
            for p_en, info in NCAA_DATABASE.items():
                if p_en in blocked_players: continue
                if info[2] in str(teams):
                    vs = [t for t in teams if info[2] not in t][0]
                    time_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    time_il = time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    all_games["NCAA"].append((time_il, f"{RTL_MARK}🏀 *{info[0]}* ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"))
    except: pass

    # בניית ההודעה הסופית
    full_msg = ""
    titles = {"NBA": "NBA", "GLEAGUE": "ליגת הפיתוח", "NCAA": "המכללות"}
    for league_key, league_name in titles.items():
        if all_games[league_key]:
            full_msg += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה ב-{league_name}** 🇮🇱\n\n"
            full_msg += "\n\n".join([g[1] for g in sorted(all_games[league_key])])
            full_msg += "\n\n---\n\n"
    
    send_telegram(full_msg if full_msg else f"{RTL_MARK}🇮🇱 אין משחקי לגיונרים הלילה 😴")

# ==========================================
# --- לולאה ראשית להרצה ---
# ==========================================

if __name__ == "__main__":
    print("🚀 הבוט המאוחד פועל במתכונת מלאה...")
    last_day_sch = ""
    last_day_sum = ""
    
    while True:
        try:
            now = datetime.now(pytz.timezone('Asia/Jerusalem'))
            today_str = now.strftime("%Y-%m-%d")
            
            # שליחת לו''ז יומי ב-15:00
            if now.hour == 15 and now.minute == 9 and last_day_sch != today_str:
                get_combined_schedule()
                last_day_sch = today_str
                
            # שליחת סיכום בוקר ב-09:15
            if now.hour == 9 and now.minute == 15 and last_day_sum != today_str:
                get_morning_summary()
                last_day_sum = today_str
                
        except Exception as e:
            print(f"⚠️ שגיאה: {e}")
            
        time.sleep(60) # בדיקה פעם בדקה

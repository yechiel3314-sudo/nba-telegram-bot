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
NBA_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event="

translator = GoogleTranslator(source='en', target='iw')
RTL_MARK = "\u200f" 
last_live_status = {} # מונע כפילויות בעדכונים חיים

# --- מילון הישראלים המעודכן ---
ISRAELI_DATABASE = {
    "Deni Avdija": ["דני אבדיה", "פורטלנד"],
    "Danny Wolf": ["דני וולף", "ברוקלין"],
    "Ben Saraf": ["בן שרף", "ברוקלין/G-League"],
    "Emanuel Sharp": ["עמנואל שארפ", "יוסטון"],
    "Yoav Berman": ["יואב ברמן", "קווינס"],
    "Ofri Naveh": ["עופרי נווה", "אורל רוברטס"],
    "Omer Mayer": ["עומר מאייר", "פורדו"],
    "Daniel Gueta": ["דניאל גואטה", "אוקלהומה סטייט"]
}

# מיפוי קבוצות (NBA + NCAA)
TEAM_TO_PLAYER = {
    "Trail Blazers": "Deni Avdija", "Nets": "Danny Wolf", "Blue Coats": "Ben Saraf", 
    "Squadron": "Ben Saraf", "Long Island Nets": "Ben Saraf",
    "Houston": "Emanuel Sharp", "Queens": "Yoav Berman", "Oral Roberts": "Ofri Naveh",
    "Oklahoma State": "Daniel Gueta", "Purdue": "Omer Mayer"
}

def tr(text):
    try:
        translated = translator.translate(text)
        return translated.replace("שבילים בלייזרים", "פורטלנד").replace("רשתות", "ברוקלין")
    except: return text

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

# --- מנגנון מעקב חי על בן שרף (כל רבע וסיום) ---
def track_ben_saraf_live():
    global last_live_status
    try:
        resp = requests.get(NBA_SCOREBOARD, timeout=10).json()
        for ev in resp.get("events", []):
            gid = ev["id"]
            summary = requests.get(NBA_SUMMARY + gid, timeout=10).json()
            for team_box in summary.get("boxscore", {}).get("players", []):
                stats_data = team_box.get("statistics", [{}])[0]
                labels, athletes = stats_data.get("labels", []), stats_data.get("athletes", [])
                for a in athletes:
                    if a["athlete"]["displayName"] == "Ben Saraf":
                        s = a["stats"]
                        def g(lb):
                            try: return s[labels.index(lb)]
                            except: return "0"
                        
                        status_detail = ev["status"]["type"]["detail"]
                        # שליחה רק אם הסטטוס השתנה (סוף רבע או סיום משחק)
                        if gid not in last_live_status or last_live_status[gid] != status_detail:
                            if "End of" in status_detail or "Final" in status_detail:
                                last_live_status[gid] = status_detail
                                home = ev["competitions"][0]["competitors"][0]
                                away = ev["competitions"][0]["competitors"][1]
                                
                                title = "🏁 סיום משחק" if "Final" in status_detail else f"🏀 עדכון {tr(status_detail)}"
                                msg = f"{RTL_MARK}🇮🇱 **{title}: בן שרף** 🇮🇱\n"
                                msg += f"{RTL_MARK}🏟️ נגד: {tr(away['team']['displayName']) if 'Nets' in home['team']['displayName'] else tr(home['team']['displayName'])}\n"
                                msg += f"{RTL_MARK}🔢 תוצאה: {home['score']} - {away['score']}\n\n"
                                msg += f"{RTL_MARK}⏱️ דקות: **{g('MIN')}**\n"
                                msg += f"{RTL_MARK}🏀 נקודות: **{g('PTS')}**\n"
                                msg += f"{RTL_MARK}👐 ריבאונדים: {g('REB')}\n"
                                msg += f"{RTL_MARK}🪄 אסיסטים: {g('AST')}\n"
                                msg += f"{RTL_MARK}🛡️ חטיפות: {g('STL')}\n"
                                msg += f"{RTL_MARK}🚫 חסימות: {g('BLK')}\n"
                                msg += f"{RTL_MARK}⚠️ איבודים: {g('TO')}\n"
                                msg += f"{RTL_MARK}📈 פלוס/מינוס: **{g('+/-')}**"
                                
                                if "Final" in status_detail:
                                    win = "✅ ניצחון!" if (home['winner'] and 'Nets' in home['team']['displayName']) else "❌ הפסד"
                                    msg += f"\n\n{RTL_MARK}🏁 **{win}**"
                                
                                send_telegram(msg)
    except: pass

# --- פונקציית לו"ז משולבת (12:50) ---
def get_combined_schedule():
    try:
        # סריקת NBA
        nba_resp = requests.get(NBA_SCOREBOARD, timeout=10).json()
        nba_games = []
        for ev in nba_resp.get("events", []):
            teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
            for t_eng, p_eng in TEAM_TO_PLAYER.items():
                if any(t_eng in name for name in teams):
                    p_info = ISRAELI_DATABASE[p_eng]
                    vs = [t for t in teams if t_eng not in t][0]
                    t_il = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
                    nba_games.append(f"{RTL_MARK}🏀 *{p_info[0]}* ({p_info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{t_il.strftime('%H:%M')}*")

        # סריקת מכללות
        ncaa_resp = requests.get(NCAA_SCOREBOARD, timeout=10).json()
        ncaa_games = []
        for ev in ncaa_resp.get("events", []):
            teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
            for t_eng, p_eng in TEAM_TO_PLAYER.items():
                if any(t_eng in name for name in teams):
                    p_info = ISRAELI_DATABASE[p_eng]
                    vs = [t for t in teams if t_eng not in t][0]
                    t_il = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
                    ncaa_games.append(f"{RTL_MARK}🏀 *{p_info[0]}* ({p_info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{t_il.strftime('%H:%M')}*")

        full_msg = ""
        if nba_games:
            full_msg += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה ב-NBA** 🇮🇱\n\n" + "\n\n".join(list(set(nba_games))) + "\n\n"
        if ncaa_games:
            full_msg += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה במכללות** 🇮🇱\n\n" + "\n\n".join(list(set(ncaa_games)))
        
        if full_msg: send_telegram(full_msg)
    except Exception as e: print(f"Schedule Error: {e}")

if __name__ == "__main__":
    print("🚀 הבוט פעיל. לו\"ז ב-12:50, מעקב חי אחרי בן שרף רץ ברקע...")
    last_day_e = ""
    while True:
        try:
            now = datetime.now(pytz.timezone('Asia/Jerusalem'))
            today = now.strftime("%Y-%m-%d")

            # בדיקה חיה של בן שרף בכל דקה
            track_ben_saraf_live()

            # שליחת לו"ז יומי ב-12:50
            if now.hour == 12 and now.minute == 50 and last_day_e != today:
                get_combined_schedule()
                last_day_e = today

        except Exception as e: print(f"Loop error: {e}")
        time.sleep(30)

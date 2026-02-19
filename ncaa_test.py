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
last_live_status = {}
RTL_MARK = "\u200f" # תו מיוחד ליישור מימין לשמאל

# --- מילון הישראלים ---
ISRAELI_DATABASE = {
    "Ben Saraf": ["בן שרף", "NBA/G-League"],
    "Emanuel Sharp": ["עמנואל שארפ", "יוסטון"],
    "Yoav Berman": ["יואב ברמן", "קווינס"],
    "Ofri Naveh": ["עופרי נווה", "אורל רוברטס"],
    "Eitan Burg": ["איתן בורג", "טנסי"],
    "Omer Mayer": ["עומר מאייר", "פורדו"],
    "Noam Dovrat": ["נועם דוברת", "מיאמי"],
    "Or Ashkenazi": ["אור אשכנזי", "ליפסקומב"],
    "Alon Michaeli": ["אלון מיכאלי", "קולורדו"],
    "Younatan Levi": ["יונתן לוי", "פפרדיין"],
    "Yuval Levin": ["יובל לוין", "פרדו פורט וויין"],
    "Omer Hamama": ["עומר חממה", "קנט סטייט"],
    "Or Paran": ["אור פארן", "מרסיהרסט"],
    "Daniel Gueta": ["דניאל גואטה", "אוקלהומה סטייט"]
}

TEAM_TO_PLAYER = {
    "Houston": "Emanuel Sharp", "Queens": "Yoav Berman", "Oral Roberts": "Ofri Naveh",
    "Tennessee": "Eitan Burg", "Purdue": "Omer Mayer", "Miami": "Noam Dovrat",
    "Lipscomb": "Or Ashkenazi", "Colorado": "Alon Michaeli", "Pepperdine": "Younatan Levi",
    "Purdue Fort Wayne": "Yuval Levin", "Kent State": "Omer Hamama", "Mercyhurst": "Or Paran",
    "Oklahoma State": "Daniel Gueta", "G League": "Ben Saraf"
}

def tr(text):
    try: return translator.translate(text)
    except: return text

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

# --- פונקציית לו"ז (מתוזמן ל-12:32) ---
def get_evening_schedule():
    try:
        resp = requests.get(NCAA_SCOREBOARD, timeout=15).json()
        games_tonight = []
        for ev in resp.get("events", []):
            comp = ev["competitions"][0]
            teams_in_game = [t["team"]["displayName"] for t in comp["competitors"]]
            for team_eng, player_eng in TEAM_TO_PLAYER.items():
                if any(team_eng in t_name for t_name in teams_in_game):
                    player_info = ISRAELI_DATABASE[player_eng]
                    vs_team = [t for t in teams_in_game if team_eng not in t][0]
                    game_time_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    game_time_il = game_time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    
                    if game_time_il.hour >= 21 or game_time_il.hour <= 11:
                        # הוספת RTL_MARK ליישור
                        line = f"{RTL_MARK}🏀 *{player_info[0]}* ({player_info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs_team)}*\n{RTL_MARK}⏰ שעה: *{game_time_il.strftime('%H:%M')}*"
                        games_tonight.append(line)
        if games_tonight:
            msg = f"{RTL_MARK}🇮🇱 **לו\"ז הישראלים הלילה:**\n\n" + "\n\n".join(list(set(games_tonight)))
            send_telegram(msg)
    except Exception as e: print(f"Schedule Error: {e}")

# --- מעקב חי בן שרף ---
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
                        if gid not in last_live_status or last_live_status[gid] != status_detail:
                            last_live_status[gid] = status_detail
                            home = ev["competitions"][0]["competitors"][0]
                            away = ev["competitions"][0]["competitors"][1]
                            
                            msg = f"{RTL_MARK}🏀 **עדכון משחק: בן שרף** 🏀\n"
                            msg += f"{RTL_MARK}🏟️ נגד: {tr(away['team']['displayName']) if home['team']['displayName']=='G League' else tr(home['team']['displayName'])}\n"
                            msg += f"{RTL_MARK}⏱️ מצב: {tr(status_detail)}\n"
                            msg += f"{RTL_MARK}🔢 תוצאה: {home['score']} - {away['score']}\n\n"
                            msg += f"{RTL_MARK}⏱️ דקות: {g('MIN')}\n"
                            msg += f"{RTL_MARK}🏀 נקודות: *{g('PTS')}*\n"
                            msg += f"{RTL_MARK}👐 ריבאונדים: {g('REB')}\n"
                            msg += f"{RTL_MARK}🪄 אסיסטים: {g('AST')}\n"
                            msg += f"{RTL_MARK}🛡️ חטיפות: {g('STL')}\n"
                            msg += f"{RTL_MARK}🚫 חסימות: {g('BLK')}\n"
                            msg += f"{RTL_MARK}⚠️ איבודים: {g('TO')}\n"
                            msg += f"{RTL_MARK}📈 פלוס/מינוס: *{g('+/-')}*"
                            
                            if ev["status"]["type"]["state"] == "post":
                                win = "✅ ניצחון!" if (home['winner'] and home['team']['displayName']=='G League') else "❌ הפסד"
                                msg += f"\n\n{RTL_MARK}🏁 **סיום משחק: {win}**"
                            
                            send_telegram(msg)
    except: pass

if __name__ == "__main__":
    print("🚀 הבוט פעיל. מחכה ל-12:32...")
    last_day_e = ""
    while True:
        try:
            now = datetime.now(pytz.timezone('Asia/Jerusalem'))
            today = now.strftime("%Y-%m-%d")

            track_ben_saraf_live()

            if now.hour == 12 and now.minute == 32 and last_day_e != today:
                get_evening_schedule()
                last_day_e = today

        except Exception as e: print(f"Loop error: {e}")
        time.sleep(10) # בדיקה מהירה יותר בשביל הניסוי

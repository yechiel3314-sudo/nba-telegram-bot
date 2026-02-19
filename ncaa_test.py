import requests
import time
from datetime import datetime
import pytz
from deep_translator import GoogleTranslator

# --- הגדרות טכניות ---
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event="

translator = GoogleTranslator(source='en', target='iw')

# --- מילון הישראלים המלא (שם ב-ESPN : [שם בעברית, קבוצה בעברית]) ---
ISRAELI_DATABASE = {
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

# מיפוי קבוצות באנגלית לחיפוש בלו"ז (כדי שהבוט ידע איזו קבוצה לחפש ב-API)
TEAM_TO_PLAYER = {
    "Houston": "Emanuel Sharp",
    "Queens University": "Yoav Berman",
    "Oral Roberts": "Ofri Naveh",
    "Tennessee": "Eitan Burg",
    "Purdue": "Omer Mayer",
    "Miami": "Noam Dovrat",
    "Lipscomb": "Or Ashkenazi",
    "Colorado": "Alon Michaeli",
    "Pepperdine": "Younatan Levi",
    "Purdue Fort Wayne": "Yuval Levin",
    "Kent State": "Omer Hamama",
    "Mercyhurst": "Or Paran",
    "Oklahoma State": "Daniel Gueta"
}

def tr(text):
    try: return translator.translate(text)
    except: return text

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except:
        pass

# --- פונקציית לו"ז (19:00) ---
def get_evening_schedule():
    try:
        resp = requests.get(SCOREBOARD_URL, timeout=15).json()
        games_tonight = []
        
        for ev in resp.get("events", []):
            comp = ev["competitions"][0]
            # שמות הקבוצות במשחק הנוכחי
            teams_in_game = [t["team"]["displayName"] for t in comp["competitors"]]
            
            for team_eng, player_eng in TEAM_TO_PLAYER.items():
                # בדיקה אם אחת הקבוצות שלנו משחקת
                if any(team_eng in t_name for t_name in teams_in_game):
                    player_info = ISRAELI_DATABASE[player_eng]
                    vs_team = [t for t in teams_in_game if team_eng not in t][0]
                    
                    # המרת זמן לישראל
                    game_time_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    game_time_il = game_time_utc.astimezone(pytz.timezone('Asia/Jerusalem')).strftime('%H:%M')
                    
                    line = f"🇮🇱 *{player_info[0]}* ({player_info[1]})\n🆚 נגד: *{tr(vs_team)}*\n⏰ שעה: *{game_time_il}*"
                    if line not in games_tonight:
                        games_tonight.append(line)

        if games_tonight:
            msg = "📅 *לו\"ז הישראלים הלילה במכללות:*\n\n" + "\n\n".join(games_tonight)
            send_telegram(msg)
        else:
            send_telegram("📅 הלילה אין משחקים לישראלים ברשימה.")
    except Exception as e:
        print(f"Evening Error: {e}")

# --- פונקציית סיכום בוקר (08:00) ---
def get_morning_summary():
    try:
        resp = requests.get(SCOREBOARD_URL, timeout=15).json()
        reports = []
        
        for ev in resp.get("events", []):
            if ev["status"]["type"]["state"] == "post": # משחק הסתיים
                gid = ev["id"]
                summary = requests.get(SUMMARY_URL + gid, timeout=15).json()
                
                for team_box in summary.get("boxscore", {}).get("players", []):
                    stats_data = team_box.get("statistics", [{}])[0]
                    labels = stats_data.get("labels", [])
                    athletes = stats_data.get("athletes", [])
                    
                    for a in athletes:
                        p_name_eng = a["athlete"]["displayName"]
                        if p_name_eng in ISRAELI_DATABASE:
                            s = a["stats"]
                            res = ISRAELI_DATABASE[p_name_eng]
                            
                            def s_val(lb):
                                try: return s[labels.index(lb)]
                                except: return "0"
                            
                            report = f"🇮🇱 *{res[0]}* ({res[1]})\n"
                            report += f"📊 *{s_val('PTS')}* נק', *{s_val('REB')}* ריב', *{s_val('AST')}* אס'\n"
                            report += f"🛡️ {s_val('STL')} חט', {s_val('BLK')} חס'\n"
                            report += f"⏱️ דקות: {s_val('MIN')} | מדד +/-: {s_val('+/-')}"
                            reports.append(report)

        if reports:
            msg = "☀️ *סיכום הופעות הישראלים מהלילה:*\n\n" + "\n\n".join(reports)
            send_telegram(msg)
        else:
            send_telegram("☀️ לא נמצאו דקות משחק לישראלים הלילה.")
    except Exception as e:
        print(f"Morning Error: {e}")

# --- לופ זמן ישראל ---
if __name__ == "__main__":
    print("🚀 בוט סקאוט ישראלים NCAA באוויר...")
    last_day = ""
    morning_done = False
    evening_done = False

    while True:
        try:
            now = datetime.now(pytz.timezone('Asia/Jerusalem'))
            today = now.strftime("%Y-%m-%d")

            if today != last_day:
                last_day = today
                morning_done = False
                evening_done = False

            # בוקר 08:00
            if now.hour == 8 and not morning_done:
                get_morning_summary()
                morning_done = True
            
            # ערב 19:00
            if now.hour == 19 and not evening_done:
                get_evening_schedule()
                evening_done = True

        except Exception as e:
            print(f"Loop Error: {e}")
            
        time.sleep(60)

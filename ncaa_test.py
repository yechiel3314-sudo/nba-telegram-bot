import requests
import time
from datetime import datetime
import pytz
from deep_translator import GoogleTranslator

# --- הגדרות טכניות ---
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
# כתובות ה-API (NCAA ו-G-League משתמשות באותו מבנה ב-ESPN)
SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event="

translator = GoogleTranslator(source='en', target='iw')

# --- מילון הישראלים המעודכן ---
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
    "Daniel Gueta": ["דניאל גואטה", "אוקלהומה סטייט"],
    "Ben Saraf": ["בן שרף", "ליגת הפיתוח"]
}

# מיפוי קבוצות (כולל אופציה לליגת הפיתוח עבור בן שרף)
TEAM_TO_PLAYER = {
    "Houston": "Emanuel Sharp", "Queens": "Yoav Berman", "Oral Roberts": "Ofri Naveh",
    "Tennessee": "Eitan Burg", "Purdue": "Omer Mayer", "Miami": "Noam Dovrat",
    "Lipscomb": "Or Ashkenazi", "Colorado": "Alon Michaeli", "Pepperdine": "Younatan Levi",
    "Purdue Fort Wayne": "Yuval Levin", "Kent State": "Omer Hamama", "Mercyhurst": "Or Paran",
    "Oklahoma State": "Daniel Gueta", "G League": "Ben Saraf", "Blue Coats": "Ben Saraf", "Squadron": "Ben Saraf"
}

def tr(text):
    try: return translator.translate(text)
    except: return text

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

# --- לו"ז (מתוזמן ל-12:15) ---
def get_evening_schedule():
    try:
        resp = requests.get(SCOREBOARD_URL, timeout=15).json()
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
                    
                    time_str = game_time_il.strftime('%H:%M')
                    line = f"🏀 *{player_info[0]}* ({player_info[1]})\n🆚 נגד: *{tr(vs_team)}*\n⏰ שעה: *{time_str}*"
                    games_tonight.append(line)
        if games_tonight:
            msg = "🇮🇱 **לו\"ז הישראלים הלילה:**\n\n" + "\n\n".join(list(set(games_tonight)))
            send_telegram(msg)
    except Exception as e: print(f"Evening Error: {e}")

# --- סיכום סטטיסטי (מיושר לימין) ---
def get_morning_summary():
    try:
        resp = requests.get(SCOREBOARD_URL, timeout=15).json()
        reports = []
        for ev in resp.get("events", []):
            if ev["status"]["type"]["state"] == "post":
                summary = requests.get(SUMMARY_URL + ev["id"], timeout=15).json()
                for team_box in summary.get("boxscore", {}).get("players", []):
                    stats_data = team_box.get("statistics", [{}])[0]
                    labels, athletes = stats_data.get("labels", []), stats_data.get("athletes", [])
                    for a in athletes:
                        p_name = a["athlete"]["displayName"]
                        if p_name in ISRAELI_DATABASE:
                            s, res = a["stats"], ISRAELI_DATABASE[p_name]
                            def g(lb):
                                try: return s[labels.index(lb)]
                                except: return "0"
                            
                            if g('MIN') == "0" or g('MIN') == "":
                                reports.append(f"🇮🇱 *{res[0]}* ({res[1]})\n❌ לא שותף במשחק")
                            else:
                                # בניית הודעה מיושרת לימין עם אמוג'ים
                                report = f"🇮🇱 *{res[0]}* ({res[1]})\n"
                                report += f"⏱️ דקות: {g('MIN')}\n"
                                report += f"🏀 נקודות: *{g('PTS')}*\n"
                                report += f"👐 ריבאונדים: {g('REB')}\n"
                                report += f"🪄 אסיסטים: {g('AST')}\n"
                                report += f"🛡️ חטיפות: {g('STL')}\n"
                                report += f"🚫 חסימות: {g('BLK')}\n"
                                report += f"⚠️ איבודים: {g('TO')}\n"
                                report += f"📈 פלוס/מינוס: *{g('+/-')}*"
                                reports.append(report)
        if reports:
            msg = "🇮🇱 **סיכום הופעות הלילה:**\n\n" + "\n\n".join(reports)
            send_telegram(msg)
    except Exception as e: print(f"Morning Error: {e}")

if __name__ == "__main__":
    print("🚀 בוט סקאוט מעודכן (כולל בן שרף) באוויר...")
    last_day_m, last_day_e = "", ""
    while True:
        try:
            now = datetime.now(pytz.timezone('Asia/Jerusalem'))
            today = now.strftime("%Y-%m-%d")

            # סיכום בוקר ב-08:00
            if now.hour == 8 and now.minute == 0 and last_day_m != today:
                get_morning_summary()
                last_day_m = today

            # לו"ז ב-12:15
            if now.hour == 12 and now.minute == 15 and last_day_e != today:
                get_evening_schedule()
                last_day_e = today
                
        except Exception as e: print(f"Loop: {e}")
        time.sleep(30)

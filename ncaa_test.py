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

# --- מילון הישראלים המלא (זיהוי ותרגום) ---
# מפתח: שם ב-ESPN, ערך: [שם בעברית, שם המכללה בעברית]
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

def tr(text):
    try: return translator.translate(text)
    except: return text

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

# --- מנוע חיפוש וסיכום ---

def get_evening_schedule():
    """סורק משחקים עתידיים לישראלים"""
    try:
        resp = requests.get(SCOREBOARD_URL, timeout=15).json()
        games_tonight = []
        
        for ev in resp.get("events", []):
            comp = ev["competitions"][0]
            teams_in_game = [t["team"]["displayName"] for t in comp["competitors"]]
            
            for eng_name, info in ISRAELI_DATABASE.items():
                college_eng = info[1] # אנחנו נחפש לפי שם המכללה באנגלית ב-API אם צריך, אבל ESPN נותן שמות מלאים
                # בדיקה אם המכללה של הישראלי משתתפת במשחק
                for t in comp["competitors"]:
                    if eng_name in [a["athlete"]["displayName"] for a in t.get("roster", [])] or any(word in t["team"]["displayName"] for word in eng_name.split()[-1:]):
                        # לצורך הפשטות ב-NCAA, נבדוק אם שם המכללה מופיע בנבחרת
                        pass

            # דרך בטוחה יותר: בדיקת כל קבוצה מול רשימת המכללות שלנו
            for t in comp["competitors"]:
                team_name = t["team"]["displayName"]
                for eng_name, info in ISRAELI_DATABASE.items():
                    # אם שם המכללה (אינדקס 1 במילון) נמצא בשם הקבוצה של ESPN
                    if info[1] in tr(team_name): 
                        vs_team = [temp["team"]["displayName"] for temp in comp["competitors"] if temp["team"]["displayName"] != team_name][0]
                        
                        game_time_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                        game_time_il = game_time_utc.astimezone(pytz.timezone('Asia/Jerusalem')).strftime('%H:%M')
                        
                        games_tonight.append(f"🇮🇱 **{info[0]}** ({info[1]})\n🆚 נגד: **{tr(vs_team)}**\n⏰ שעה: **{game_time_il}**")
                        break

        if games_tonight:
            msg = "📅 **לו\"ז הישראלים הלילה במכללות:**\n\n" + "\n\n".join(list(set(games_tonight)))
            send_telegram(msg)
        else:
            send_telegram("📅 הלילה אין משחקים לישראלים ברשימה.")
    except Exception as e: print(f"Evening Error: {e}")

def get_morning_summary():
    """סורק סטטיסטיקות של משחקים שהסתיימו"""
    try:
        resp = requests.get(SCOREBOARD_URL, timeout=15).json()
        reports = []
        
        for ev in resp.get("events", []):
            if ev["status"]["type"]["state"] == "post":
                gid = ev["id"]
                summary = requests.get(SUMMARY_URL + gid, timeout=15).json()
                
                for team_box in summary.get("boxscore", {}).get("players", []):
                    # מחפשים את הישראלים בתוך ה-boxscore
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
                            
                            report = f"🇮🇱 **{res[0]}** ({res[1]})\n"
                            report += f"📊 **{s_val('PTS')}** נק', **{s_val('REB')}** ריב', **{s_val('AST')}** אס'\n"
                            report += f"🛡️ {s_val('STL')} חט', {s_val('BLK')} חס'\n"
                            report += f"⏱️ דקות: {s_val('MIN')} | מדד +/-: {s_val('+/-')}"
                            reports.append(report)

        if reports:
            msg = "☀️ **סיכום הופעות הישראלים מהלילה:**\n\n" + "\n\n".join(reports)
            send_telegram(msg)
        else:
            send_telegram("☀️ לא נמצאו דקות משחק לישראלים הלילה.")
    except Exception as e: print(f"Morning Error: {e}")

# --- לופ הפעלה לפי שעות ---

if __name__ == "__main__":
    print("🚀 בוט סקאוט ישראלים (NCAA) פעיל...")
    
    # משתנים למניעת כפילות שליחה
    last_morning_day = ""
    last_evening_day = ""

    while True:
        try:
            now = datetime.now(pytz.timezone('Asia/Jerusalem'))
            current_day = now.strftime("%Y-%m-%d")

            # בדיקת בוקר - 08:00
            if now.hour == 8 and last_morning_day != current_day:
                get_morning_summary()
                last_morning_day = current_day
            
            # בדיקת ערב - 19:00
            if now.hour == 19 and last_evening_day != current_day:
                get_evening_schedule()
                last_evening_day = current_day

        except Exception as e:
            print(f"Loop Error: {e}")
            
        time.sleep(60)

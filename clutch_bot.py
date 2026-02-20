import requests
import time
from datetime import datetime
import pytz
from deep_translator import GoogleTranslator

# --- הגדרות מערכת ---
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
NBA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

translator = GoogleTranslator(source='en', target='iw')
RTL_MARK = "\u200f" 
sent_clutch_alerts = set() 

def tr(text):
    try:
        t = translator.translate(text)
        return t.replace("שבילים בלייזרים", "פורטלנד").replace("רשתות", "ברוקלין").replace("לוחמים", "ווריורס").replace("בוכנות", "פיסטונס")
    except: return text

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def check_all_nba_clutch():
    global sent_clutch_alerts
    try:
        resp = requests.get(NBA_SCOREBOARD, timeout=5).json()
        for ev in resp.get("events", []):
            gid = ev["id"]
            status = ev["status"]["type"]
            
            # בדיקה אם המשחק פעיל
            if status["state"] == "in":
                clock = ev["status"]["displayClock"]
                period = ev["status"]["period"]
                
                # --- תנאי חדש: רק רבע 4 ופחות מ-4 דקות (ללא הארכות) ---
                if period != 4: continue
                
                try:
                    if ":" in clock:
                        minutes = int(clock.split(":")[0])
                        if minutes >= 4: continue
                except: continue

                competition = ev["competitions"][0]
                home = competition["competitors"][0]
                away = competition["competitors"][1]
                
                try:
                    h_score = int(home["score"])
                    a_score = int(away["score"])
                    diff = abs(h_score - a_score)
                except: continue

                # --- תנאי הפרש: 4 ומטה ---
                if diff <= 4:
                    if gid not in sent_clutch_alerts:
                        sent_clutch_alerts.add(gid)
                        
                        # שליפת קלעים מובילים
                        try:
                            # פונקציית עזר למציאת הקלעי המוביל מתוך רשימת הסטטיסטיקה של ESPN
                            def get_top_scorer(comp_idx):
                                leaders = competition["competitors"][comp_idx].get("leaders", [])
                                for leader in leaders:
                                    if leader["name"] == "points":
                                        player_name = tr(leader["leaders"][0]["athlete"]["displayName"])
                                        points = leader["leaders"][0]["displayValue"]
                                        return f"{player_name} ({points} נק')"
                                return "לא זמין"

                            home_leader = get_top_scorer(0) # בית
                            away_leader = get_top_scorer(1) # חוץ
                        except:
                            home_leader = away_leader = "לא זמין"

                        # בניית ההודעה עם דגשים
                        msg = f"{RTL_MARK}🔥 **התראת קלאץ'! משחק צמוד** 🔥\n\n"
                        msg += f"{RTL_MARK}🏀 **{tr(away['team']['displayName'])}** 🆚 **{tr(home['team']['displayName'])}**\n"
                        msg += f"{RTL_MARK}⏱️ זמן: **{clock} לסיום**\n"
                        msg += f"{RTL_MARK}🔢 תוצאה: **{a_score} - {h_score}**\n\n"
                        msg += f"{RTL_MARK}⭐ **קלעים בולטים:**\n"
                        msg += f"{RTL_MARK}👤 {tr(away['team']['abbreviation'])}: {away_leader}\n"
                        msg += f"{RTL_MARK}👤 {tr(home['team']['abbreviation'])}: {home_leader}\n\n"
                        msg += f"{RTL_MARK}🚨 **כנסו עכשיו למשחק!**"
                        
                        send_telegram(msg)

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("🚀 בוט קלאץ' (הפרש 4, 4 דקות אחרונות, ללא הארכה) פעיל...")
    while True:
        check_all_nba_clutch()
        
        # איפוס רשימה בצהריים
        now = datetime.now(pytz.timezone('Asia/Jerusalem'))
        if now.hour == 14 and now.minute == 0:
            sent_clutch_alerts.clear()
            
        time.sleep(20)

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
        # תרגום בסיסי + תיקון שמות קבוצות שנוטים להשתבש
        t = translator.translate(text)
        replacements = {
            "שבילים בלייזרים": "פורטלנד",
            "רשתות": "ברוקלין",
            "לוחמים": "גולדן סטייט",
            "בוכנות": "דטרויט",
            "מלכים": "סקרמנטו",
            "אגמים": "לייקרס",
            "שלוחה": "סן אנטוניו",
            "יוטה ג'אז": "יוטה",
            "תרבויות": "מיאמי"
        }
        for eng, heb in replacements.items():
            t = t.replace(eng, heb)
        return t
    except: return text

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try: 
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"Telegram Error: {r.text}")
    except Exception as e: 
        print(f"Request Error: {e}")

def check_all_nba_clutch():
    global sent_clutch_alerts
    try:
        resp = requests.get(NBA_SCOREBOARD, timeout=5).json()
        for ev in resp.get("events", []):
            gid = ev["id"]
            status = ev["status"]
            
            # בדיקה אם המשחק ברבע הרביעי ופעיל
            if status["type"]["state"] == "in":
                clock = status["displayClock"]
                period = status["period"]
                
                # --- תנאי זמן: רק רבע 4 ופחות מ-3 דקות ---
                if period != 4: continue
                
                try:
                    if ":" in clock:
                        minutes = int(clock.split(":")[0])
                        if minutes >= 3: continue # רק מתחת ל-3 דקות
                except: continue

                competition = ev["competitions"][0]
                home = competition["competitors"][0]
                away = competition["competitors"][1]
                
                try:
                    h_score = int(home["score"])
                    a_score = int(away["score"])
                    diff = abs(h_score - a_score)
                except: continue

                # --- תנאי הפרש: 3 ומטה ---
                if diff <= 3:
                    if gid not in sent_clutch_alerts:
                        sent_clutch_alerts.add(gid)
                        
                        # שליפת קלעים מובילים
                        try:
                            def get_top_scorer(comp_idx):
                                leaders = competition["competitors"][comp_idx].get("leaders", [])
                                for leader in leaders:
                                    if leader["name"] == "points":
                                        p_name = tr(leader["leaders"][0]["athlete"]["displayName"])
                                        pts = leader["leaders"][0]["displayValue"]
                                        return f"{p_name} ({pts} נק')"
                                return "לא זמין"

                            home_leader = get_top_scorer(0)
                            away_leader = get_top_scorer(1)
                        except:
                            home_leader = away_leader = "לא זמין"

                        # --- בניית ההודעה (שימוש ב-Markdown תקני) ---
                        # שימי לב: אין רווח בין ה-** לטקסט
                        msg = f"{RTL_MARK}🔥 *התראת קלאץ'! משחק צמוד* 🔥\n\n"
                        msg += f"{RTL_MARK}🏀 **{tr(away['team']['displayName'])}** 🆚 **{tr(home['team']['displayName'])}**\n"
                        msg += f"{RTL_MARK}⏱️ זמן: **{clock} לסיום**\n"
                        msg += f"{RTL_MARK}🔢 תוצאה: **{a_score} - {h_score}**\n\n"
                        msg += f"{RTL_MARK}⭐ **קלעים בולטים:**\n"
                        msg += f"{RTL_MARK}👤 {away['team']['abbreviation']}: {away_leader}\n"
                        msg += f"{RTL_MARK}👤 {home['team']['abbreviation']}: {home_leader}\n\n"
                        msg += f"{RTL_MARK}🚨 **כנסו עכשיו למשחק!**"
                        
                        send_telegram(msg)

    except Exception as e:
        print(f"Error logic: {e}")

if __name__ == "__main__":
    print("🚀 בוט קלאץ' (הפרש 3, 3 דקות אחרונות) פעיל...")
    while True:
        check_all_nba_clutch()
        
        # איפוס רשימה בצהריים כדי לאפשר התראות למשחקי הלילה הבא
        now = datetime.now(pytz.timezone('Asia/Jerusalem'))
        if now.hour == 14 and now.minute == 0:
            sent_clutch_alerts.clear()
            time.sleep(65) # מניעת איפוס כפול באותה דקה
            
        time.sleep(15) # בדיקה כל 15 שניות

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
sent_clutch_alerts = {} 

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

def is_clutch_time(clock_str, period):
    """בודק אם אנחנו בזמן קלאץ' (רבע 4 פחות מ-5 דק', או כל זמן בהארכה)"""
    try:
        if period >= 4:
            if ":" in clock_str:
                minutes = int(clock_str.split(":")[0])
                return minutes < 5
            return True # אם זה שניות בלבד או פורמט אחר ברבע 4+
        return False
    except: return False

def check_all_nba_clutch():
    global sent_clutch_alerts
    try:
        resp = requests.get(NBA_SCOREBOARD, timeout=5).json()
        for ev in resp.get("events", []):
            gid = ev["id"]
            status = ev["status"]["type"]
            
            if status["state"] == "in":
                clock = ev["status"]["displayClock"]
                period = ev["status"]["period"]
                home = ev["competitions"][0]["competitors"][0]
                away = ev["competitions"][0]["competitors"][1]
                
                try:
                    h_score = int(home["score"])
                    a_score = int(away["score"])
                    diff = abs(h_score - a_score)
                except: continue

                # התנאי החדש: חייב להיות זמן קלאץ' וגם הפרש 5 ומטה
                if is_clutch_time(clock, period) and diff <= 5:
                    if gid not in sent_clutch_alerts:
                        sent_clutch_alerts[gid] = True
                        
                        msg = f"{RTL_MARK}🔥 **התראת קלאץ'! משחק צמוד** 🔥\n\n"
                        msg += f"{RTL_MARK}🏀 {tr(away['team']['displayName'])} 🆚 {tr(home['team']['displayName'])}\n"
                        msg += f"{RTL_MARK}⏱️ זמן: **{clock} לרבע {period}**\n"
                        msg += f"{RTL_MARK}🔢 תוצאה: **{a_score} - {h_score}**\n\n"
                        msg += f"{RTL_MARK}🚨 כנסו עכשיו למשחק!"
                        
                        send_telegram(msg)

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("🚀 בוט קלאץ' (סריקה כל 15 שניות) פעיל...")
    while True:
        check_all_nba_clutch()
        if datetime.now(pytz.timezone('Asia/Jerusalem')).hour == 14:
            sent_clutch_alerts = {}
        time.sleep(15)

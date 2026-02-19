import requests
import time
import re
from deep_translator import GoogleTranslator

# --- הגדרות ---
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
MY_CHAT_ID = "-1003808107418"
translator = GoogleTranslator(source='en', target='iw')

def translate_heb(text):
    if not text: return ""
    try: return translator.translate(text)
    except: return text

def send_msg(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": MY_CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=15)
    except: pass

def get_live_ncaa_scraping():
    """שאיבת נתונים ישירות מהאתר כדי לעקוף את הדיליי של ה-API"""
    try:
        # דף התוצאות הכללי של המכללות
        url = "https://site.web.api.espn.com/apis/v2/scoreboard/header?sport=basketball&league=mens-college-basketball&region=us&lang=en&contentorigin=espn"
        headers = {'User-Agent': 'Mozilla/5.0'}
        data = requests.get(url, headers=headers, timeout=10).json()
        
        sports = data.get('sports', [])
        if not sports: return
        
        leagues = sports[0].get('leagues', [])
        if not leagues: return
        
        events = leagues[0].get('events', [])
        active_found = False

        for ev in events:
            # בודק אם המשחק בסטטוס "In Progress"
            status = ev['status']['type']['state']
            if status == 'in':
                active_found = True
                t1 = ev['competitors'][0]
                t2 = ev['competitors'][1]
                
                t1_name = translate_heb(t1['homeAway'].capitalize() + ": " + t1['displayName'])
                t2_name = translate_heb(t2['homeAway'].capitalize() + ": " + t2['displayName'])
                score = f"{t1['score']} - {t2['score']}"
                clock = ev['status']['displayClock']
                
                # בניית הודעה עם תוצאה חיה
                msg = f"🏀 *משחק פעיל בזמן אמת:* \n🏟️ {t1_name} {score} {t2_name}\n⏱️ שעון: {clock}\n"
                
                # ניסיון למשוך סטטיסטיקת חמישייה מה-Summary המהיר
                gid = ev['id']
                stats_url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event={gid}"
                stats_data = requests.get(stats_url, headers=headers, timeout=10).json()
                
                for team in stats_data.get('boxscore', {}).get('players', []):
                    team_label = translate_heb(team['team']['displayName'])
                    msg += f"\n📊 *{team_label}:*\n"
                    # מושך רק את ה-5 שחקנים ששיחקו הכי הרבה דקות (בד"כ החמישייה)
                    players = team.get('statistics', [{}])[0].get('athletes', [])
                    for p in players[:5]: 
                        p_name = translate_heb(p['athlete']['displayName'])
                        s = p['stats']
                        if len(s) >= 13:
                            msg += f"⭐️ {p_name}: {s[12]}נ' | {s[6]}ר' | {s[7]}א'\n"
                
                send_msg(msg)
                time.sleep(2)

        if not active_found:
            print("No live NCAA games at the moment.")

    except Exception as e:
        print(f"Scraping Error: {e}")

if __name__ == "__main__":
    print("🚀 הבוט עובד במצב Scraping - ללא מגבלת בקשות")
    while True:
        get_live_ncaa_scraping()
        # המתנה של 2 דקות
        time.sleep(120)

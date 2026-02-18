import requests
import time
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

def get_realtime_data(game_id):
    """שליפת נתונים עמוקה לעקיפת הדיליי של הלוח הראשי"""
    try:
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event={game_id}"
        data = requests.get(url, timeout=10).json()
        
        header = data.get('header', {})
        comp = header.get('competitions', [{}])[0]
        status_text = comp.get('status', {}).get('type', {}).get('description', "")
        clock = comp.get('status', {}).get('displayClock', "0:00")
        
        t1 = comp.get('competitors', [])[0]
        t2 = comp.get('competitors', [])[1]
        
        # אם אין ניקוד בכלל, המשחק באמת עוד לא התחיל ב-API
        if t1['score'] == "0" and t2['score'] == "0":
            return None

        t1_name = translate_heb(t1['team']['shortDisplayName'])
        t2_name = translate_heb(t2['team']['shortDisplayName'])
        score = f"{t1['score']} - {t2['score']}"

        report = f"🏀 *עדכון חי (כל 2 דקות):* {t1_name} {score} {t2_name}\n⏱️ מצב: {status_text} ({clock})\n"
        
        # שליפת חמישיות
        for team in data.get('boxscore', {}).get('players', []):
            team_name = translate_heb(team['team']['displayName'])
            report += f"\n📊 *{team_name}:*\n"
            players = team.get('statistics', [{}])[0].get('athletes', [])
            starters = [p for p in players if p.get('starter')]
            
            for p in starters:
                p_name = translate_heb(p['athlete']['displayName'])
                s = p['stats']
                if len(s) > 12:
                    report += f"⭐️ {p_name}: {s[12]}נ' | {s[6]}ר' | {s[7]}א'\n"
        
        return report
    except: return None

def main_loop():
    print("🚀 הבוט נכנס למצב עבודה: עדכון כל 2 דקות.")
    send_msg("⚙️ *המערכת הוגדרה:* תקבל עדכון על כל המשחקים הפעילים בכל 2 דקות.")
    
    while True:
        try:
            # מקבל את רשימת כל ה-IDs של משחקי היום
            list_url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
            resp = requests.get(list_url, timeout=10).json()
            
            found_any = False
            for ev in resp.get('events', []):
                gid = ev['id']
                # בדיקה עמוקה לכל משחק
                content = get_realtime_data(gid)
                if content:
                    send_msg(content)
                    found_any = True
                    time.sleep(1.5) # הפסקה קצרה כדי לא להציף את טלגרם בבת אחת
            
            if not found_any:
                print("סריקה הושלמה: אין משחקים פעילים עם ניקוד כרגע.")
                
        except Exception as e:
            print(f"Error in loop: {e}")
        
        # המתנה של 2 דקות (120 שניות) לפני הסבב הבא
        time.sleep(120)

if __name__ == "__main__":
    main_loop()

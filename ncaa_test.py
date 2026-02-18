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

def get_game_data(game_id):
    """שימוש ב-Core API - המקור הכי אמין של ESPN לנתוני אמת"""
    try:
        # פנייה ל-Core API לקבלת נתונים חיים בלבד
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event={game_id}"
        data = requests.get(url, timeout=10).json()
        
        boxscore = data.get('boxscore', {})
        header = data.get('header', {})
        comp = header.get('competitions', [{}])[0]
        
        t1 = comp['competitors'][0]
        t2 = comp['competitors'][1]
        
        # בדיקה קריטית: אם אין ניקוד או שהסטטוס הוא 'Pre', דלג
        if int(t1['score']) == 0 and int(t2['score']) == 0:
            return None

        t1_name = translate_heb(t1['team']['shortDisplayName'])
        t2_name = translate_heb(t2['team']['shortDisplayName'])
        score = f"{t1['score']} - {t2['score']}"
        clock = comp['status']['displayClock']
        period = comp['status']['period']

        report = f"🏀 *עדכון חי:* {t1_name} {score} {t2_name}\n⏱️ זמן: חצי {period} ({clock})\n"

        for team_data in boxscore.get('players', []):
            t_name = translate_heb(team_data['team']['displayName'])
            report += f"\n📊 *{t_name}:*\n"
            
            # לוקחים חמישייה בלבד למהירות
            starters = [p for p in team_data.get('statistics', [{}])[0].get('athletes', []) if p.get('starter')]
            
            for p in starters:
                p_name = translate_heb(p['athlete']['displayName'])
                s = p['stats']
                if len(s) > 12:
                    report += f"⭐️ {p_name}: {s[12]}נ' | {s[6]}ר' | {s[7]}א'\n"
        
        return report
    except:
        return None

def run_monitor():
    print("🔄 מריץ סריקת עומק...")
    while True:
        try:
            # לוח המשחקים הכללי
            url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
            resp = requests.get(url, timeout=10).json()
            
            found_games = False
            for ev in resp.get('events', []):
                gid = ev['id']
                # בדיקה ישירה של המשחק
                game_report = get_game_data(gid)
                if game_report:
                    send_msg(game_report)
                    found_games = True
                    time.sleep(2)

            if not found_games:
                print("No live scoring games found in API yet.")
                
        except Exception as e:
            print(f"Error: {e}")
        
        # סריקה כל 2 דקות
        time.sleep(120)

if __name__ == "__main__":
    run_monitor()

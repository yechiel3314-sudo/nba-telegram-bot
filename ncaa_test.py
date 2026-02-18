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

def get_filtered_stats(game_id):
    try:
        # פנייה ישירה לסיכום המשחק המפורט
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event={game_id}"
        data = requests.get(url, timeout=10).json()
        report = ""
        
        for team in data.get('boxscore', {}).get('players', []):
            t_name = translate_heb(team['team']['displayName'])
            report += f"\n🏀 *{t_name}*\n"
            
            all_players = team.get('statistics', [{}])[0].get('athletes', [])
            if not all_players:
                report += "עדיין אין סטטיסטיקת שחקנים זמינה\n"
                continue

            starters = [p for p in all_players if p.get('starter')]
            bench = sorted([p for p in all_players if not p.get('starter')], 
                           key=lambda x: int(x['stats'][0]) if x['stats'][0].isdigit() else 0, reverse=True)[:3]
            
            for p in starters + bench:
                p_name = translate_heb(p['athlete']['displayName'])
                s = p['stats']
                prefix = "⭐️" if p.get('starter') else "👟"
                # בדיקה שיש מספיק נתונים במערך הסטטיסטיקה
                if len(s) > 12:
                    report += f"{prefix} *{p_name}*: {s[12]} נק' | {s[6]} ריב' | {s[7]} אס'\n"
                else:
                    report += f"{prefix} *{p_name}*: טרם עודכן\n"
        return report
    except: return "❌ שגיאה בשליפת נתונים מפורטים"

def run_forced_check():
    """סורק הכל ושולח ללא סינונים"""
    try:
        url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
        resp = requests.get(url, timeout=10).json()
        events = resp.get('events', [])
        
        send_msg(f"🚨 *בדיקה כפויה:* שולף נתונים עבור {len(events)} משחקים...")

        for ev in events:
            gid = ev['id']
            t1_data = ev['competitions'][0]['competitors'][0]
            t2_data = ev['competitions'][0]['competitors'][1]
            
            t1_name = translate_heb(t1_data['team']['shortDisplayName'])
            t2_name = translate_heb(t2_data['team']['shortDisplayName'])
            score = f"{t1_data['score']} - {t2_data['score']}"
            status = ev['status']['type']['description']

            # שליפת הסטטיסטיקה לכל משחק שנמצא בלוח
            stats = get_filtered_stats(gid)
            
            msg = f"📊 *עדכון חי:* {t1_name} {score} {t2_name}\n⏱️ מצב: {status}\n{stats}"
            send_msg(msg)
            time.sleep(2) # מניעת חסימת טלגרם
            
    except Exception as e:
        send_msg(f"❌ שגיאה כללית: {str(e)}")

if __name__ == "__main__":
    run_forced_check()
    # משאיר את הבוט דולק ב-Railway
    while True:
        time.sleep(60)

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
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event={game_id}"
        data = requests.get(url, timeout=10).json()
        report = ""
        for team in data.get('boxscore', {}).get('players', []):
            t_name = translate_heb(team['team']['displayName'])
            report += f"\n🏀 *{t_name}*\n"
            all_players = team.get('statistics', [{}])[0].get('athletes', [])
            
            # שולף רק שחקני חמישייה (Starters)
            starters = [p for p in all_players if p.get('starter')]
            
            for p in starters:
                p_name = translate_heb(p['athlete']['displayName'])
                s = p['stats']
                if len(s) > 12:
                    report += f"⭐️ *{p_name}*: {s[12]} נק' | {s[6]} ריב' | {s[7]} אס'\n"
        return report
    except: return "❌ אין סטטיסטיקת שחקנים זמינה כרגע"

def run_immediate_live_check():
    """סורק ושולף נתונים רק למשחקים שבאמת רצים עכשיו"""
    try:
        url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
        resp = requests.get(url, timeout=10).json()
        events = resp.get('events', [])
        
        found_active = False
        for ev in events:
            gid = ev['id']
            status_obj = ev['status']
            clock = status_obj.get('displayClock', "20:00")
            
            t1_data = ev['competitions'][0]['competitors'][0]
            t2_data = ev['competitions'][0]['competitors'][1]
            t1_score = int(t1_data['score'])
            t2_score = int(t2_data['score'])

            # הגדרה למשחק שהתחיל: שעון זז או שיש ניקוד
            is_active = (clock != "20:00" and clock != "0:00") or (t1_score > 0 or t2_score > 0)

            if is_active:
                found_active = True
                t1_name = translate_heb(t1_data['team']['shortDisplayName'])
                t2_name = translate_heb(t2_data['team']['shortDisplayName'])
                score_str = f"{t1_score} - {t2_score}"
                
                stats = get_filtered_stats(gid)
                msg = f"✅ *משחק פעיל זוהה:*\n🏟️ {t1_name} {score_str} {t2_name}\n⏱️ שעון: {clock}\n{stats}"
                send_msg(msg)
                time.sleep(2)

        if not found_active:
            send_msg("🔎 סריקה הושלמה: לא נמצאו משחקים עם שעון רץ או ניקוד כרגע.")
            
    except Exception as e:
        send_msg(f"❌ שגיאה בסריקה: {str(e)}")

if __name__ == "__main__":
    run_immediate_live_check()

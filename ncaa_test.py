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
            starters = [p for p in all_players if p.get('starter')]
            bench = sorted([p for p in all_players if not p.get('starter')], 
                           key=lambda x: int(x['stats'][0]) if x['stats'][0].isdigit() else 0, reverse=True)[:3]
            for p in starters + bench:
                p_name = translate_heb(p['athlete']['displayName'])
                s = p['stats']
                prefix = "⭐️" if p.get('starter') else "👟"
                if len(s) > 12:
                    report += f"{prefix} *{p_name}*: {s[12]} נק' | {s[6]} ריב' | {s[7]} אס'\n"
        return report
    except: return "❌ אין סטטיסטיקה זמינה כרגע"

def run_immediate_check():
    """סורק את כל המשחקים בלוח ללא יוצא מן הכלל"""
    try:
        url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
        resp = requests.get(url, timeout=10).json()
        events = resp.get('events', [])
        
        send_msg(f"🔎 *סריקה כללית:* בודק {len(events)} משחקים בלוח...")

        for ev in events:
            gid = ev['id']
            # מושך נתונים לכל משחק שיש לו כבר תוצאה או שהוא לא 'pre'
            status_text = ev['status']['type']['description']
            
            t1 = translate_heb(ev['competitions'][0]['competitors'][0]['team']['shortDisplayName'])
            t2 = translate_heb(ev['competitions'][0]['competitors'][1]['team']['shortDisplayName'])
            score = f"{ev['competitions'][0]['competitors'][0]['score']} - {ev['competitions'][0]['competitors'][1]['score']}"
            
            # אם יש כבר נקודות, נשלח סטטיסטיקה
            if ev['competitions'][0]['competitors'][0]['score'] != "0" or "1st" in status_text or "2nd" in status_text:
                stats = get_filtered_stats(gid)
                msg = f"📊 *עדכון משחק:* {t1} 🆚 {t2}\n⏱️ מצב: {status_text}\n🔹 תוצאה: {score}\n{stats}"
                send_msg(msg)
                time.sleep(1)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run_immediate_check()
    # כאן הוספתי לופ פשוט שימשיך לעבוד
    while True:
        time.sleep(60)

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
    except: return "❌ שגיאה בשליפת סטטיסטיקה"

def run_immediate_check():
    """פונקציה שרצה פעם אחת בסטארט-אפ ושולחת מצב קיים של כל המשחקים"""
    print("מריץ בדיקה מיידית על כל המשחקים...")
    try:
        url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
        resp = requests.get(url, timeout=10).json()
        active_games = [ev for ev in resp.get('events', []) if ev['status']['type']['state'].lower() != 'pre']
        
        if not active_games:
            send_msg("ℹ️ לא נמצאו משחקים פעילים כרגע לסריקה.")
            return

        send_msg(f"🔍 *בדיקת מערכת:* נמצאו {len(active_games)} משחקים פעילים. שולף נתונים...")
        
        for ev in active_games:
            gid = ev['id']
            t1 = translate_heb(ev['competitions'][0]['competitors'][0]['team']['shortDisplayName'])
            t2 = translate_heb(ev['competitions'][0]['competitors'][1]['team']['shortDisplayName'])
            score = f"{ev['competitions'][0]['competitors'][0]['score']} - {ev['competitions'][0]['competitors'][1]['score']}"
            clock = ev['status'].get('displayClock', "0:00")
            
            stats = get_filtered_stats(gid)
            msg = f"📊 *סטטוס משחק חי:*\n🏟️ {t1} {score} {t2}\n⏱️ שעון: {clock}\n{stats}"
            send_msg(msg)
            time.sleep(2) # הפסקה קצרה בין הודעות למניעת חסימה
    except Exception as e:
        print(f"Startup check error: {e}")

def monitor():
    # שלב 1: בדיקה מיידית על הכל
    run_immediate_check()
    
    # שלב 2: לופ הניטור הרגיל
    sent = {}
    print("עובר למצב ניטור רגיל...")
    while True:
        try:
            url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
            resp = requests.get(url, timeout=10).json()
            for ev in resp.get('events', []):
                gid = ev['id']
                status = ev['status']
                state = status['type']['state'].lower()
                clock = status.get('displayClock', "0:00")
                period = status.get('period', 1)
                
                # תנאי אמצע חצי (מתחת ל-10 דקות)
                try:
                    mins = int(clock.split(":")[0])
                except: mins = 20
                
                if state == 'in' and mins < 10 and f"{gid}_mid_{period}" not in sent:
                    stats = get_filtered_stats(gid)
                    t1 = translate_heb(ev['competitions'][0]['competitors'][0]['team']['shortDisplayName'])
                    t2 = translate_heb(ev['competitions'][0]['competitors'][1]['team']['shortDisplayName'])
                    score = f"{ev['competitions'][0]['competitors'][0]['score']}-{ev['competitions'][0]['competitors'][1]['score']}"
                    send_msg(f"⏰ *עדכון 10 דקות - חצי {period}:*\n🏟️ {t1} {score} {t2}\n{stats}")
                    sent[f"{gid}_mid_{period}"] = True

                # תנאי מחצית
                if "half" in status['type']['description'].lower() and f"{gid}_h" not in sent:
                    stats = get_filtered_stats(gid)
                    send_msg(f"🏀 *סיכום מחצית:* \n{stats}")
                    sent[f"{gid}_h"] = True

        except Exception as e: print(f"Error: {e}")
        time.sleep(30)

if __name__ == "__main__":
    monitor()

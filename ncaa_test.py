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
    try:
        # שימוש ב-API של ה-NBA (יותר אמין)
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={game_id}"
        data = requests.get(url, timeout=10).json()
        
        boxscore = data.get('boxscore', {})
        header = data.get('header', {})
        comp = header.get('competitions', [{}])[0]
        
        t1 = comp['competitors'][0]
        t2 = comp['competitors'][1]
        
        # מושך נתונים גם אם הניקוד הוא 0-0, רק כדי לראות שהוא קורא!
        t1_name = translate_heb(t1['team']['shortDisplayName'])
        t2_name = translate_heb(t2['team']['shortDisplayName'])
        score = f"{t1['score']} - {t2['score']}"
        clock = comp['status']['displayClock']

        report = f"🏀 *בדיקת NBA:* {t1_name} {score} {t2_name}\n⏱️ זמן: {clock}\n"

        for team_data in boxscore.get('players', []):
            t_name = translate_heb(team_data['team']['displayName'])
            report += f"\n📊 *{t_name}*:\n"
            players = team_data.get('statistics', [{}])[0].get('athletes', [])
            # שולף את 3 השחקנים הראשונים ברשימה לבדיקה
            for p in players[:3]:
                p_name = translate_heb(p['athlete']['displayName'])
                s = p['stats']
                if len(s) > 12:
                    report += f"👤 {p_name}: {s[12]}נ' | {s[6]}ר'\n"
        
        return report
    except: return None

def run_monitor():
    send_msg("🧪 *מתחיל בדיקת NBA עוקפת דיליי...*")
    while True:
        try:
            # לוח משחקי NBA
            url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
            resp = requests.get(url, timeout=10).json()
            
            for ev in resp.get('events', []):
                gid = ev['id']
                game_report = get_game_data(gid)
                if game_report:
                    send_msg(game_report)
                    time.sleep(2)
            
            send_msg("✅ סבב בדיקה הושלם.")
        except Exception as e:
            print(f"Error: {e}")
        
        time.sleep(300) # בדיקה כל 5 דקות

if __name__ == "__main__":
    run_monitor()

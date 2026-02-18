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
    """שליפת נתונים ישירה מה-Summary לעקיפת הדיליי של ה-Scoreboard"""
    try:
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event={game_id}"
        data = requests.get(url, timeout=10).json()
        
        header = data.get('header', {})
        competitors = header.get('competitions', [{}])[0].get('competitors', [])
        
        # זיהוי קבוצות ותוצאה מהראש (Header)
        t1 = competitors[0]
        t2 = competitors[1]
        t1_name = translate_heb(t1['team']['shortDisplayName'])
        t2_name = translate_heb(t2['team']['shortDisplayName'])
        score = f"{t1['score']} - {t2['score']}"
        clock = header.get('competitions', [{}])[0].get('status', {}).get('displayClock', "0:00")
        
        # בדיקה אם באמת יש ניקוד (מישהו קלע)
        if t1['score'] == "0" and t2['score'] == "0":
            return None

        report = f"✅ *משחק חי זוהה!* \n🏟️ {t1_name} {score} {t2_name}\n⏱️ שעון: {clock}\n"
        
        # הוספת סטטיסטיקת שחקנים (חמישייה)
        for team in data.get('boxscore', {}).get('players', []):
            team_title = translate_heb(team['team']['displayName'])
            report += f"\n📊 *{team_title}*:\n"
            all_players = team.get('statistics', [{}])[0].get('athletes', [])
            starters = [p for p in all_players if p.get('starter')]
            
            for p in starters:
                p_name = translate_heb(p['athlete']['displayName'])
                s = p['stats']
                if len(s) > 12:
                    report += f"⭐️ {p_name}: {s[12]}נ' | {s[6]}ר' | {s[7]}א'\n"
        
        return report
    except: return None

def run_direct_sync():
    print("🔄 מריץ סנכרון ישיר לעקיפת הדיליי...")
    try:
        # קבלת רשימת ה-IDs של כל משחקי היום
        url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
        resp = requests.get(url, timeout=10).json()
        
        for ev in resp.get('events', []):
            gid = ev['id']
            # בדיקה ישירה לתוך הקרביים של המשחק
            result = get_realtime_data(gid)
            if result:
                send_msg(result)
                time.sleep(2) # מניעת הצפה
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run_direct_sync()

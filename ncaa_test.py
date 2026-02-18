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

def get_ncaa_live_data(game_id):
    """משיכת נתונים מנתיב ה-Live של ESPN שעוקף את הדיליי הרגיל"""
    try:
        # שימוש בנתיב summary שמכיל נתונים הרבה יותר מעודכנים מה-Scoreboard
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event={game_id}"
        data = requests.get(url, timeout=10).json()
        
        header = data.get('header', {})
        competition = header.get('competitions', [{}])[0]
        status = competition.get('status', {})
        
        # בדיקה אם יש כבר נקודות ב-Summary (זה המדד האמיתי)
        t1 = competition.get('competitors', [])[0]
        t2 = competition.get('competitors', [])[1]
        
        s1 = int(t1.get('score', 0))
        s2 = int(t2.get('score', 0))
        
        # אם התוצאה היא 0-0, המשחק באמת לא התחיל בשרתים של ESPN
        if s1 == 0 and s2 == 0:
            return None

        t1_name = translate_heb(t1['team']['shortDisplayName'])
        t2_name = translate_heb(t2['team']['shortDisplayName'])
        clock = status.get('displayClock', "0:00")
        period = status.get('period', 1)

        report = f"🏀 *עדכון חי (NCAA):* {t1_name} {s1} - {s2} {t2_name}\n⏱️ זמן: חצי {period} ({clock})\n"
        
        # סטטיסטיקה של החמישייה
        boxscore = data.get('boxscore', {})
        for team_stat in boxscore.get('players', []):
            team_title = translate_heb(team_stat['team']['displayName'])
            report += f"\n📊 *{team_title}:*\n"
            
            # לוקחים רק שחקנים שהם Starters (חמישייה)
            athletes = team_stat.get('statistics', [{}])[0].get('athletes', [])
            for p in athletes:
                if p.get('starter'):
                    p_name = translate_heb(p['athlete']['displayName'])
                    s = p['stats']
                    # במכללות: [MIN, FG, 3PT, FT, OREB, DREB, REB, AST, STL, BLK, TO, PF, PTS] (סה"כ 13 שדות)
                    if len(s) >= 13:
                        report += f"⭐️ {p_name}: {s[12]}נ' | {s[6]}ר' | {s[7]}א'\n"
        
        return report
    except:
        return None

def main_monitor():
    print("🚀 סורק מכללות במצב עומק (כל 2 דקות)...")
    send_msg("🔎 *בדיקת מכללות:* מתחיל סריקה עמוקה של כל המשחקים בלוח...")
    
    while True:
        try:
            # קבלת רשימת כל המשחקים של היום
            url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
            resp = requests.get(url, timeout=10).json()
            
            active_found = False
            for ev in resp.get('events', []):
                gid = ev['id']
                # הולך לבדוק כל משחק בנפרד ב-API הפנימי
                result = get_ncaa_live_data(gid)
                if result:
                    send_msg(result)
                    active_found = True
                    time.sleep(2) # הפסקה קצרה
            
            if not active_found:
                print("לא נמצאו משחקים עם ניקוד מעל 0-0 כרגע.")
                
        except Exception as e:
            print(f"Error: {e}")
            
        time.sleep(120) # המתנה של 2 דקות

if __name__ == "__main__":
    main_monitor()

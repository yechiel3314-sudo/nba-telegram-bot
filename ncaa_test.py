import requests
import time
from deep_translator import GoogleTranslator

# --- הגדרות ---
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
MY_CHAT_ID = "-1003808107418"
translator = GoogleTranslator(source='en', target='iw')

def translate_heb(text):
    if not text: return ""
    try:
        # תרגום מהיר עם מגבלת זמן
        return translator.translate(text)
    except:
        return text

def send_msg(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": MY_CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except:
        pass

def get_filtered_stats(game_id):
    try:
        # שימוש ב-Summary API לקבלת נתוני שחקנים מפורטים
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event={game_id}"
        data = requests.get(url, timeout=10).json()
        report = ""
        
        for team in data.get('boxscore', {}).get('players', []):
            t_name = translate_heb(team['team']['displayName'])
            report += f"\n🏀 *{t_name}*\n"
            report += "--------------------------\n"
            
            all_players = team.get('statistics', [{}])[0].get('athletes', [])
            
            # סינון חמישייה
            starters = [p for p in all_players if p.get('starter')]
            # סינון ספסל (3 הכי פעילים לפי דקות משחק)
            bench = sorted([p for p in all_players if not p.get('starter')], 
                           key=lambda x: int(x['stats'][0]) if x['stats'][0].isdigit() else 0, 
                           reverse=True)[:3]
            
            for p in starters + bench:
                p_name_en = p['athlete']['displayName']
                p_name_he = translate_heb(p_name_en)
                s = p['stats'] # [MIN, FG, 3PT, FT, OREB, DREB, REB, AST, STL, BLK, TO, PF, PTS]
                
                prefix = "⭐️" if p.get('starter') else "👟"
                
                # פורמט הודעה יפה: שם | נקודות | ריבאונדים | אסיסטים
                if len(s) > 12:
                    line = f"{prefix} *{p_name_he}*: {s[12]} נק' | {s[6]} ריב' | {s[7]} אס'"
                    report += line + "\n"
            
        return report
    except Exception as e:
        return f"❌ שגיאה בשליפת סטטיסטיקה: {str(e)}"

def monitor():
    sent = {}
    send_msg("💎 *בוט ה-NBA/מכללות מוכן עם עיצוב משופר בעברית!*")
    
    while True:
        try:
            # כתובת ה-API (למחר נחליף ל-nba במקום mens-college-basketball)
            url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
            resp = requests.get(url, timeout=10).json()
            
            for ev in resp.get('events', []):
                gid = ev['id']
                status = ev['status']
                state = status['type']['state'].lower()
                clock = status.get('displayClock', "0:00")
                period = status.get('period', 1)
                
                # זיהוי אם אנחנו מתחת ל-10 דקות לסיום החצי
                is_mid_point = False
                try:
                    mins = int(clock.split(":")[0])
                    if mins < 10: is_mid_point = True
                except: pass

                # שמות קבוצות ותוצאה
                t1 = translate_heb(ev['competitions'][0]['competitors'][0]['team']['shortDisplayName'])
                t2 = translate_heb(ev['competitions'][0]['competitors'][1]['text'] if 'text' in ev['competitions'][0]['competitors'][1]['team'] else ev['competitions'][0]['competitors'][1]['team']['shortDisplayName'])
                score = f"{ev['competitions'][0]['competitors'][0]['score']} - {ev['competitions'][0]['competitors'][1]['score']}"

                # 1. הודעת פתיחה
                if state == 'in' and gid not in sent:
                    send_msg(f"🔥 *המשחק יצא לדרך!* 🔥\n🏟️ {translate_heb(t1)} 🆚 {translate_heb(t2)}")
                    sent[gid] = "STARTED"

                # 2. עדכון אמצע חצי + סטטיסטיקה מורחבת
                if state == 'in' and is_mid_point and f"{gid}_mid_{period}" not in sent:
                    stats = get_filtered_stats(gid)
                    msg = f"⏰ *עדכון אמצע חצי {period}* ({clock})\n🏟️ {t1} {score} {t2}\n{stats}"
                    send_msg(msg)
                    sent[f"{gid}_mid_{period}"] = True

                # 3. מחצית
                if "half" in status['type']['description'].lower() and f"{gid}_h" not in sent:
                    stats = get_filtered_stats(gid)
                    send_msg(f"🏀 *סיכום מחצית:* {t1} {score} {t2} 🏀\n{stats}")
                    sent[f"{gid}_h"] = True

        except Exception as e:
            print(f"Error: {e}")
        
        time.sleep(30)

if __name__ == "__main__":
    monitor()

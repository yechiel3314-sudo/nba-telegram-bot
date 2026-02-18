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
    except: return "❌ סטטיסטיקה לא זמינה"

def monitor_college_basketball():
    sent_states = {}
    send_msg("🚀 *הבוט פעיל:* מעקב תחילת משחק, כל 10 דקות, מחצית וסיום.")

    while True:
        try:
            url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
            resp = requests.get(url, timeout=10).json()
            
            for ev in resp.get('events', []):
                gid = ev['id']
                status_obj = ev['status']
                state = status_obj['type']['state'].lower()
                description = status_obj['type']['description'].lower()
                clock = status_obj.get('displayClock', "0:00")
                period = status_obj.get('period', 1)
                
                # המרת שעון למספר לבדיקת ה-10 דקות
                try: mins = int(clock.split(':')[0])
                except: mins = 20

                t1 = translate_heb(ev['competitions'][0]['competitors'][0]['team']['shortDisplayName'])
                t2 = translate_heb(ev['competitions'][0]['competitors'][1]['team']['shortDisplayName'])
                score = f"{ev['competitions'][0]['competitors'][0]['score']} - {ev['competitions'][0]['competitors'][1]['score']}"

                # 1. הודעת תחילת משחק (רק כשמשתנה ל-In)
                if state == 'in' and gid not in sent_states:
                    send_msg(f"🔥 *המשחק יצא לדרך!* 🔥\n🏟️ {t1} 🆚 {t2}")
                    sent_states[gid] = "STARTED"

                # 2. עדכון אמצע חצי (כששעון יורד מ-10:00)
                if state == 'in' and mins < 10:
                    clock_key = f"{gid}_mid_{period}"
                    if clock_key not in sent_states:
                        stats = get_filtered_stats(gid)
                        send_msg(f"⏰ *עדכון 10 דקות לסיום חצי {period}* ({clock})\n🏟️ {t1} {score} {t2}\n{stats}")
                        sent_states[clock_key] = True

                # 3. מחצית
                if "half" in description and f"{gid}_half" not in sent_states:
                    stats = get_filtered_stats(gid)
                    send_msg(f"🏀 *סיכום מחצית:* {t1} {score} {t2}\n{stats}")
                    sent_states[f"{gid}_half"] = True

                # 4. סיום משחק
                if state == 'post' and f"{gid}_final" not in sent_states:
                    stats = get_filtered_stats(gid)
                    send_msg(f"🏁 *סיום משחק:* {t1} {score} {t2}\n{stats}")
                    sent_states[f"{gid}_final"] = True

        except Exception as e:
            print(f"Error: {e}")
            
        time.sleep(30) # סריקה כל חצי דקה

if __name__ == "__main__":
    monitor_college_basketball()

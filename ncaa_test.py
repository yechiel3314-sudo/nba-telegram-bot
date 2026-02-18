import requests
import time
from datetime import datetime
from deep_translator import GoogleTranslator

# --- הגדרות ---
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
MY_CHAT_ID = "-1003808107418"
translator = GoogleTranslator(source='auto', target='iw')

def translate_heb(text):
    try: return translator.translate(text)
    except: return text

def send_msg(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": MY_CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def get_filtered_stats(game_id):
    try:
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event={game_id}"
        data = requests.get(url, timeout=10).json()
        report = ""
        for team in data.get('boxscore', {}).get('players', []):
            t_name = translate_heb(team['team']['displayName'])
            report += f"\n📊 *{t_name}:*\n"
            all_players = team.get('statistics', [{}])[0].get('athletes', [])
            starters = [p for p in all_players if p.get('starter')]
            bench = [p for p in all_players if not p.get('starter')]
            # מיון ספסל לפי דקות (3 הכי פעילים)
            bench = sorted(bench, key=lambda x: int(x['stats'][0]) if x['stats'][0].isdigit() else 0, reverse=True)[:3]
            for p in starters + bench:
                name = translate_heb(p['athlete']['displayName'])
                s = p['stats']
                prefix = "⭐️" if p.get('starter') else "👟"
                line = f"{prefix} {name}: {s[12]}נ' | {s[6]}ר' | {s[7]}א' | {s[8]}חט' | {s[9]}חס'"
                report += line + "\n"
        return report
    except: return "❌ שגיאה בשליפת סטטיסטיקה"

def monitor_college_basketball():
    sent_states = {}
    send_msg("🚀 *הבוט המעודכן עלה:* כולל סטטיסטיקה באמצע חצי ומנגנון למניעת פספוס דקות!")

    while True:
        try:
            url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
            resp = requests.get(url, timeout=10).json()
            
            for ev in resp.get('events', []):
                gid = ev['id']
                status_obj = ev['status']
                state = status_obj['type']['state'].lower()
                description = status_obj['type']['description'].lower()
                display_clock = status_obj.get('displayClock', "0:00")
                period = status_obj.get('period', 1)
                
                # המרת שעון למספר (שניות) כדי לבדוק אם עברנו את ה-10 דקות
                try:
                    minutes = int(display_clock.split(':')[0])
                except:
                    minutes = 20

                t1_short = ev['competitions'][0]['competitors'][0]['team']['shortDisplayName']
                t2_short = ev['competitions'][0]['competitors'][1]['team']['shortDisplayName']
                score = f"{ev['competitions'][0]['competitors'][0]['score']} - {ev['competitions'][0]['competitors'][1]['score']}"

                # 1. הודעת פתיחה
                if state == 'in' and gid not in sent_states:
                    send_msg(f"🔥 *המשחק יצא לדרך!* 🔥\n🏟️ {translate_heb(t1_short)} 🆚 {translate_heb(t2_short)}")
                    sent_states[gid] = "STARTED"

                # 2. עדכון אמצע חצי (מתחת ל-10 דקות) + סטטיסטיקה
                if state == 'in' and minutes < 10:
                    clock_key = f"{gid}_mid_{period}"
                    if clock_key not in sent_states:
                        stats = get_filtered_stats(gid)
                        msg = f"⏰ *אמצע חצי {period} ({display_clock}):*\n🏟️ {translate_heb(t1_short)} 🆚 {translate_heb(t2_short)}\n🔹 תוצאה: {score}\n{stats}"
                        send_msg(msg)
                        sent_states[clock_key] = True

                # 3. מחצית
                if "half" in description or "end of 1st" in description:
                    if f"{gid}_half" not in sent_states:
                        stats = get_filtered_stats(gid)
                        send_msg(f"🏀 *מחצית: {translate_heb(t1_short)} {score} {translate_heb(t2_short)}* 🏀\n{stats}")
                        sent_states[f"{gid}_half"] = True

                # 4. סיום
                if state == 'post' and f"{gid}_final" not in sent_states:
                    stats = get_filtered_stats(gid)
                    send_msg(f"🏁 *סיום: {translate_heb(t1_short)} {score} {translate_heb(t2_short)}* 🏁\n{stats}")
                    sent_states[f"{gid}_final"] = True

        except Exception as e: print(f"Error: {e}")
        time.sleep(30)

if __name__ == "__main__":
    monitor_college_basketball()

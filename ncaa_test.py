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
            # מיון ספסל לפי דקות (לוקחים 3 הכי פעילים)
            bench = sorted(bench, key=lambda x: int(x['stats'][0]) if x['stats'][0].isdigit() else 0, reverse=True)[:3]
            for p in starters + bench:
                name = translate_heb(p['athlete']['displayName'])
                s = p['stats'] # [MIN, FG, 3PT, FT, OREB, DREB, REB, AST, STL, BLK, TO, PF, PTS]
                prefix = "⭐️" if p.get('starter') else "👟"
                line = f"{prefix} {name}: {s[12]}נ' | {s[6]}ר' | {s[7]}א' | {s[8]}חט' | {s[9]}חס'"
                report += line + "\n"
        return report
    except: return "❌ שגיאה בשליפת סטטיסטיקה"

def monitor_college_basketball():
    sent_states = {}
    print("🚀 הבוט סורק את כל משחקי הלילה (כולל 1:30, 2:00, 3:00)...")
    send_msg("🏀 *מערכת המכללות במעקב מלא:* משחקי 01:00, 01:30, 02:00 ו-03:00 בפנים!")

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
                
                t1_name = translate_heb(ev['competitions'][0]['competitors'][0]['team']['shortDisplayName'])
                t2_name = translate_heb(ev['competitions'][0]['competitors'][1]['team']['shortDisplayName'])
                score = f"{ev['competitions'][0]['competitors'][0]['score']} - {ev['competitions'][0]['competitors'][1]['score']}"

                # 1. הודעת פתיחה
                if state == 'in' and gid not in sent_states:
                    send_msg(f"🔥 *המשחק יצא לדרך!* 🔥\n🏟️ {t1_name} 🆚 {t2_name}")
                    sent_states[gid] = "STARTED"

                # 2. עדכון כל 10 דקות (בכל חצי)
                if state == 'in' and display_clock.startswith("10:"):
                    # מפתח ייחודי כדי שלא ישלח פעמיים באותה דקה
                    clock_key = f"{gid}_clk_{period}"
                    if clock_key not in sent_states:
                        send_msg(f"⏰ *עדכון אמצע חצי ({display_clock}):*\n🏟️ {t1_name} 🆚 {t2_name}\n🔹 תוצאה: {score}")
                        sent_states[clock_key] = True

                # 3. מחצית + סטטיסטיקה
                if "half" in description or "end of 1st" in description:
                    if f"{gid}_half" not in sent_states:
                        stats = get_filtered_stats(gid)
                        send_msg(f"🏀 *מחצית: {t1_name} {score} {t2_name}* 🏀\n{stats}")
                        sent_states[f"{gid}_half"] = True

                # 4. סיום + סטטיסטיקה סופית
                if state == 'post' and f"{gid}_final" not in sent_states:
                    stats = get_filtered_stats(gid)
                    send_msg(f"🏁 *סיום: {t1_name} {score} {t2_name}* 🏁\n{stats}")
                    sent_states[f"{gid}_final"] = True

        except Exception as e:
            print(f"Error: {e}")
            
        time.sleep(30) # בדיקה כל 30 שניות כדי לתפוס את הדקה ה-10 בדיוק

if __name__ == "__main__":
    monitor_college_basketball()

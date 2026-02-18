import requests
import time
from datetime import datetime, timedelta
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
            bench = sorted(bench, key=lambda x: int(x['stats'][0]) if x['stats'][0].isdigit() else 0, reverse=True)[:3]
            for p in starters + bench:
                name = translate_heb(p['athlete']['displayName'])
                s = p['stats']
                prefix = "⭐️" if p.get('starter') else "👟"
                line = f"{prefix} {name}: {s[12]}נ' | {s[6]}ר' | {s[7]}א' | {s[8]}חט' | {s[9]}חס'"
                report += line + "\n"
        return report
    except: return "❌ שגיאה בשליפת נתונים"

def monitor_all_live_games():
    sent_states = {}
    print("🚀 בוט מכללות עלה ומבצע סריקה ראשונה...")
    send_msg("🔎 *מתחיל סריקת משחקים פעילים...*")

    while True:
        try:
            url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
            resp = requests.get(url, timeout=10).json()
            events = resp.get('events', [])
            
            print(f"found {len(events)} games in ESPN scoreboard")

            for ev in events:
                gid = ev['id']
                status_obj = ev['status']
                state = status_obj['type']['state'].lower() # הופך לאותיות קטנות ליתר ביטחון
                
                # הדפסה ללוג כדי שנראה מה קורה בזמן אמת
                t1_short = ev['competitions'][0]['competitors'][0]['team']['shortDisplayName']
                t2_short = ev['competitions'][0]['competitors'][1]['team']['shortDisplayName']
                print(f"Game {t1_short} vs {t2_short} | State: {state}")

                # שינוי התנאי: כל מה שלא 'pre' (כלומר התחיל או הסתיים) יקבל הודעה
                if state != 'pre' and gid not in sent_states:
                    t1_name = translate_heb(t1_short)
                    t2_name = translate_heb(t2_short)
                    send_msg(f"🔥 *המשחק יצא לדרך (או כבר רץ)!* 🔥\n🏟️ {t1_name} 🆚 {t2_name}")
                    sent_states[gid] = "STARTED"

                # בדיקת מחצית (גמיש יותר)
                description = status_obj['type']['description'].lower()
                if "half" in description or "end of 1st" in description:
                    if f"{gid}_half" not in sent_states:
                        score = f"{ev['competitions'][0]['competitors'][0]['score']} - {ev['competitions'][0]['competitors'][1]['score']}"
                        stats = get_filtered_stats(gid)
                        send_msg(f"🏀 *מחצית: {translate_heb(t1_short)} {score} {translate_heb(t2_short)}* 🏀\n{stats}")
                        sent_states[f"{gid}_half"] = True

        except Exception as e: 
            print(f"Error: {e}")
        
        time.sleep(30)

if __name__ == "__main__":
    monitor_all_live_games()

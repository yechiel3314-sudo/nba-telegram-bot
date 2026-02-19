import requests
import time
from deep_translator import GoogleTranslator

TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
MY_CHAT_ID = "-1003808107418"
translator = GoogleTranslator(source='en', target='iw')

def translate_heb(text):
    if not text: return ""
    try: return translator.translate(text)
    except: return text

def send_msg(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": MY_CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=15)
    except: pass

def run_final_test():
    send_msg("🔎 *מתחיל סריקת חירום:* בודק את כל מה שמופיע בשרתי ESPN כרגע...")
    try:
        # פנייה ללוח התוצאות
        url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
        resp = requests.get(url, timeout=10).json()
        
        events = resp.get('events', [])
        if not events:
            send_msg("❌ השרת מחזיר רשימה ריקה. אין משחקים בכלל ב-API.")
            return

        for ev in events:
            gid = ev['id']
            status = ev['status']['type']['description']
            t1_name = translate_heb(ev['competitions'][0]['competitors'][0]['team']['shortDisplayName'])
            t2_name = translate_heb(ev['competitions'][0]['competitors'][1]['team']['shortDisplayName'])
            score = f"{ev['competitions'][0]['competitors'][0]['score']} - {ev['competitions'][0]['competitors'][1]['score']}"
            
            # שליחת כל משחק שנמצא, בלי לסנן!
            msg = f"📌 *נמצא משחק:* {t1_name} 🆚 {t2_name}\n📊 תוצאה ב-API: {score}\n⏱️ סטטוס: {status}"
            send_msg(msg)
            time.sleep(1)

    except Exception as e:
        send_msg(f"❌ שגיאה טכנית: {str(e)}")

if __name__ == "__main__":
    run_final_test()

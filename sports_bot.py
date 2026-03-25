import asyncio
import schedule
import time
import requests
from telegram import Bot
from telegram.constants import ParseMode
from datetime import datetime, timedelta
import html
import traceback
from deep_translator import GoogleTranslator

# ==========================================
# הגדרות מערכת
# ==========================================
TOKEN = '8284141482:AAGG1vPtJrleAvl7kADMeufGbEydIq08ib0'
MY_CHAT_ID = '-1003820726077'

bot = Bot(token=TOKEN)
# הגדרת המתרגם מעברית לאנגלית
translator = GoogleTranslator(source='en', target='iw')

def log_step(message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [INFO]: {message}")

# ==========================================
# פונקציית תרגום (deep-translator)
# ==========================================
def translate_name(text):
    if not text: return text
    try:
        # תרגום מהיר ואמין
        return translator.translate(text)
    except:
        return text

# ==========================================
# שליפת תוצאות מ-ESPN
# ==========================================
def get_espn_scores(sport, league, display_title):
    log_step(f"סורק {display_title}...")
    date_str = datetime.now().strftime("%Y%m%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    
    results = []
    for d in [yesterday, date_str]:
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard?dates={d}"
        try:
            r = requests.get(url, timeout=15)
            data = r.json()
            for event in data.get("events", []):
                if not event['status']['type']['completed']: continue
                
                comp = event['competitions'][0]['competitors']
                h_en = comp[0]['team']['displayName']
                a_en = comp[1]['team']['displayName']
                h_score = int(comp[0]['score'])
                a_score = int(comp[1]['score'])

                # סינונים (ישראל / אינטר מיאמי)
                full_names = f"{h_en} {a_en}".lower()
                if "ישראל" in display_title and "israel" not in full_names: continue
                if league == "usa.1" and "inter miami" not in full_names: continue

                # תרגום שמות הקבוצות
                h_name = translate_name(h_en)
                a_name = translate_name(a_en)

                if h_score > a_score:
                    line = f"• {h_name} <b>מנצחת</b> {h_score}-{a_score} את {a_name}"
                elif a_score > h_score:
                    line = f"• {a_name} <b>מנצחת</b> {a_score}-{h_score} את {h_name}"
                else:
                    line = f"• {h_name} ו{a_name} נפרדו בתיקו {h_score}-{a_score}"
                
                if line not in results: results.append(line)
        except: continue
    return results

# ==========================================
# הפקת הדו"ח המלא
# ==========================================
async def send_daily_update():
    log_step("--- התחלת הפקת דו\"ח מלא ---")
    
    categories = [
        ("במשחקי ידידות ⚽", "soccer", "fifa.friendly"),
        ("במוקדמות מונדיאל 🌍", "soccer", "fifa.worldq"),
        ("בליגת האומות 🇪🇺", "soccer", "uefa.nations"),
        ("במוקדמות יורו 🇪🇺", "soccer", "uefa.euroq"),
        ("במוקדמות אליפות אפריקה 🌍", "soccer", "caf.nations.q"),
        ("בנבחרת ישראל הצעירה (U21) 🇮🇱", "soccer", "uefa.euro.u21.q"),
        ("בנבחרת ישראל נוער (U19) 🇮🇱", "soccer", "uefa.euro.u19"),
        ("בנבחרת ישראל נערים (U17) 🇮🇱", "soccer", "uefa.euro.u17"),
        ("בליגת העל 🇮🇱", "soccer", "isr.1"),
        ("בליגה הלאומית 🇮🇱", "soccer", "isr.2"),
        ("בליגה האנגלית 🏴󠁧󠁢󠁥󠁮󠁧󠁿", "soccer", "eng.1"),
        ("בליגה הספרדית 🇪🇸", "soccer", "esp.1"),
        ("בליגה האיטלקית 🇮🇹", "soccer", "ita.1"),
        ("בליגה הגרמנית 🇩🇪", "soccer", "ger.1"),
        ("בליגה הצרפתית 🇫🇷", "soccer", "fra.1"),
        ("בליגה ההולנדית 🇳🇱", "soccer", "ned.1"),
        ("בליגה הסעודית 🇸🇦", "soccer", "sau.1"),
        ("בליגת האלופות 🇪🇺", "soccer", "uefa.champions"),
        ("בליגת MLS 🇺🇸", "soccer", "usa.1"),
        ("ביורוליג 🏀", "basketball", "mens-euroleague"),
        ("ב-NBA 🏀", "basketball", "nba")
    ]

    report = ["<b>📊 סיכום תוצאות (24 שעות אחרונות):</b>\n"]
    
    for title, sport, league in categories:
        scores = get_espn_scores(sport, league, title)
        if scores:
            report.append(f"<b>{title}</b>")
            report.extend(scores)
            report.append("")

    final_msg = "\n".join(report) if len(report) > 1 else "📭 אין תוצאות חדשות."
    
    try:
        await bot.send_message(chat_id=MY_CHAT_ID, text=final_msg, parse_mode=ParseMode.HTML)
        log_step("הדו''ח נשלח בהצלחה!")
    except Exception as e:
        log_step(f"שגיאה בשליחה: {e}")

def run_scheduler():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(send_daily_update())
    loop.close()

schedule.every().day.at("00:00").do(run_scheduler)

log_step("הבוט עלה לאוויר ב-Railway!")
run_scheduler() # הרצה ראשונית

while True:
    schedule.run_pending()
    time.sleep(30)

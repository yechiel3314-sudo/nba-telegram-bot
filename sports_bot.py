import asyncio
import schedule
import time
import requests
from telegram import Bot
from telegram.constants import ParseMode
from datetime import datetime, timedelta
import html
import traceback
from googletrans import Translator

# ==========================================
# הגדרות מערכת
# ==========================================
TOKEN = '8284141482:AAGG1vPtJrleAvl7kADMeufGbEydIq08ib0'
MY_CHAT_ID = '-1003820726077'

bot = Bot(token=TOKEN)
translator = Translator()

# ==========================================
# מערכת לוגים מפורטת (Railway Logs)
# ==========================================
def log_step(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [INFO]: {message}")

def log_error(message, error=None):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    err_msg = f"[{timestamp}] [ERROR]: {message}"
    if error:
        err_msg += f" | Detail: {traceback.format_exc()}"
    print(err_msg)

# ==========================================
# פונקציית תרגום אוטומטית (Google Translate)
# ==========================================
def auto_translate(text):
    if not text: return text
    try:
        log_step(f"מנסה לתרגם: {text}")
        translation = translator.translate(text, dest='he')
        return translation.text
    except Exception as e:
        log_error(f"תרגום נכשל עבור {text}", e)
        return text 

# ==========================================
# שליחה בטוחה לטלגרם (Async 20.8)
# ==========================================
async def safe_send(text):
    if not text:
        log_step("אין תוכן למשלוח.")
        return

    MAX_LEN = 4000
    if len(text) > MAX_LEN: text = text[:MAX_LEN]
    
    safe_text = html.escape(text).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")

    for i in range(3):
        try:
            log_step(f"ניסיון שליחה לטלגרם ({i+1}/3)...")
            await bot.send_message(chat_id=MY_CHAT_ID, text=safe_text, parse_mode=ParseMode.HTML)
            log_step("ההודעה נשלחה בהצלחה!")
            return
        except Exception as e:
            log_error(f"ניסיון שליחה {i+1} נכשל", e)
            await asyncio.sleep(3)

# ==========================================
# שליפת תוצאות מ-ESPN
# ==========================================
def get_espn_scores(sport, league, title):
    log_step(f"סורק ליגה: {title}")
    now = datetime.now()
    yesterday = (now - timedelta(days=1)).strftime("%Y%m%d")
    today = now.strftime("%Y%m%d")

    results = []
    for date_str in [yesterday, today]:
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard?dates={date_str}"
        try:
            r = requests.get(url, timeout=20)
            data = r.json()
            events = data.get("events", [])
        except Exception as e:
            log_error(f"שגיאה בגישה ל-ESPN ({league})", e)
            continue

        for event in events:
            try:
                if not event['status']['type']['completed']: continue
                
                comp = event['competitions'][0]['competitors']
                h_en = comp[0]['team']['displayName']
                a_en = comp[1]['team']['displayName']

                # סינונים מיוחדים (ישראל / אינטר מיאמי)
                if "נבחרת ישראל" in title and "israel" not in f"{h_en} {a_en}".lower(): continue
                if league == "usa.1" and "Inter Miami" not in [h_en, a_en]: continue

                h_name = auto_translate(h_en)
                a_name = auto_translate(a_en)
                h_score = comp[0]['score']
                a_score = comp[1]['score']

                if int(h_score) > int(a_score):
                    line = f"{h_name} מנצחת {h_score} - {a_score} את {a_name}"
                elif int(a_score) > int(h_score):
                    line = f"{a_name} מנצחת {a_score} - {h_score} את {h_name}"
                else:
                    line = f"{h_name} ו{a_name} נפרדו בתיקו {h_score} - {a_score}"

                if line not in results: results.append(line)
            except: continue
    return results

# ==========================================
# הדו"ח המלא (כל הליגות שביקשת)
# ==========================================
async def send_daily_update():
    log_step("--- התחלת הפקת דו\"ח יומי ---")
    categories = [
        # נבחרות ומוקדמות
        ("במשחקי ידידות (נבחרות) ⚽", "soccer", "fifa.friendly"),
        ("במוקדמות מונדיאל 🌍", "soccer", "fifa.worldq"),
        ("בליגת האומות 🇪🇺", "soccer", "uefa.nations"),
        ("במוקדמות יורו 🇪🇺", "soccer", "uefa.euroq"),
        ("במוקדמות אליפות אפריקה 🌍", "soccer", "caf.nations.q"),
        # ישראל (כל הגילאים)
        ("בנבחרת ישראל הצעירה (U21) 🇮🇱", "soccer", "uefa.euro.u21.q"),
        ("בנבחרת ישראל נוער (U19) 🇮🇱", "soccer", "uefa.euro.u19"),
        ("בנבחרת ישראל נערים (U17) 🇮🇱", "soccer", "uefa.euro.u17"),
        # ליגות מקומיות ואירופאיות
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
        ("בליגת MLS (אינטר מיאמי) 🇺🇸", "soccer", "usa.1"),
        # כדורסל
        ("ביורוליג 🏀", "basketball", "mens-euroleague"),
        ("ב-NBA 🏀", "basketball", "nba")
    ]

    report = []
    for title, sport, league in categories:
        scores = get_espn_scores(sport, league, title)
        if scores:
            report.append(f"<b>{title}</b>")
            report.extend([f"• {s}" for s in scores])
            report.append("")

    final_msg = "\n".join(report) if report else "📭 אין תוצאות חדשות לדווח"
    await safe_send(final_msg)
    log_step("--- סיום הפקת דו\"ח ---")

def run_now():
    log_step("מפעיל סבב בדיקה אסינכרוני...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(send_daily_update())
    loop.close()

schedule.every().day.at("00:00").do(run_now)

log_step("הבוט עלה לאוויר ב-Railway!")
run_now() # הרצה ראשונית

while True:
    schedule.run_pending()
    time.sleep(30)

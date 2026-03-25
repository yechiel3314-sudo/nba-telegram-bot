import asyncio
import schedule
import time
import requests
from telegram import Bot
from telegram.constants import ParseMode
from datetime import datetime, timedelta
from deep_translator import GoogleTranslator

# ==========================================
# הגדרות מערכת
# ==========================================
TOKEN = '8284141482:AAGG1vPtJrleAvl7kADMeufGbEydIq08ib0'
MY_CHAT_ID = '-1003820726077'

bot = Bot(token=TOKEN)
translator = GoogleTranslator(source='en', target='iw')

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def translate_name(text):
    if not text: return text
    try:
        return translator.translate(text)
    except:
        return text

# ==========================================
# שליפת תוצאות
# ==========================================
def get_espn_scores(sport, league, display_title):
    log(f"בודק {display_title}...")
    now = datetime.now()
    dates = [(now - timedelta(days=1)).strftime("%Y%m%d"), now.strftime("%Y%m%d")]
    
    results = []
    for d in dates:
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard?dates={d}"
        try:
            data = requests.get(url, timeout=15).json()
            for event in data.get("events", []):
                if not event['status']['type']['completed']: continue
                
                comp = event['competitions'][0]['competitors']
                # זיהוי מנצחת
                t1_en = comp[0]['team']['displayName']
                t2_en = comp[1]['team']['displayName']
                s1 = int(comp[0]['score'])
                s2 = int(comp[1]['score'])

                # תרגום
                t1 = translate_name(t1_en)
                t2 = translate_name(t2_en)

                if s1 > s2:
                    line = f"• {t1} <b>מנצחת</b> {s1}-{s2} את {t2}"
                elif s2 > s1:
                    line = f"• {t2} <b>מנצחת</b> {s2}-{s1} את {t1}"
                else:
                    line = f"• {t1} ו{t2} נפרדו בתיקו {s1}-{s2}"
                
                if line not in results: results.append(line)
        except: continue
    return results

# ==========================================
# הדו"ח המלא
# ==========================================
async def send_daily_update():
    log("--- התחלת דו\"ח ---")
    
    # רשימה מורחבת הכוללת את כל המוקדמות והמסגרות האירופיות
    categories = [
        # מוקדמות וטורנירי נבחרות
        ("מוקדמות מונדיאל 🌍", "soccer", "fifa.worldq"),
        ("מוקדמות יורו 🇪🇺", "soccer", "uefa.euroq"),
        ("ליגת האומות 🇪🇺", "soccer", "uefa.nations"),
        ("מוקדמות קופה אמריקה 🌎", "soccer", "conmebol.worldq"),
        ("מוקדמות אליפות אפריקה 🌍", "soccer", "caf.nations.q"),
        ("משחקי ידידות ⚽", "soccer", "fifa.friendly"),
        # נבחרות ישראל
        ("נבחרת ישראל U21 🇮🇱", "soccer", "uefa.euro.u21.q"),
        ("נבחרת ישראל U19 🇮🇱", "soccer", "uefa.euro.u19"),
        ("נבחרת ישראל U17 🇮🇱", "soccer", "uefa.euro.u17"),
        # ליגות כדורגל
        ("ליגת העל 🇮🇱", "soccer", "isr.1"),
        ("הליגה הלאומית 🇮🇱", "soccer", "isr.2"),
        ("ליגת האלופות 🇪🇺", "soccer", "uefa.champions"),
        ("ליגה אנגלית 🏴󠁧󠁢󠁥󠁮󠁧󠁿", "soccer", "eng.1"),
        ("ליגה ספרדית 🇪🇸", "soccer", "esp.1"),
        ("ליגה איטלקית 🇮🇹", "soccer", "ita.1"),
        ("ליגה גרמנית 🇩🇪", "soccer", "ger.1"),
        ("ליגה צרפתית 🇫🇷", "soccer", "fra.1"),
        ("ליגה הולנדית 🇳🇱", "soccer", "ned.1"),
        ("אינטר מיאמי (MLS) 🇺🇸", "soccer", "usa.1"),
        # כדורסל אירופי
        ("יורוליג 🏀", "basketball", "mens-euroleague"),
        ("יורוקאפ 🏀", "basketball", "mens-eurocup"),
        ("ליגת האלופות בכדורסל 🏀", "basketball", "mens-basketball-champions-league"),
        ("הליגה הספרדית בכדורסל 🏀", "basketball", "esp.1")
    ]

    report = ["<b>📊 סיכום תוצאות (24 שעות):</b>\n"]
    
    for title, sport, league in categories:
        scores = get_espn_scores(sport, league, title)
        if scores:
            report.append(f"<b>ב{title}</b>") # הוספת "ב" לפני השם
            report.extend(scores)
            report.append("")

    final_msg = "\n".join(report) if len(report) > 1 else "📭 אין תוצאות חדשות."
    await bot.send_message(chat_id=MY_CHAT_ID, text=final_msg, parse_mode=ParseMode.HTML)
    log("דו''ח נשלח!")

def run_scheduler():
    asyncio.run(send_daily_update())

schedule.every().day.at("00:00").do(run_scheduler)
run_scheduler() # הרצה ראשונית

while True:
    schedule.run_pending()
    time.sleep(30)

import asyncio
import schedule
import time
import requests
from telegram import Bot
from telegram.constants import ParseMode
from datetime import datetime, timedelta
import html
import traceback

# ==========================================
# הגדרות מערכת (TOKEN ו-ID שלך)
# ==========================================
TOKEN = '8284141482:AAGG1vPtJrleAvl7kADMeufGbEydIq08ib0'
MY_CHAT_ID = '-1003820726077'

bot = Bot(token=TOKEN)

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
# שליחה בטוחה לטלגרם
# ==========================================
async def safe_send(text):
    if not text:
        log_step("אין תוכן למשלוח.")
        return

    # פיצול הודעות ארוכות (מגבלת טלגרם היא 4096 תווים)
    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
    else:
        parts = [text]

    for part in parts:
        try:
            log_step("שולח חלק מהדו''ח לטלגרם...")
            await bot.send_message(chat_id=MY_CHAT_ID, text=part, parse_mode=ParseMode.HTML)
            await asyncio.sleep(1) # מניעת הצפה
        except Exception as e:
            log_error("שגיאה בשליחת הודעה", e)

# ==========================================
# שליפת תוצאות מ-ESPN (ללא תרגום אוטומטי)
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
            r = requests.get(url, timeout=15)
            data = r.json()
            events = data.get("events", [])
        except Exception as e:
            log_error(f"שגיאה בגישה ל-ESPN עבור {league}", e)
            continue

        for event in events:
            try:
                if not event['status']['type']['completed']: continue
                
                comp = event['competitions'][0]['competitors']
                h_name = comp[0]['team']['displayName']
                a_name = comp[1]['team']['displayName']
                h_score = comp[0]['score']
                a_score = comp[1]['score']

                # סינונים מיוחדים (נבחרת ישראל / אינטר מיאמי)
                en_names = f"{h_name} {a_name}".lower()
                if "נבחרת ישראל" in title and "israel" not in en_names: continue
                if league == "usa.1" and "inter miami" not in en_names: continue

                line = f"{h_name} {h_score} - {a_score} {a_name}"
                if line not in results: results.append(line)
            except: continue
    return results

# ==========================================
# הדו"ח המלא (כל הליגות שביקשת)
# ==========================================
async def send_daily_update():
    log_step("--- התחלת הפקת דו\"ח יומי ---")
    
    # רשימת הליגות המלאה - מתורגמת ידנית
    categories = [
        ("⚽ משחקי ידידות (נבחרות)", "soccer", "fifa.friendly"),
        ("🌍 מוקדמות מונדיאל", "soccer", "fifa.worldq"),
        ("🇪🇺 ליגת האומות", "soccer", "uefa.nations"),
        ("🇪🇺 מוקדמות יורו", "soccer", "uefa.euroq"),
        ("🌍 מוקדמות אליפות אפריקה", "soccer", "caf.nations.q"),
        ("🇮🇱 נבחרת ישראל הצעירה (U21)", "soccer", "uefa.euro.u21.q"),
        ("🇮🇱 נבחרת ישראל נוער (U19)", "soccer", "uefa.euro.u19"),
        ("🇮🇱 נבחרת ישראל נערים (U17)", "soccer", "uefa.euro.u17"),
        ("🇮🇱 ליגת העל", "soccer", "isr.1"),
        ("🇮🇱 הליגה הלאומית", "soccer", "isr.2"),
        ("🏴󠁧󠁢󠁥󠁮󠁧󠁿 ליגה אנגלית (Premier League)", "soccer", "eng.1"),
        ("🇪🇸 ליגה ספרדית (LaLiga)", "soccer", "esp.1"),
        ("🇮🇹 ליגה איטלקית (Serie A)", "soccer", "ita.1"),
        ("🇩🇪 ליגה גרמנית (Bundesliga)", "soccer", "ger.1"),
        ("🇫🇷 ליגה צרפתית (Ligue 1)", "soccer", "fra.1"),
        ("🇳🇱 ליגה הולנדית (Eredivisie)", "soccer", "ned.1"),
        ("🇸🇦 ליגה סעודית", "soccer", "sau.1"),
        ("🇪🇺 ליגת האלופות", "soccer", "uefa.champions"),
        ("🇺🇸 ליגת MLS (אינטר מיאמי)", "soccer", "usa.1"),
        ("🏀 NBA", "basketball", "nba"),
        ("🏀 יורוליג", "basketball", "mens-euroleague")
    ]

    report = ["<b>📊 סיכום תוצאות אחרונות (24 שעות):</b>\n"]
    
    for title, sport, league in categories:
        scores = get_espn_scores(sport, league, title)
        if scores:
            report.append(f"<b>{title}</b>")
            for s in scores:
                report.append(f"• {s}")
            report.append("")

    final_msg = "\n".join(report) if len(report) > 1 else "📭 אין תוצאות חדשות לדווח כרגע."
    await safe_send(final_msg)
    log_step("--- סיום הפקת דו\"ח ---")

def run_scheduler():
    log_step("מריץ בדיקה עכשיו...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(send_daily_update())
    loop.close()

# תזמון לכל חצות
schedule.every().day.at("00:00").do(run_scheduler)

log_step("הבוט עלה לאוויר ב-Railway!")
run_scheduler() # הרצה ראשונית מיד עם ההפעלה

while True:
    schedule.run_pending()
    time.sleep(30)

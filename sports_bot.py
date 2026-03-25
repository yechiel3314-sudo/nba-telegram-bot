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
# לוגים מפורטים לכל שלב (Railway Logs)
# ==========================================
def log_step(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [STEP]: {message}")

def log_error(message, error=None):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    err_msg = f"[{timestamp}] [ERROR]: {message}"
    if error:
        err_msg += f" | Detail: {error}"
    print(err_msg)

# ==========================================
# פונקציית תרגום אוטומטית (Google Translate)
# ==========================================
def auto_translate(text):
    if not text:
        return text
    try:
        log_step(f"מתרגם טקסט: {text}")
        translation = translator.translate(text, dest='he')
        return translation.text
    except Exception as e:
        log_error(f"התרגום נכשל עבור '{text}'", e)
        return text 

# ==========================================
# שליחה בטוחה לטלגרם (Async)
# ==========================================
async def safe_send(text):
    if not text:
        log_step("אין תוכן למשלוח, מדלג על הודעה.")
        return

    MAX_LEN = 4000
    if len(text) > MAX_LEN:
        log_step("הודעה ארוכה מדי, מבצע חיתוך.")
        text = text[:MAX_LEN]

    safe_text = html.escape(text)
    safe_text = safe_text.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")

    for i in range(3):
        try:
            log_step(f"ניסיון שליחה לטלגרם ({i+1}/3)...")
            await bot.send_message(chat_id=MY_CHAT_ID, text=safe_text, parse_mode=ParseMode.HTML)
            log_step("ההודעה נשלחה בהצלחה לטלגרם!")
            return
        except Exception as e:
            log_error(f"ניסיון שליחה {i+1} נכשל", e)
            await asyncio.sleep(3)

# ==========================================
# שליפת תוצאות מ-ESPN
# ==========================================
def get_espn_scores(sport, league, title):
    log_step(f"מתחיל סריקה עבור: {title} ({league})")
    now = datetime.now()
    yesterday = (now - timedelta(days=1)).strftime("%Y%m%d")
    today = now.strftime("%Y%m%d")

    results = []
    for date_str in [yesterday, today]:
        log_step(f"בודק תאריך: {date_str} עבור {league}")
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard?dates={date_str}"
        
        try:
            r = requests.get(url, timeout=20)
            data = r.json()
            events = data.get("events", [])
            log_step(f"נמצאו {len(events)} משחקים במאגר עבור {league}")
        except Exception as e:
            log_error(f"שגיאה בשליפת נתונים מ-ESPN עבור {league}", e)
            continue

        for event in events:
            try:
                status = event['status']['type']['completed']
                if not status:
                    continue # מדלג על משחקים שלא הסתיימו

                comp = event['competitions'][0]['competitors']
                home = comp[0]
                away = comp[1]

                home_name_en = home['team']['displayName']
                away_name_en = away['team']['displayName']
                
                # סינונים מיוחדים
                if "נבחרת ישראל" in title:
                    if "israel" not in home_name_en.lower() and "israel" not in away_name_en.lower():
                        continue
                
                if league == "usa.1" and "Inter Miami" not in [home_name_en, away_name_en]:
                    continue

                log_step(f"מעבד תוצאה: {home_name_en} נגד {away_name_en}")
                
                # תרגום שמות הקבוצות
                home_team = auto_translate(home_name_en)
                away_team = auto_translate(away_name_en)

                h_score = int(home['score'])
                a_score = int(away['score'])

                if h_score > a_score:
                    line = f"{home_team} מנצחת {h_score} - {a_score} את {away_team}"
                elif a_score > h_score:
                    line = f"{away_team} מנצחת {a_score} - {h_score} את {home_team}"
                else:
                    line = f"{home_team} ו{away_team} נפרדו בתיקו {h_score} - {a_score}"

                if line not in results:
                    results.append(line)
            except Exception as e:
                log_error("שגיאה בעיבוד משחק ספציפי", e)
                continue
                
    return results

# ==========================================
# פונקציית הדו"ח המרכזית (כל הליגות)
# ==========================================
async def send_daily_update():
    log_step("--- מתחיל הפקת דו\"ח יומי מלא ---")
    
    categories = [
        # --- נבחרות וטורנירים בינלאומיים ---
        ("במשחקי ידידות (נבחרות) ⚽", "soccer", "fifa.friendly"),
        ("במוקדמות מונדיאל 🌍", "soccer", "fifa.worldq"),
        ("במונדיאל 🏆", "soccer", "fifa.world"),
        ("ביורו 🇪🇺", "soccer", "uefa.euro"),
        ("במוקדמות יורו 🇪🇺", "soccer", "uefa.euroq"),
        ("בליגת האומות 🇪🇺", "soccer", "uefa.nations"),
        ("במוקדמות אליפות אפריקה 🌍", "soccer", "caf.nations.q"),
        ("באליפות אפריקה 🌍", "soccer", "caf.nations"),
        ("בקופה אמריקה 🌎", "soccer", "conmebol.america"),
        ("במוקדמות קופה אמריקה 🌎", "soccer", "conmebol.america.q"),
        ("בגביע אסיה 🌏", "soccer", "afc.asian.cup"),
        ("במוקדמות גביע אסיה 🌏", "soccer", "afc.asian.cup.q"),
        ("בגביע הזהב (CONCACAF) 🌎", "soccer", "concacaf.gold"),
        ("בליגת האומות (CONCACAF) 🌎", "soccer", "concacaf.nations"),

        # --- נבחרות ישראל ---
        ("בנבחרת ישראל הצעירה (U21) 🇮🇱", "soccer", "uefa.euro.u21.q"),
        ("בנבחרת ישראל נוער (U19) 🇮🇱", "soccer", "uefa.euro.u19"),
        ("בנבחרת ישראל נערים (U17) 🇮🇱", "soccer", "uefa.euro.u17"),

        # --- הליגות הגדולות והנוספות שביקשת ---
        ("בליגת העל 🇮🇱", "soccer", "isr.1"),
        ("בליגה הלאומית 🇮🇱", "soccer", "isr.2"),
        ("בליגה האנגלית 🏴󠁧󠁢󠁥󠁮󠁧󠁿", "soccer", "eng.1"),
        ("בליגה הספרדית 🇪🇸", "soccer", "esp.1"),
        ("בליגה האיטלקית 🇮🇹", "soccer", "ita.1"),
        ("בליגה הגרמנית 🇩🇪", "soccer", "ger.1"),
        ("בליגה הצרפתית 🇫🇷", "soccer", "fra.1"),
        ("בליגה ההולנדית 🇳🇱", "soccer", "ned.1"),
        ("בליגה הסעודית 🇸🇦", "soccer", "sau.1"),
        ("בליגה הבלגית 🇧🇪", "soccer", "bel.1"),
        ("בליגה הפורטוגלית 🇵🇹", "soccer", "por.1"),

        # --- גביעים אירופיים ---
        ("בליגת האלופות 🇪🇺", "soccer", "uefa.champions"),
        ("בליגה האירופית 🇪🇺", "soccer", "uefa.europa"),
        ("בליגת הקונפרנס 🇪🇺", "soccer", "uefa.europa.conf"),
        ("בליגת MLS (אינטר מיאמי) 🇺🇸", "soccer", "usa.1"),

        # --- כדורסל ---
        ("ביורוליג 🏀", "basketball", "mens-euroleague"),
        ("ביורוקאפ 🏀", "basketball", "eurocup"),
        ("בליגת האלופות של פיב\"א 🏀", "basketball", "mens-champions-league"),
        ("ב-NBA 🏀", "basketball", "nba")
    ]

    report = []
    for title, sport, league in categories:
        try:
            scores = get_espn_scores(sport, league, title)
            if scores:
                report.append(f"<b>{title}</b>")
                for s in scores:
                    report.append(f"• {s}")
                report.append("")
        except Exception as e:
            log_error(f"נכשלה סריקת קטגוריה: {title}", e)

    msg = "\n".join(report) if report else "📭 אין משחקים ב-24 שעות האחרונות"
    await safe_send(msg)
    log_step("--- סיום הפקת דו\"ח ---")

# ==========================================
# ניהול לולאה ראשית ותזמון
# ==========================================
def run_now():
    log_step("מריץ עדכון ידני/מתוזמן...")
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(send_daily_update())
        loop.close()
    except Exception as e:
        log_error("קריסה בלולאת ההרצה", e)

# תזמון לחצות
schedule.every().day.at("00:00").do(run_now)

log_step("הבוט עלה לאוויר ב-Railway!")
log_step(f"גרסת ספריית טלגרם: 20.8")

# הרצה ראשונה מיד עם הפעלת השרת
run_now()

while True:
    schedule.run_pending()
    time.sleep(15)

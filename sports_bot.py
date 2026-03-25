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
# הגדרות
# ==========================================
TOKEN = '8284141482:AAGG1vPtJrleAvl7kADMeufGbEydIq08ib0'
MY_CHAT_ID = '-1003820726077'

bot = Bot(token=TOKEN)
translator = Translator()

# ==========================================
# פונקציית תרגום אוטומטית (Google Translate)
# ==========================================
def auto_translate(text):
    try:
        translation = translator.translate(text, dest='he')
        return translation.text
    except Exception as e:
        print(f"[DEBUG] תרגום נכשל עבור {text}: {e}")
        return text 

# ==========================================
# שליחה בטוחה
# ==========================================
async def safe_send(text):
    MAX_LEN = 4000
    if len(text) > MAX_LEN:
        text = text[:MAX_LEN]

    safe_text = html.escape(text)
    safe_text = safe_text.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")

    for i in range(3):
        try:
            print(f"[LOG] ניסיון שליחה {i+1}")
            await bot.send_message(chat_id=MY_CHAT_ID, text=safe_text, parse_mode=ParseMode.HTML)
            return
        except Exception as e:
            print(f"[ERROR] שליחה נכשלה: {e}")
            await asyncio.sleep(2)

# ==========================================
# שליפת תוצאות
# ==========================================
def get_espn_scores(sport, league, title):
    print(f"[LOG] סורק: {title}")
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
        except:
            continue

        for event in events:
            try:
                comp = event['competitions'][0]['competitors']
                home = comp[0]
                away = comp[1]

                home_name_en = home['team']['displayName']
                away_name_en = away['team']['displayName']
                
                home_team = auto_translate(home_name_en)
                away_team = auto_translate(away_name_en)

                status = event['status']['type']['completed']
                if not status: continue

                if "נבחרת ישראל" in title:
                    if "israel" not in home_name_en.lower() and "israel" not in away_name_en.lower():
                        continue
                    if "women" in home_name_en.lower() or "women" in away_name_en.lower():
                        continue

                if league == "usa.1" and "Inter Miami" not in [home_name_en, away_name_en]:
                    continue

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
            except:
                continue
    return results

# ==========================================
# דו"ח יומי - כל הליגות והנבחרות (27 קטגוריות)
# ==========================================
async def send_daily_update():
    categories = [
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
        ("בנבחרת ישראל הצעירה (U21) 🇮🇱", "soccer", "uefa.euro.u21.q"),
        ("בנבחרת ישראל נוער (U19) 🇮🇱", "soccer", "uefa.euro.u19"),
        ("בנבחרת ישראל נערים (U17) 🇮🇱", "soccer", "uefa.euro.u17"),
        ("בליגת העל 🇮🇱", "soccer", "isr.1"),
        ("בליגה הלאומית 🇮🇱", "soccer", "isr.2"),
        ("בליגה האנגלית 🏴󠁧󠁢󠁥󠁮󠁧󠁿", "soccer", "eng.1"),
        ("בליגה הספרדית 🇪🇸", "soccer", "esp.1"),
        ("בליגה האיטלקית 🇮🇹", "soccer", "ita.1"),
        ("בליגת האלופות 🇪🇺", "soccer", "uefa.champions"),
        ("בליגת MLS (אינטר מיאמי) 🇺🇸", "soccer", "usa.1"),
        ("ביורוליג 🏀", "basketball", "mens-euroleague"),
        ("ביורוקאפ 🏀", "basketball", "eurocup"),
        ("בליגת האלופות של פיב\"א 🏀", "basketball", "mens-champions-league")
    ]

    report = []
    for title, sport, league in categories:
        scores = get_espn_scores(sport, league, title)
        if scores:
            report.append(f"<b>{title}</b>")
            for s in scores: report.append(f"• {s}")
            report.append("")

    msg = "\n".join(report) if report else "📭 אין משחקים ב-24 שעות האחרונות"
    await safe_send(msg)

def run_now():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(send_daily_update())

schedule.every().day.at("00:00").do(run_now)
print("🚀 הבוט מעודכן ורץ (כל הליגות + גרסה 20.8)...")
run_now()

while True:
    schedule.run_pending()
    time.sleep(15)

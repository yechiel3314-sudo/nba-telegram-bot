import asyncio
import schedule
import time
import requests
from telegram import Bot
from telegram.constants import ParseMode
from datetime import datetime, timedelta
from deep_translator import GoogleTranslator
from hebcal.hebrew_date import HebrewDate

# ==========================================
# הגדרות מערכת
# ==========================================
TOKEN = '8284141482:AAGG1vPtJrleAvl7kADMeufGbEydIq08ib0'
MY_CHAT_ID = '-1003820726077'
bot = Bot(token=TOKEN)
translator = GoogleTranslator(source='en', target='iw')

def get_clean_name(en_name):
    try:
        translated = translator.translate(en_name)
        to_remove = ["הרפובליקה של", "רפובליקת", "פדרציית", "מדינת", "איי", "הדמוקרטית"]
        for word in to_remove:
            translated = translated.replace(word, "")
        return translated.strip()
    except:
        return en_name

def get_formatted_date_header():
    # מכיוון שהבוט רץ אחרי 12 בלילה, אנחנו רוצים את התאריך של "אתמול"
    target_date = datetime.now() - timedelta(days=1)
    
    # יום בשבוע
    days_heb = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
    day_name = days_heb[target_date.weekday()]
    
    # תאריך לועזי
    luezi_date = target_date.strftime("%d/%m/%Y")
    
    # תאריך עברי
    heb_date_obj = HebrewDate(target_date.year, target_date.month, target_date.day)
    heb_date_str = heb_date_obj.hebrew_date_string()
    
    return f"📊 <b>תוצאות ליום {day_name}</b>\nתאריך עברי: {heb_date_str}\nתאריך לועזי: {luezi_date}\n"

def get_scores(sport, league, title):
    now = datetime.now()
    # בודקים תוצאות של אתמול והיום
    dates = [(now - timedelta(days=1)).strftime("%Y%m%d"), now.strftime("%Y%m%d")]
    results = []
    
    for d in dates:
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard?dates={d}"
        try:
            r = requests.get(url, timeout=10)
            data = r.json()
            for event in data.get("events", []):
                if not event['status']['type']['completed']: continue
                
                comp = event['competitions'][0]['competitors']
                s1, s2 = int(comp[0]['score']), int(comp[1]['score'])
                t1_en, t2_en = comp[0]['team']['displayName'], comp[1]['team']['displayName']

                # --- סינונים ספציפיים שביקשת ---
                # אינטר מיאמי
                if league == "usa.1" and "Inter Miami" not in [t1_en, t2_en]: continue
                # הפועל חולון בליגת האלופות
                if league == "mens-basketball-champions-league" and "Hapoel Holon" not in [t1_en, t2_en]: continue
                
                t1 = get_clean_name(t1_en)
                t2 = get_clean_name(t2_en)

                if s1 > s2:
                    line = f"• {t1} <b>מנצחת</b> {s1}-{s2} את {t2}"
                elif s2 > s1:
                    line = f"• {t2} <b>מנצחת</b> {s2}-{s1} את {t1}"
                else:
                    line = f"• {t1} ו-{t2} נפרדו בתיקו {s1}-{s2}"
                
                if line not in results: results.append(line)
        except: continue
    return results

async def send_daily_update():
    header = get_formatted_date_header()
    
    categories = [
        # כדורגל
        ("ליגה אנגלית 🏴󠁧󠁢󠁥󠁮󠁧󠁿", "soccer", "eng.1"),
        ("ליגה ספרדית 🇪🇸", "soccer", "esp.1"),
        ("ליגה איטלקית 🇮🇹", "soccer", "ita.1"),
        ("ליגה גרמנית 🇩🇪", "soccer", "ger.1"),
        ("ליגה צרפתית 🇫🇷", "soccer", "fra.1"),
        ("ליגה הולנדית 🇳🇱", "soccer", "ned.1"),
        ("ליגה סעודית 🇸🇦", "soccer", "sau.1"),
        ("אינטר מיאמי (MLS) 🇺🇸", "soccer", "usa.1"),
        ("ליגת העל 🇮🇱", "soccer", "isr.1"),
        ("ליגת האלופות 🇪🇺", "soccer", "uefa.champions"),
        ("הליגה האירופית 🇪🇺", "soccer", "uefa.europa"),
        ("קונפרנס ליג 🇪🇺", "soccer", "uefa.conf"),
        # נבחרות ומוקדמות
        ("מוקדמות מונדיאל ופלייאוף 🌍", "soccer", "fifa.worldq"),
        ("מוקדמות יורו ופלייאוף 🇪🇺", "soccer", "uefa.euroq"),
        ("ליגת האומות 🇪🇺", "soccer", "uefa.nations"),
        ("מוקדמות אליפות אפריקה 🌍", "soccer", "caf.nations.q"),
        ("קופה אמריקה 🌎", "soccer", "conmebol.worldq"),
        ("ישראל הצעירה (U21) 🇮🇱", "soccer", "uefa.euro.u21.q"),
        # כדורסל
        ("יורוליג 🏀", "basketball", "mens-euroleague"),
        ("הפועל חולון (BCL) 🏀", "basketball", "mens-basketball-champions-league"),
        ("ליגה ספרדית בכדורסל 🏀", "basketball", "esp.1")
    ]

    report = [header]
    for name, sport, league in categories:
        scores = get_scores(sport, league, name)
        if scores:
            report.append(f"<b>ב{name}</b>")
            report.extend(scores)
            report.append("")

    if len(report) > 1:
        await bot.send_message(chat_id=MY_CHAT_ID, text="\n".join(report), parse_mode=ParseMode.HTML)

def run():
    asyncio.run(send_daily_update())

# תזמון לחצות
schedule.every().day.at("00:01").do(run)

print("הבוט פעיל ובודק תזמון...")
while True:
    schedule.run_pending()
    time.sleep(15) # בדיקת לוח זמנים כל 15 שניות

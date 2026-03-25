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

# פונקציה לניקוי שמות וקבלת תרגום קצר ותקין
def get_clean_name(en_name):
    try:
        # תרגום בסיסי
        translated = translator.translate(en_name)
        # הסרת מילים מיותרות שגורמות לשמות להיראות רע
        bad_words = ["הרפובליקה של", "רפובליקת", "הבתולה של ארצות הברית", "פדרציית"]
        for word in bad_words:
            translated = translated.replace(word, "")
        
        # תיקונים ספציפיים לשמות נפוצים שנוטים להשתבש
        fixes = {"קירגיזסטן": "קירגיזסטן", "סמואה האמריקאית": "סמואה האמריקנית"}
        return fixes.get(translated.strip(), translated.strip())
    except:
        return en_name

def get_espn_scores(sport, league, title):
    now = datetime.now()
    dates = [(now - timedelta(days=1)).strftime("%Y%m%d"), now.strftime("%Y%m%d")]
    results = []
    
    for d in dates:
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard?dates={d}"
        try:
            r = requests.get(url, timeout=15)
            data = r.json()
            for event in data.get("events", []):
                if not event['status']['type']['completed']: continue
                
                comp = event['competitions'][0]['competitors']
                s1, s2 = int(comp[0]['score']), int(comp[1]['score'])
                t1_en, t2_en = comp[0]['team']['displayName'], comp[1]['team']['displayName']

                # סינון לאינטר מיאמי ב-MLS
                if league == "usa.1" and "Inter Miami" not in [t1_en, t2_en]: continue
                
                # תרגום שמות נקי
                t1 = get_clean_name(t1_en)
                t2 = get_clean_name(t2_en)

                if s1 > s2:
                    line = f"• {t1} <b>מנצחת</b> {s1}-{s2} את {t2}"
                elif s2 > s1:
                    line = f"• {t2} <b>מנצחת</b> {s2}-{s1} את {t1}"
                else:
                    line = f"• {t1} ו-{t2} תיקו {s1}-{s2}"
                
                if line not in results: results.append(line)
        except: continue
    return results

async def send_daily_update():
    # כל הליגות שביקשת במקום אחד
    categories = [
        # ליגות בכירות
        ("ליגה אנגלית 🏴󠁧󠁢󠁥󠁮󠁧󠁿", "soccer", "eng.1"),
        ("ליגה ספרדית 🇪🇸", "soccer", "esp.1"),
        ("ליגה איטלקית 🇮🇹", "soccer", "ita.1"),
        ("ליגה גרמנית 🇩🇪", "soccer", "ger.1"),
        ("ליגה צרפתית 🇫🇷", "soccer", "fra.1"),
        ("ליגה הולנדית 🇳🇱", "soccer", "ned.1"),
        ("ליגה סעודית 🇸🇦", "soccer", "sau.1"),
        ("אינטר מיאמי (MLS) 🇺🇸", "soccer", "usa.1"),
        ("ליגת העל 🇮🇱", "soccer", "isr.1"),
        # מפעלים אירופיים
        ("ליגת האלופות 🇪🇺", "soccer", "uefa.champions"),
        ("הליגה האירופית 🇪🇺", "soccer", "uefa.europa"),
        ("קונפרנס ליג 🇪🇺", "soccer", "uefa.conf"),
        # נבחרות ומוקדמות
        ("מוקדמות מונדיאל 🌍", "soccer", "fifa.worldq"),
        ("מוקדמות יורו 🇪🇺", "soccer", "uefa.euroq"),
        ("ליגת האומות 🇪🇺", "soccer", "uefa.nations"),
        ("מוקדמות אליפות אפריקה 🌍", "soccer", "caf.nations.q"),
        ("משחקי ידידות ⚽", "soccer", "fifa.friendly"),
        ("ישראל הצעירה (U21) 🇮🇱", "soccer", "uefa.euro.u21.q"),
        ("ישראל נוער (U19) 🇮🇱", "soccer", "uefa.euro.u19"),
        # כדורסל אירופי
        ("יורוליג 🏀", "basketball", "mens-euroleague"),
        ("יורוקאפ 🏀", "basketball", "mens-eurocup")
    ]

    report = ["<b>📊 סיכום תוצאות אחרונות:</b>\n"]
    for name, sport, league in categories:
        scores = get_espn_scores(sport, league, name)
        if scores:
            report.append(f"<b>ב{name}</b>")
            report.extend(scores)
            report.append("")

    if len(report) > 1:
        await bot.send_message(chat_id=MY_CHAT_ID, text="\n".join(report), parse_mode=ParseMode.HTML)

def run():
    asyncio.run(send_daily_update())

schedule.every().day.at("00:00").do(run)
run() # הרצה ראשונית

while True:
    schedule.run_pending()
    time.sleep(30)

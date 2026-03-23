import asyncio
import schedule
import time
import requests
from telegram import Bot
from datetime import datetime, timedelta

# הגדרות הבוט והצ'אט שלך
TOKEN = '8284141482:AAGG1VPtJrLeAvl7kADMeufGbEYdIq08ib0'
MY_CHAT_ID = '-1003714393119' 

bot = Bot(token=TOKEN)

def get_espn_scores(sport, league, title):
    print(f"[LOG] בודק תוצאות עבור: {title} ({league})")
    
    # סורק את 24 השעות האחרונות כדי למנוע פספוסים של חצות/שעות שרת
    now = datetime.now()
    yesterday = (now - timedelta(days=1)).strftime("%Y%m%d")
    today = now.strftime("%Y%m%d")
    
    results = []
    
    # בודק גם את אתמול וגם את היום (למקרה שהמשחק נגמר אחרי חצות)
    for date_str in [yesterday, today]:
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard?dates={date_str}"
        try:
            response = requests.get(url, timeout=15)
            data = response.json()
            events = data.get('events', [])
            
            for event in events:
                home_team = event['competitions'][0]['competitors'][0]['team']['displayName']
                away_team = event['competitions'][0]['competitors'][1]['team']['displayName']
                home_score = event['competitions'][0]['competitors'][0]['score']
                away_score = event['competitions'][0]['competitors'][1]['score']
                status = event['status']['type']['completed']

                # לוקח רק משחקים שהסתיימו
                if not status: continue

                # פילטר לאינטר מיאמי ב-MLS
                if league == "usa.1" and "Inter Miami" not in [home_team, away_team]:
                    continue

                h_s, a_s = int(home_score), int(away_score)
                line = ""
                if h_s > a_s:
                    line = f"{home_team} מנצחת {h_s} - {a_s} את {away_team}"
                elif a_s > h_s:
                    line = f"{away_team} מנצחת {a_s} - {h_s} את {home_team}"
                else:
                    line = f"{home_team} ו{away_team} נפרדות בתיקו {h_s} - {a_s}"
                
                if line not in results: # מונע כפילויות בין אתמול להיום
                    results.append(line)
        except Exception as e:
            print(f"[ERROR] שגיאה במשיכת {title}: {e}")
            
    return results

async def send_daily_update():
    print(f"[LOG] מתחיל הכנת דו\"ח יומי... שעה נוכחית: {datetime.now().strftime('%H:%M:%S')}")
    
    # הרשימה המלאה לפי הסדר שביקשת
    categories = [
        ("בליגת העל 🇮🇱", "soccer", "isr.1"),
        ("בליגה הלאומית 🇮🇱", "soccer", "isr.2"),
        ("בליגת האלופות 🇪🇺", "soccer", "uefa.champions"),
        ("בליגה האירופית 🇪🇺", "soccer", "uefa.europa"),
        ("בקונפרנס ליג 🇪🇺", "soccer", "uefa.europa.conf"),
        ("בליגה הספרדית 🇪🇸", "soccer", "esp.1"),
        ("בליגה האנגלית 🏴󠁧󠁢󠁥󠁮󠁧󠁿", "soccer", "eng.1"),
        ("בליגה האיטלקית 🇮🇹", "soccer", "ita.1"),
        ("בליגה הגרמנית 🇩🇪", "soccer", "ger.1"),
        ("בליגה הצרפתית 🇫🇷", "soccer", "fra.1"),
        ("בליגה ההולנדית 🇳🇱", "soccer", "ned.1"),
        ("בליגה הסעודית 🇸🇦", "soccer", "ksa.1"),
        ("בליגת ה-MLS באינטר מיאמי 🇺🇸", "soccer", "usa.1"),
        ("בנבחרות כדורגל ⚽", "soccer", "fifa.friendly"),
        ("ביורוליג 🏀", "basketball", "euroleague"),
        ("ביורוקאפ 🏀", "basketball", "eurocup")
    ]

    report = []
    for title, sport, league_code in categories:
        scores = get_espn_scores(sport, league_code, title)
        if scores:
            report.append(f"### {title}")
            for s in scores:
                report.append(f"* {s}")
            report.append("")

    if report:
        final_message = "\n".join(report)
        try:
            print("[LOG] מנסה לשלוח הודעה לטלגרם...")
            await bot.send_message(chat_id=MY_CHAT_ID, text=final_message, parse_mode='Markdown')
            print("[LOG] ההודעה נשלחה בהצלחה!")
        except Exception as e:
            print(f"[ERROR] שגיאה בשליחה לטלגרם: {e}")
    else:
        print("[LOG] לא נמצאו משחקים שהסתיימו ב-24 השעות האחרונות.")
        # אפשר להוסיף שליחת הודעת "אין משחקים" לבדיקה:
        # await bot.send_message(chat_id=MY_CHAT_ID, text="בדיקה: הבוט רץ אך לא נמצאו משחקים.")

def run_now():
    print("[LOG] מריץ בדיקה מיידית של הבוט...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(send_daily_update())

# תזמון קבוע
schedule.every().day.at("01:20").do(run_now)

print("--- הבוט @MyTestNbaBot עלה לאוויר ב-Railway ---")

# שלב 1: הרצה מיידית ברגע שהקוד עולה
run_now()

# שלב 2: כניסה ללופ המתנה
print("[LOG] נכנס למצב המתנה לתזמון היומי (01:20)...")
while True:
    schedule.run_pending()
    time.sleep(30)

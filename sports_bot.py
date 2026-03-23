import asyncio
import schedule
import time
import requests
from telegram import Bot
from datetime import datetime, timedelta

# פרטי הבוט והצ'אט שלך
TOKEN = '8284141482:AAGG1VPtJrLeAvl7kADMeufGbEYdIq08ib0'
MY_CHAT_ID = '-1003714393119' 

bot = Bot(token=TOKEN)

def get_espn_scores(sport, league):
    # מושך תוצאות של אתמול (היום שהסתיים)
    date_str = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard?dates={date_str}"
    
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        events = data.get('events', [])
        
        results = []
        for event in events:
            home_team = event['competitions'][0]['competitors'][0]['team']['displayName']
            away_team = event['competitions'][0]['competitors'][1]['team']['displayName']
            home_score = event['competitions'][0]['competitors'][0]['score']
            away_score = event['competitions'][0]['competitors'][1]['score']
            status = event['status']['type']['completed']

            if not status: continue

            # פילטר מיוחד לאינטר מיאמי בתוך ה-MLS
            if league == "usa.1" and "Inter Miami" not in [home_team, away_team]:
                continue

            h_s = int(home_score)
            a_s = int(away_score)

            if h_s > a_s:
                results.append(f"{home_team} מנצחת {h_s} - {a_s} את {away_team}")
            elif a_s > h_s:
                results.append(f"{away_team} מנצחת {a_s} - {h_s} את {home_team}")
            else:
                results.append(f"{home_team} ו{away_team} נפרדות בתיקו {h_s} - {a_s}")
        
        return results
    except:
        return []

async def send_daily_update():
    print(f"מתחיל הפצה אוטומטית... {datetime.now().strftime('%H:%M:%S')}")
    
    # הסדר המדויק שביקשת
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
        ("בנבחרות כדורגל ⚽", "soccer", "fifa.friendly"), # דוגמה למסגרת נבחרות
        ("ביורוליג 🏀", "basketball", "euroleague"),
        ("ביורוקאפ 🏀", "basketball", "eurocup")
    ]

    report = []
    for title, sport, league_code in categories:
        scores = get_espn_scores(sport, league_code)
        if scores:
            report.append(f"### {title}")
            for s in scores:
                report.append(f"* {s}")
            report.append("")

    if report:
        message = "\n".join(report)
        try:
            await bot.send_message(chat_id=MY_CHAT_ID, text=message)
            print("העדכון נשלח לקבוצה!")
        except Exception as e:
            print(f"שגיאה בשליחה: {e}")

def run_scheduler():
    asyncio.run(send_daily_update())

# תזמון מדויק ל-01:02
schedule.every().day.at("01:04").do(run_scheduler)

print(f"הבוט @MyTestNbaBot רץ. העדכון הבא ב-01:02 ל-ID: {MY_CHAT_ID}")

while True:
    schedule.run_pending()
    time.sleep(30)

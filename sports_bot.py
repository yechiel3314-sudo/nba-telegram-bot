import asyncio
import schedule
import time
import requests
from telegram import Bot
from datetime import datetime, timedelta
import html
import traceback

# ==========================================
# הגדרות
# ==========================================
TOKEN = '8284141482:AAGG1VPtJrLeAvl7kADMeufGbEYdIq08ib0'
MY_CHAT_ID = '-1003714393119'

bot = Bot(token=TOKEN)

# ==========================================
# שליחה בטוחה
# ==========================================
async def safe_send(text):
    MAX_LEN = 4000

    if len(text) > MAX_LEN:
        print("[WARN] הודעה ארוכה מדי - חותך")
        text = text[:MAX_LEN]

    safe_text = html.escape(text)
    safe_text = safe_text.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")

    for i in range(3):
        try:
            print(f"[LOG] ניסיון שליחה {i+1}")
            await bot.send_message(chat_id=MY_CHAT_ID, text=safe_text, parse_mode='HTML')
            print("[SUCCESS] נשלח!")
            return
        except Exception as e:
            print(f"[ERROR] ניסיון {i+1} נכשל: {e}")
            await asyncio.sleep(2)

    print("[FATAL] נכשל לשלוח הודעה")

# ==========================================
# שליפת תוצאות
# ==========================================
def get_espn_scores(sport, league, title):
    print(f"[LOG] בודק: {title}")

    now = datetime.now()
    yesterday = (now - timedelta(days=1)).strftime("%Y%m%d")
    today = now.strftime("%Y%m%d")

    results = []

    for date_str in [yesterday, today]:
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard?dates={date_str}"

        for attempt in range(3):
            try:
                r = requests.get(url, timeout=15)
                data = r.json()
                events = data.get("events", [])
                break
            except Exception as e:
                print(f"[ERROR] API ניסיון {attempt+1}: {e}")
                time.sleep(1)
        else:
            continue

        for event in events:
            try:
                comp = event['competitions'][0]['competitors']

                home = comp[0]
                away = comp[1]

                home_team = home['team']['displayName']
                away_team = away['team']['displayName']

                status = event['status']['type']['completed']
                if not status:
                    continue

                # =========================
                # 🇮🇱 נבחרת ישראל בלבד (ליגות נבחרות)
                # =========================
                if "נבחרת ישראל" in title:
                    teams_text = f"{home_team} {away_team}".lower()

                    if "israel" not in teams_text:
                        continue

                    # סינון נשים
                    if "women" in teams_text or "w" in teams_text:
                        continue

                # =========================
                # אינטר מיאמי
                # =========================
                if league == "usa.1" and "Inter Miami" not in [home_team, away_team]:
                    continue

                home_score = int(home['score'])
                away_score = int(away['score'])

                if home_score > away_score:
                    line = f"{home_team} מנצחת {home_score} - {away_score} את {away_team}"
                elif away_score > home_score:
                    line = f"{away_team} מנצחת {away_score} - {home_score} את {home_team}"
                else:
                    line = f"{home_team} ו{away_team} נפרדות בתיקו {home_score} - {away_score}"

                if line not in results:
                    results.append(line)

            except Exception as e:
                print("[ERROR] בעיבוד משחק")
                print(traceback.format_exc())

    return results

# ==========================================
# דו"ח יומי
# ==========================================
async def send_daily_update():
    print(f"[LOG] מתחיל דו\"ח... {datetime.now().strftime('%H:%M:%S')}")

    categories = [
        ("בליגת העל 🇮🇱", "soccer", "isr.1"),
        ("בליגה הלאומית 🇮🇱", "soccer", "isr.2"),
        ("בליגת האלופות 🇪🇺", "soccer", "uefa.champions"),
        ("בליגה האירופית 🇪🇺", "soccer", "uefa.europa"),
        ("בקונפרנס ליג 🇪🇺", "soccer", "uefa.europa.conf"),
        ("בליגה הספרדית 🇪🇸", "soccer", "esp.1"),
        ("בליגה האנגלית 🏴", "soccer", "eng.1"),
        ("בליגה האיטלקית 🇮🇹", "soccer", "ita.1"),
        ("בליגה הגרמנית 🇩🇪", "soccer", "ger.1"),
        ("בליגה הצרפתית 🇫🇷", "soccer", "fra.1"),
        ("בליגה ההולנדית 🇳🇱", "soccer", "ned.1"),
        ("בליגה הסעודית 🇸🇦", "soccer", "ksa.1"),
        ("בליגת MLS (אינטר מיאמי בלבד) 🇺🇸", "soccer", "usa.1"),

        # 🇮🇱 נבחרות ישראל
        ("נבחרת ישראל 🇮🇱", "soccer", "fifa.friendly"),
        ("נבחרת ישראל 🇮🇱 מוקדמות מונדיאל", "soccer", "fifa.worldq"),
        ("נבחרת ישראל 🇮🇱 מוקדמות יורו", "soccer", "uefa.euroq"),
        ("נבחרת ישראל 🇮🇱 יורו", "soccer", "uefa.euro"),
        ("נבחרת ישראל 🇮🇱 ליגת האומות", "soccer", "uefa.nations"),

        # 🏀
        ("יורוליג 🏀", "basketball", "euroleague"),
        ("יורוקאפ 🏀", "basketball", "eurocup")
    ]

    report = []

    for title, sport, league in categories:
        scores = get_espn_scores(sport, league, title)
        if scores:
            report.append(f"<b>{title}</b>")
            for s in scores:
                report.append(f"• {s}")
            report.append("")

    if report:
        msg = "\n".join(report)
        await safe_send(msg)
    else:
        await safe_send("📭 אין משחקים ב-24 שעות האחרונות")

# ==========================================
# הרצה
# ==========================================
def run_now():
    print("[LOG] הרצה מיידית")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(send_daily_update())

# ==========================================
# תזמון
# ==========================================
schedule.every().day.at("00:00").do(run_now)

print("🚀 הבוט עלה לאוויר (גרסה מושלמת)")

run_now()

print("[LOG] ממתין...")
while True:
    schedule.run_pending()
    time.sleep(15)

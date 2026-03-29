import requests
import time
import re
import json
import os
from datetime import datetime, timedelta, timezone

# ==============================
# הגדרות
# ==============================
CHANNEL_ID = "UC0v-tlzsn0QZwJnkiaUSJVQ"
API_KEY = "AIzaSyAHEN7hSaTejSUH53CACsM5dzDANrvsR6U"

TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

DATA_FILE = "sent_videos.json"

# ==============================
# תרגום קבוצות
# ==============================
TEAM_TRANSLATIONS = {
    "Hawks": "אטלנטה הוקס",
    "Celtics": "בוסטון סלטיקס",
    "Nets": "ברוקלין נטס",
    "Hornets": "שארלוט הורנטס",
    "Bulls": "שיקגו בולס",
    "Cavaliers": "קליבלנד קאבלירס",
    "Mavericks": "דאלאס מאבריקס",
    "Nuggets": "דנבר נאגטס",
    "Pistons": "דטרויט פיסטונס",
    "Warriors": "גולדן סטייט ווריורס",
    "Rockets": "יוסטון רוקטס",
    "Pacers": "אינדיאנה פייסרס",
    "Clippers": "לוס אנג'לס קליפרס",
    "Lakers": "לוס אנג'לס לייקרס",
    "Grizzlies": "ממפיס גריזליס",
    "Heat": "מיאמי היט",
    "Bucks": "מילווקי באקס",
    "Timberwolves": "מינסוטה טימברוולבס",
    "Pelicans": "ניו אורלינס פליקנס",
    "Knicks": "ניו יורק ניקס",
    "Thunder": "אוקלהומה סיטי ת'אנדר",
    "Magic": "אורלנדו מג'יק",
    "76ers": "פילדלפיה 76",
    "Sixers": "פילדלפיה 76",
    "Suns": "פיניקס סאנס",
    "Blazers": "פורטלנד טרייל בלייזרס",
    "Kings": "סקרמנטו קינגס",
    "Spurs": "סן אנטוניו ספרס",
    "Raptors": "טורונטו ראפטורס",
    "Jazz": "יוטה ג'אז",
    "Wizards": "וושינגטון וויזארדס"
}

# ==============================
# כלים
# ==============================
def debug(msg):
    print(f"[DEBUG] {msg}", flush=True)

def now_utc():
    return datetime.now(timezone.utc)

# ==============================
# זיכרון
# ==============================
def load_sent():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_sent(sent):
    with open(DATA_FILE, "w") as f:
        json.dump(list(sent), f)

# ==============================
# חילוץ קבוצות
# ==============================
def extract_teams(title):
    match = re.search(r":\s*(.*?)\s*\d+,\s*(.*?)\s*\d+", title)

    if match:
        t1 = TEAM_TRANSLATIONS.get(match.group(1).strip())
        t2 = TEAM_TRANSLATIONS.get(match.group(2).strip())

        if t1 and t2:
            return t1, t2

    return None, None

# ==============================
# הודעה
# ==============================
def build_message(title):
    t1, t2 = extract_teams(title)

    if t1 and t2:
        return f"{t1} 🆚 {t2}"

    return "משחק NBA 🏀"

# ==============================
# שליחה
# ==============================
def send_video(text, url):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": f"{text}\n{url}"
            }
        )

        if r.status_code == 200:
            print("✅ נשלח")
        else:
            print("❌ שגיאה:", r.text)

    except Exception as e:
        print("❌ קריסה:", e)

# ==============================
# 🔥 YouTube API
# ==============================
def get_videos():
    try:
        url = "https://www.googleapis.com/youtube/v3/search"

        params = {
            "key": API_KEY,
            "channelId": CHANNEL_ID,
            "part": "snippet",
            "order": "date",
            "maxResults": 50
        }

        r = requests.get(url, params=params)
        data = r.json()

        videos = []

        for item in data.get("items", []):
            if item["id"]["kind"] != "youtube#video":
                continue

            vid = item["id"]["videoId"]
            title = item["snippet"]["title"]
            published = item["snippet"]["publishedAt"]

            published_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
            url = f"https://www.youtube.com/watch?v={vid}"

            videos.append((vid, title, url, published_dt))

        debug(f"Found {len(videos)} videos")
        return videos

    except Exception as e:
        print("❌ API ERROR:", e)
        return []

# ==============================
# FIRST RUN (24 שעות אחורה)
# ==============================
def first_run():
    print("🚀 FIRST RUN")

    sent = set()
    videos = get_videos()

    cutoff = now_utc() - timedelta(hours=24)
    recent = [v for v in videos if v[3] >= cutoff]

    debug(f"Recent videos: {len(recent)}")

    for vid, title, url, _ in recent:

        if "short" in title.lower():
            continue

        if "recap" not in title.lower() and "highlight" not in title.lower():
            continue

        msg = build_message(title)
        print("📤", msg)

        send_video(msg, url)

        sent.add(vid)
        time.sleep(20)

    save_sent(sent)

# ==============================
# LOOP
# ==============================
def loop():
    print("🤖 BOT STARTED")

    last_run_date = None

    while True:
        now = datetime.now()

        # ⏰ רק ב־09:30
        if now.hour == 9 and now.minute == 30:
            if last_run_date != now.date():
                print("🚀 09:30 RUN")

                sent = load_sent()
                videos = get_videos()

                cutoff = now_utc() - timedelta(hours=24)
                recent = [v for v in videos if v[3] >= cutoff]

                debug(f"Recent videos: {len(recent)}")

                for vid, title, url, _ in recent:

                    if "short" in title.lower():
                        continue

                    if "recap" not in title.lower() and "highlight" not in title.lower():
                        continue

                    if vid in sent:
                        continue

                    msg = build_message(title)
                    print("📤", msg)

                    send_video(msg, url)

                    sent.add(vid)
                    save_sent(sent)

                    time.sleep(20)

                last_run_date = now.date()

                # שלא ירוץ שוב באותה דקה
                time.sleep(60)

        # ⏳ בודק כל 20 שניות אם הגיע הזמן
        time.sleep(20)
# ==============================
# START
# ==============================
if __name__ == "__main__":
    if not os.path.exists(DATA_FILE):
        first_run()

    loop()

import requests
import time
import re
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

try:
    import yt_dlp
except ImportError:
    print("❌ yt_dlp לא מותקן!")
    exit(1)

# ==============================
# הגדרות
# ==============================
CHANNEL_ID = "UC0v-tlzsn0QZwJnkiaUSJVQ"
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

RSS_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
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
# ❗ סינון Shorts לפי duration
# ==============================
def is_short(url):
    try:
        ydl_opts = {
            'quiet': True,
            'skip_download': True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        duration = info.get("duration", 0)

        if duration and duration < 70:
            return True

        return False

    except:
        return False

# ==============================
# הורדה
# ==============================
def download_video(url, filename="video.mp4"):
    try:
        ydl_opts = {
            'format': 'best[height<=480]',
            'outtmpl': filename,
            'quiet': True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        return filename

    except Exception as e:
        print("❌ שגיאה בהורדה:", e)
        return None

# ==============================
# שליחה
# ==============================
def send_video(text, url):
    file_path = download_video(url)

    if not file_path:
        return

    try:
        with open(file_path, 'rb') as f:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo",
                data={
                    "chat_id": CHAT_ID,
                    "caption": text
                },
                files={"video": f}
            )

        if r.status_code != 200:
            print("❌ שגיאה בשליחה:", r.text)
        else:
            print("✅ נשלח בהצלחה")

    except Exception as e:
        print("❌ קריסה בשליחה:", e)

    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

# ==============================
# RSS
# ==============================
def get_videos():
    try:
        r = requests.get(RSS_URL)
        root = ET.fromstring(r.content)

        videos = []

        for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
            vid = entry.find("{http://www.youtube.com/xml/schemas/2015}videoId").text
            title = entry.find("{http://www.w3.org/2005/Atom}title").text
            published = entry.find("{http://www.w3.org/2005/Atom}published").text

            published_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
            url = f"https://www.youtube.com/watch?v={vid}"

            videos.append((vid, title, url, published_dt))

        debug(f"Found {len(videos)} videos")
        return videos

    except Exception as e:
        print("❌ שגיאה RSS:", e)
        return []

# ==============================
# FIRST RUN
# ==============================
def first_run():
    print("🚀 FIRST RUN (24H)")

    sent = set()
    videos = get_videos()

    cutoff = now_utc() - timedelta(hours=24)
    recent = [v for v in videos if v[3] >= cutoff]

    debug(f"Recent videos: {len(recent)}")

    for vid, title, url, _ in recent:

        # ❌ סינון Shorts לפי כותרת
        if "short" in title.lower():
            print("⏭️ דילוג SHORT (title)")
            continue

        # ❌ סינון לפי אורך
        if is_short(url):
            print("⏭️ דילוג SHORT (duration)")
            continue

        # ❌ רק משחקים
        if "recap" not in title.lower() and "highlight" not in title.lower():
            print("⏭️ לא משחק")
            continue

        msg = build_message(title)
        print("📤", msg)

        send_video(msg, url)
        sent.add(vid)

        time.sleep(10)

    save_sent(sent)

# ==============================
# LOOP
# ==============================
def loop():
    print("🤖 BOT STARTED")

    while True:
        try:
            sent = load_sent()
            videos = get_videos()

            new_videos = [v for v in videos if v[0] not in sent]
            debug(f"New videos: {len(new_videos)}")

            for vid, title, url, _ in new_videos:

                if "short" in title.lower():
                    print("⏭️ דילוג SHORT")
                    continue

                if is_short(url):
                    print("⏭️ דילוג SHORT (duration)")
                    continue

                if "recap" not in title.lower() and "highlight" not in title.lower():
                    print("⏭️ לא משחק")
                    continue

                msg = build_message(title)
                print("📤", msg)

                send_video(msg, url)
                sent.add(vid)
                save_sent(sent)

                time.sleep(10)

        except Exception as e:
            print("❌ LOOP ERROR:", e)

        time.sleep(120)

# ==============================
# START
# ==============================
if __name__ == "__main__":
    if not os.path.exists(DATA_FILE):
        first_run()

    loop()

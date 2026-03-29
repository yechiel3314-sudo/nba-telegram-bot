import requests
import time
import re
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import yt_dlp

# ==============================
# הגדרות
# ==============================
CHANNEL_ID = "UCV4xOVpbcV8SdueDCOxLXtQ"
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
# הורדת וידאו
# ==============================
def download_video(url, filename="video.mp4"):
    try:
        ydl_opts = {
            'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
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
# שליחת וידאו
# ==============================
def send_video(text, url):
    file_path = download_video(url)

    if not file_path:
        return

    size_mb = os.path.getsize(file_path) / (1024 * 1024)

    # אם גדול מדי → איכות נמוכה
    if size_mb > 50:
        print("⚠️ גדול מדי, מוריד איכות...")
        os.remove(file_path)

        try:
            ydl_opts = {
                'format': 'worst',
                'outtmpl': file_path,
                'quiet': True
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

        except Exception as e:
            print("❌ שגיאה בהורדה נמוכה:", e)
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

        return videos

    except Exception as e:
        print("❌ שגיאה RSS:", e)
        return []

# ==============================
# הרצה ראשונית (24 שעות)
# ==============================
def first_run():
    print("🚀 הרצה ראשונית")

    sent = set()
    videos = get_videos()

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    recent = [v for v in videos if v[3] >= cutoff]

    for vid, title, url, _ in recent:
        msg = build_message(title)

        print("📤", msg)
        send_video(msg, url)

        sent.add(vid)
        time.sleep(20)

    save_sent(sent)

# ==============================
# הרצה יומית (09:30)
# ==============================
def daily_run():
    print("📅 בדיקה יומית")

    sent = load_sent()
    videos = get_videos()

    new_videos = [v for v in videos if v[0] not in sent]

    for vid, title, url, _ in new_videos:
        msg = build_message(title)

        print("📤", msg)
        send_video(msg, url)

        sent.add(vid)
        save_sent(sent)

        time.sleep(20)

# ==============================
# לולאה
# ==============================
def main():
    if not os.path.exists(DATA_FILE):
        first_run()

    print("🤖 הבוט פועל...")

    last_run_date = None

    while True:
        now = datetime.now()

        if now.hour == 9 and now.minute == 30:
            if last_run_date != now.date():
                daily_run()
                last_run_date = now.date()
                time.sleep(60)

        time.sleep(20)

# ==============================
# START
# ==============================
if __name__ == "__main__":
    main()

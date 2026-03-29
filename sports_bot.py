import requests
import time
import re
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# ==============================
# הגדרות
# ==============================
CHANNEL_ID = "UCWJ2lWNubArHWmf3FIHbfcQ"
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

RSS_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
DATA_FILE = "sent_videos.json"

# ==============================
# תרגום קבוצות (בלי אנגלית!)
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
# חילוץ קבוצות מהכותרת
# ==============================
def extract_teams(title):
    match = re.search(r":\s*(.*?)\s*\d+,\s*(.*?)\s*\d+", title)

    if match:
        t1_raw = match.group(1).strip()
        t2_raw = match.group(2).strip()

        t1 = TEAM_TRANSLATIONS.get(t1_raw)
        t2 = TEAM_TRANSLATIONS.get(t2_raw)

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
# שליחה לטלגרם
# ==============================
def send_telegram(text, url):
    msg = f"{text}\n{url}"

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg}
        )

        if r.status_code != 200:
            print("❌ שגיאה:", r.text)

    except Exception as e:
        print("❌ קריסה:", e)

# ==============================
# שליפת RSS
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
        print("❌ שגיאה ב-RSS:", e)
        return []

# ==============================
# שליחה ראשונית (24 שעות אחרונות)
# ==============================
def first_run():
    print("🚀 הרצה ראשונית (24 שעות אחרונות)")

    sent = set()
    videos = get_videos()

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    recent_videos = [v for v in videos if v[3] >= cutoff]

    for vid, title, url, _ in recent_videos:
        msg = build_message(title)

        print("📤", msg)
        send_telegram(msg, url)

        sent.add(vid)
        time.sleep(20)

    save_sent(sent)

# ==============================
# בדיקה רגילה
# ==============================
def check_new():
    sent = load_sent()
    videos = get_videos()

    new_videos = [v for v in videos if v[0] not in sent]

    if not new_videos:
        print("😴 אין חדש")
        return

    print(f"🔥 {len(new_videos)} חדשים")

    for vid, title, url, _ in new_videos:
        msg = build_message(title)

        print("📤", msg)
        send_telegram(msg, url)

        sent.add(vid)
        save_sent(sent)

        time.sleep(20)

# ==============================
# לולאה
# ==============================
def main():
    if not os.path.exists(DATA_FILE):
        first_run()

    print("🤖 הבוט עובד...")

    while True:
        check_new()
        time.sleep(300)

# ==============================
# START
# ==============================
if __name__ == "__main__":
    main()

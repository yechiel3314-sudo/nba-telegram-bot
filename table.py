import requests
import time
import pytz
import logging
import feedparser
import re
from datetime import datetime

# ===============================
# הגדרות (מעודכן עם הפרטים שלך)
# ===============================
TELEGRAM_TOKEN = "8284141482:AAGG1vPtJrLeAvL7kADMeuFGbEydIq08ib0"
CHAT_ID = "-1003714393119" 

CHECK_INTERVAL = 60  # בדיקה כל דקה
CHECK_START = "08:30" # מתי להתחיל לחפש את הטבלה בבוקר

# הלינק ל-RSS שסיפקת
RSS_URL = "https://rss.app/feeds/9s9KfJp1JqkVZ3Yl.xml"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger()

# ===============================
# שליפת הפוסט וזיהוי התמונה
# ===============================
def get_latest_post():
    try:
        feed = feedparser.parse(RSS_URL)
        if not feed.entries:
            return None

        # עובר על 5 הפוסטים האחרונים (למקרה שהעלו משהו לפני הטבלה)
        for post in feed.entries[:5]:
            title = post.title.lower()
            
            # בדיקה אם זה הפוסט של GoatFlex לפי המילים שביקשת
            if "nba standings update" in title or "standing" in title:
                image = None
                
                # ניסיון 1: שליפה מ-media_content
                if "media_content" in post:
                    image = post.media_content[0]["url"]
                # ניסיון 2: חיפוש לינק לתמונה בתוך התיאור (לפעמים ה-RSS מחביא את זה שם)
                elif "description" in post:
                    img_match = re.search(r'src="([^"]+)"', post.description)
                    if img_match:
                        image = img_match.group(1)

                if image:
                    return {"id": post.id, "image": image}
        
    except Exception as e:
        logger.error(f"RSS error: {e}")
    return None

def send_to_telegram(image):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    payload = {
        "chat_id": CHAT_ID,
        "photo": image,
        "caption": "🏀 <b>NBA Standings Update</b>\nהטבלה היומית המעודכנת",
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=30)
        return r.status_code == 200
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False

# ===============================
# לולאה ראשית
# ===============================
def run_bot():
    tz = pytz.timezone("Asia/Jerusalem")
    last_sent_id = None
    sent_today = False
    
    logger.info("Bot started and monitoring RSS...")

    while True:
        try:
            now = datetime.now(tz)
            current_time = now.strftime("%H:%M")

            # בדיקה אם הגיע זמן השליחה וטרם נשלח להיום
            if current_time >= CHECK_START and not sent_today:
                post = get_latest_post()
                
                if post and post["id"] != last_sent_id:
                    logger.info(f"Found new standings! ID: {post['id']}")
                    if send_to_telegram(post["image"]):
                        last_sent_id = post["id"]
                        sent_today = True
                        logger.info("Image sent successfully.")

            # איפוס בחצות
            if current_time == "00:01":
                sent_today = False
                logger.info("Daily reset performed.")

            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            logger.error(f"Main loop error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_bot()

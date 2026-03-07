import requests
import time
import pytz
import logging
import feedparser
import re
from datetime import datetime

# ===============================
# הגדרות (Token & Chat ID שלך)
# ===============================
TELEGRAM_TOKEN = "8284141482:AAGG1vPtJrLeAvL7kADMeuFGbEydIq08ib0"
CHAT_ID = "-1003714393119" 

CHECK_INTERVAL = 60 
CHECK_START = "23:42" # זמן הבדיקה הקרוב

RSS_URL = "https://rss.app/feeds/9s9KfJp1JqkVZ3Yl.xml"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger()

def get_latest_post():
    try:
        feed = feedparser.parse(RSS_URL)
        if not feed.entries:
            logger.warning("RSS Feed is empty!")
            return None

        for post in feed.entries[:10]: # בודק את 10 הפוסטים האחרונים
            title = post.title.lower()
            logger.info(f"Checking post title: {title}") # זה יגיד לנו מה הבוט רואה
            
            # חיפוש גמיש יותר למילה Standings
            if "standing" in title:
                image = None
                if "media_content" in post:
                    image = post.media_content[0]["url"]
                elif "description" in post:
                    img_match = re.search(r'src="([^"]+)"', post.description)
                    if img_match:
                        image = img_match.group(1)

                if image:
                    logger.info(f"MATCH FOUND! Image URL: {image}")
                    return {"id": post.id, "image": image}
        
        logger.info("No post with 'standings' found in the last 10 entries.")
    except Exception as e:
        logger.error(f"RSS error: {e}")
    return None

def send_to_telegram(image):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    payload = {
        "chat_id": CHAT_ID,
        "photo": image,
        "caption": "🏀 <b>NBA Standings Update</b>",
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=30)
        return r.status_code == 200
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False

def run_bot():
    tz = pytz.timezone("Asia/Jerusalem")
    last_sent_id = None
    sent_today = False
    
    logger.info("Bot started and monitoring RSS...")

    while True:
        try:
            now = datetime.now(tz)
            current_time = now.strftime("%H:%M")

            if current_time >= CHECK_START and not sent_today:
                logger.info(f"Time reached ({current_time}). Checking RSS...")
                post = get_latest_post()
                
                if post:
                    if send_to_telegram(post["image"]):
                        last_sent_id = post["id"]
                        sent_today = True
                        logger.info("Success! Image sent to Telegram.")
                    else:
                        logger.error("Failed to send image.")
                else:
                    # אם לא מצא, ננסה שוב בעוד דקה עד שיימצא או עד סוף היום
                    logger.warning("Standings not found yet, will retry in 60 seconds...")

            if current_time == "00:01":
                sent_today = False
                logger.info("Daily reset.")

            time.sleep(CHECK_INTERVAL)
        except Exception as e:
            logger.error(f"Main loop error: {e}")
            time.sleep(30)

if __name__ == "__main__":
    run_bot()

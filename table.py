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

# שעת הבדיקה - שנה לזמן שקרוב אליך עכשיו לבדיקה (למשל 23:55)
CHECK_START = "23:48" 

# הלינק ל-RSS של פייסבוק GoatFlex
RSS_URL = "https://rss.app/feeds/9s9KfJp1JqkVZ3Yl.xml"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger()

def get_goatflex_image():
    try:
        # שליפה של הפיד
        feed = feedparser.parse(RSS_URL)
        
        if not feed.entries:
            logger.warning("הפיד של פייסבוק ריק כרגע - ייתכן ששירות ה-RSS חסום או מתעדכן")
            return None

        for post in feed.entries:
            title = post.title
            logger.info(f"בודק פוסט: {title}")
            
            # בדיקה אם הכותרת מכילה את המילים המדויקות מ-GoatFlex
            if "NBA Standings Update" in title or "standings" in title.lower():
                image = None
                
                # חיפוש תמונה בדרכים שונות שפייסבוק משתמש בהן
                if "media_content" in post:
                    image = post.media_content[0]["url"]
                elif "description" in post:
                    # חילוץ לינק תמונה מתוך תיאור ה-HTML
                    img_match = re.search(r'src="([^"]+)"', post.description)
                    if img_match:
                        image = img_match.group(1)
                
                if image:
                    logger.info(f"נמצאה התאמה! שולח תמונה: {image}")
                    return image
        
        logger.info("לא נמצא פוסט עם הכותרת המבוקשת בפיד הנוכחי")
    except Exception as e:
        logger.error(f"שגיאה בקריאת ה-RSS: {e}")
    return None

def send_photo(image_url):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    payload = {
        "chat_id": CHAT_ID,
        "photo": image_url,
        "caption": "🏀 <b>NBA Standings Update</b>\nמתוך פייסבוק GoatFlex Sports",
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=30)
        return r.status_code == 200
    except Exception as e:
        logger.error(f"שגיאה בשליחה לטלגרם: {e}")
        return False

def run_bot():
    tz = pytz.timezone("Asia/Jerusalem")
    sent_today = False
    logger.info("הבוט של GoatFlex הופעל ומחכה לשעה הנקובה")

    while True:
        now = datetime.now(tz)
        current_time = now.strftime("%H:%M")

        if current_time == CHECK_START and not sent_today:
            logger.info("מבצע בדיקה יומית בפיד של GoatFlex...")
            image_url = get_goatflex_image()
            
            if image_url:
                if send_photo(image_url):
                    sent_today = True
                    logger.info("התמונה נשלחה בהצלחה!")
            else:
                logger.warning("לא נמצאה תמונה מתאימה, מנסה שוב בעוד דקה...")

        # איפוס בחצות
        if current_time == "00:01":
            sent_today = False

        time.sleep(30)

if __name__ == "__main__":
    run_bot()

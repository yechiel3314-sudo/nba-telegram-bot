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

# שעת הבדיקה - כרגע על חצות וחמש
CHECK_START = "00:03" 
CHECK_INTERVAL = 60 # בדיקה כל דקה

RSS_URL = "https://rss.app/feeds/9s9KfJp1JqkVZ3Yl.xml"

# הגדרת לוגים מפורטת שתראה ב-Railway
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger()

# ===============================
# שליפת הפוסט וזיהוי התמונה
# ===============================
def get_latest_post():
    try:
        logger.info(f"--- מתחיל סריקת RSS בכתובת: {RSS_URL} ---")
        feed = feedparser.parse(RSS_URL)
        
        if not feed.entries:
            logger.warning("⚠️ אזהרה: הפיד חזר ריק! (ייתכן שפייסבוק חוסם את הגישה)")
            return None

        logger.info(f"נמצאו {len(feed.entries)} פוסטים בפיד. מתחיל לסנן...")

        for post in feed.entries[:10]:
            title = post.title.lower()
            logger.info(f"🔍 בודק פוסט: '{post.title}'")
            
            # החיפוש המדויק שביקשת
            if "nba standings update" in title or "standing" in title:
                logger.info(f"✅ נמצאה התאמה לכותרת המבוקשת!")
                
                image = None
                # ניסיון 1: שליפה מ-media_content
                if "media_content" in post:
                    image = post.media_content[0]["url"]
                    logger.info("📸 תמונה נמצאה ב-media_content")
                
                # ניסיון 2: חיפוש לינק לתמונה בתוך התיאור (לפייסבוק זה קורה הרבה)
                if not image and "description" in post:
                    img_match = re.search(r'src="([^"]+)"', post.description)
                    if img_match:
                        image = img_match.group(1)
                        logger.info("📸 תמונה חולצה מתוך ה-description")

                if image:
                    return {"id": post.id, "image": image, "title": post.title}
                else:
                    logger.warning("❌ נמצא פוסט מתאים אבל לא הצלחתי לחלץ לינק לתמונה")
        
        logger.info("🔚 סריקה הסתיימה: לא נמצא פוסט עם 'Standing' ב-10 האחרונים.")
    except Exception as e:
        logger.error(f"❌ שגיאה בתהליך ה-RSS: {e}")
    return None

# ===============================
# שליחה לטלגרם
# ===============================
def send_to_telegram(image_url, title):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    payload = {
        "chat_id": CHAT_ID,
        "photo": image_url,
        "caption": f"🏀 <b>NBA Standings Update</b>\nמתוך פייסבוק GoatFlex",
        "parse_mode": "HTML"
    }
    try:
        logger.info(f"📤 מנסה לשלוח תמונה לטלגרם: {image_url}")
        r = requests.post(url, json=payload, timeout=30)
        if r.status_code == 200:
            logger.info("🚀 הצלחה! התמונה נשלחה בהצלחה לערוץ.")
            return True
        else:
            logger.error(f"❌ טלגרם החזיר שגיאה: {r.text}")
    except Exception as e:
        logger.error(f"❌ שגיאה בשליחה לטלגרם: {e}")
    return False

# ===============================
# הבוט הראשי
# ===============================
def run_bot():
    tz = pytz.timezone("Asia/Jerusalem")
    last_sent_id = None
    sent_today = False
    
    logger.info("🚀 הבוט התניע! סורק בכל יום החל מ-" + CHECK_START)

    while True:
        try:
            now = datetime.now(tz)
            current_time = now.strftime("%H:%M")

            # בדיקה בזמן המיועד
            if current_time >= CHECK_START and not sent_today:
                logger.info(f"⏰ השעה {current_time} - מבצע בדיקה יומית...")
                post = get_latest_post()
                
                if post:
                    if post["id"] != last_sent_id:
                        if send_to_telegram(post["image"], post["title"]):
                            last_sent_id = post["id"]
                            sent_today = True
                    else:
                        logger.info("♻️ הפוסט הכי חדש כבר נשלח בעבר, מחכה ליום הבא.")
                else:
                    logger.info("⏳ לא נמצאה טבלה כרגע, ננסה שוב בעוד דקה.")

            # איפוס בחצות וחצי כדי להתכונן ליום הבא
            if current_time == "00:30":
                sent_today = False
                logger.info("🔄 איפוס יומי בוצע - הבוט מוכן ליום החדש.")

            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            logger.error(f"⚠️ שגיאה בלולאה הראשית: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_bot()

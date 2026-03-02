import requests
import time
import os
import gc
import logging
import json
import random
from datetime import datetime
import pytz
from moviepy.editor import VideoFileClip, concatenate_videoclips

# ==========================================================
# CONFIGURATION - הגדרות מערכת
# ==========================================================

TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# רשימת הישראלים למעקב צמוד - IDs רשמיים
ISRAELI_PLAYERS = {
    "1630166": "דני אבדיה",
    "1642234": "בן שרף",
    "1642300": "דני וולף"
}

# הגדרות Headers קריטיות לעקיפת חסימות NBA Stats
NBA_STATS_HEADERS = {
    "Host": "stats.nba.com",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "Connection": "keep-alive"
}

# Headers כלליים ל-CDN
GENERAL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://www.nba.com/"
}

SENT_TODAY = set()
LAST_MORNING_RUN = None
israel_tz = pytz.timezone("Asia/Jerusalem")

# ==========================================================
# LOGGING SYSTEM - ניהול התראות ולוגים
# ==========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

def log_step(step, message):
    logging.info(f"[{step}] ✅ {message}")

def log_error(step, message):
    logging.error(f"[{step}] ❌ {message}")

def log_warn(step, message):
    logging.warning(f"[{step}] ⚠️ {message}")

def notify_admin(message):
    """שליחת עדכון טקסט קצר לטלגרם על סטטוס הבוט"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": f"🤖 סטטוס בוט: {message}", "parse_mode": "HTML"})
    except:
        pass

# ==========================================================
# NBA ASSETS API - הפתרון הוודאי
# ==========================================================

def get_nba_video_assets(game_id, player_id):
    """שליפת קליפים ישירות מה-API הרשמי של NBA Stats"""
    step = "NBA_ASSETS"
    url = f"https://stats.nba.com/stats/videoeventsasset?GameID={game_id}&PlayerID={player_id}"
    
    try:
        log_step(step, f"מושך נכסי וידאו עבור שחקן {player_id} במשחק {game_id}")
        # שימוש ב-Retry למקרה של Timeout שנראה בלוגים של Railway
        for attempt in range(3):
            try:
                response = requests.get(url, headers=NBA_STATS_HEADERS, timeout=20)
                if response.status_code == 200:
                    break
            except requests.exceptions.Timeout:
                log_warn(step, f"Timeout בניסיון {attempt+1}, מנסה שוב...")
                time.sleep(2)
        else:
            return []

        data = response.json()
        results = data.get('resultSets', {}).get('Meta', {}).get('videoUrls', [])
        
        # סינון וסידור הקליפים - המבנה המקורי בדרך כלל כרונולוגי
        valid_clips = []
        for vid in results:
            mp4_url = vid.get('lhigh') or vid.get('mhigh')
            if mp4_url:
                valid_clips.append(mp4_url)
        
        log_step(step, f"נמצאו {len(valid_clips)} קליפים רשמיים.")
        return valid_clips

    except Exception as e:
        log_error(step, f"כשל בשליפת נכסי וידאו: {e}")
        return []

# ==========================================================
# TELEGRAM INTERFACE
# ==========================================================

def send_video_by_url(video_url, caption):
    """שליחת וידאו לטלגרם באמצעות URL ישיר (חוסך הורדה)"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    payload = {
        "chat_id": CHAT_ID,
        "video": video_url,
        "caption": caption,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, data=payload, timeout=30)
        return r.status_code == 200
    except Exception as e:
        log_error("TELEGRAM_URL", f"כשל בשליחת URL: {e}")
        return False

def send_video_file(video_path, caption):
    """שליחת קובץ וידאו פיזי מהשרת"""
    step = "TELEGRAM_FILE"
    if not os.path.exists(video_path):
        log_error(step, f"קובץ {video_path} לא קיים")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    try:
        with open(video_path, "rb") as f:
            r = requests.post(
                url,
                data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                files={"video": f},
                timeout=300 # זמן ארוך יותר לקבצים כבדים
            )
        return r.status_code == 200
    except Exception as e:
        log_error(step, f"כשל בשליחת קובץ: {e}")
        return False

# ==========================================================
# VIDEO CONCATENATION ENGINE - חיבור מהלכים
# ==========================================================

def build_merged_highlights(game_id, game_date, player_id, player_name, stats_line):
    """מחבר קליפים לסרטון אחד בסדר כרונולוגי"""
    step = f"MERGE_{player_name}"
    
    asset_urls = get_nba_video_assets(game_id, player_id)
    
    if not asset_urls:
        log_warn(step, "לא נמצאו נכסים ב-Stats API.")
        return None

    clips = []
    temp_files = []
    
    try:
        # הגבלת כמות מהלכים כדי למנוע קריסת זכרון ב-Railway
        max_clips = 15 if player_id in ISRAELI_PLAYERS else 10
        
        for i, url in enumerate(asset_urls[:max_clips]):
            try:
                # הורדה זמנית לצורך איחוד
                r = requests.get(url, headers=GENERAL_HEADERS, timeout=15)
                if r.status_code == 200:
                    fname = f"temp_{player_id}_{i}.mp4"
                    with open(fname, "wb") as f:
                        f.write(r.content)
                    
                    clip = VideoFileClip(fname)
                    clips.append(clip)
                    temp_files.append(fname)
                    log_step(step, f"הורד מהלך {i+1}/{len(asset_urls)}")
            except Exception as download_err:
                log_warn(step, f"דילוג על מהלך {i} עקב שגיאה: {download_err}")
                continue

        if not clips:
            return None

        log_step(step, f"מתחיל איחוד של {len(clips)} מהלכים...")
        output = f"final_{player_id}_{int(time.time())}.mp4"
        
        # איחוד קטעים
        final_video = concatenate_videoclips(clips, method="compose")
        final_video.write_videofile(output, codec="libx264", audio=True, logger=None, threads=2)
        
        # סגירת קבצים וניקוי
        final_video.close()
        for c in clips:
            c.close()
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)
            
        icon = '🇮🇱' if player_id in ISRAELI_PLAYERS else '🔥'
        caption = f"{icon} <b>ביצועי {player_name} מהלילה!</b>\n\n📊 {stats_line}\n🏀 <i>המהלכים מסודרים לפי סדר המשחק</i>"
        return output, caption

    except Exception as e:
        log_error(step, f"שגיאה קריטית בתהליך הבנייה: {e}")
        # ניקוי חירום של קבצים זמניים
        for f in temp_files:
            if os.path.exists(f): os.remove(f)
        return None

# ==========================================================
# GAME ANALYTICS & CORE LOGIC
# ==========================================================

def process_nba_games(check_35=False):
    step = "CORE_SCAN"
    log_step(step, "מתחיל סריקה של כל משחקי הלילה...")

    try:
        sb_url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
        resp = requests.get(sb_url, headers=GENERAL_HEADERS, timeout=15)
        if resp.status_code != 200:
            log_error(step, "לוח התוצאות לא זמין")
            return

        games = resp.json().get("scoreboard", {}).get("games", [])
        log_step(step, f"נמצאו {len(games)} משחקים בלוח.")
        
        for g in games:
            gid = g["gameId"]
            g_status = g.get("gameStatus") # 3 זה סיום משחק
            g_date = g.get("gameDate")
            
            # בדיקת בוקסקור
            box_url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
            box_resp = requests.get(box_url, headers=GENERAL_HEADERS, timeout=15)
            if box_resp.status_code != 200:
                continue
            
            box_data = box_resp.json().get("game", {})
            h_team = box_data.get("homeTeam", {})
            a_team = box_data.get("awayTeam", {})
            
            h_players = h_team.get("players", [])
            a_players = a_team.get("players", [])
            all_players = h_players + a_players

            # לוגיקת פוסטר: כוכב הבית [cite: 2026-03-01]
            home_star = max(h_players, key=lambda x: x.get("statistics", {}).get("points", 0)) if h_players else None
            
            for p in all_players:
                stats = p.get("statistics", {})
                pid = str(p.get("personId", ""))
                pts = stats.get("points", 0)
                
                is_israeli = pid in ISRAELI_PLAYERS
                is_top_performer = (check_35 and pts >= 35)

                if (is_israeli or is_top_performer) and pid not in SENT_TODAY:
                    # המשחק חייב להיות הסתיים או לקראת סיום כדי שיהיו קליפים
                    if g_status < 2: continue 

                    name = ISRAELI_PLAYERS.get(pid, f"{p.get('firstName')} {p.get('familyName')}")
                    log_step(step, f"מעבד את {name} ({pts} נק')")

                    # הרחבת הסטטיסטיקה לחטיפות וחסימות
                    stls = stats.get('steals', 0)
                    blks = stats.get('blocks', 0)
                    rebs = stats.get('reboundsTotal', 0)
                    asts = stats.get('assists', 0)
                    
                    stats_str = f"🏀 {pts} נק' | 👐 {rebs} רב' | 🪄 {asts} אס'"
                    if stls > 0 or blks > 0:
                        stats_str += f"\n🛡️ {stls} חט' | ❌ {blks} חס'"
                    
                    # בניית הסרטון
                    result = build_merged_highlights(gid, g_date, pid, name, stats_str)
                    
                    if result:
                        v_file, caption = result
                        if send_video_file(v_file, caption):
                            SENT_TODAY.add(pid)
                            log_step(step, f"הסרטון של {name} נשלח בהצלחה!")
                        if os.path.exists(v_file): os.remove(v_file)
                    else:
                        # Fallback: שליחת לינק ישיר למהלך בודד
                        assets = get_nba_video_assets(gid, pid)
                        if assets:
                            caption = f"🏀 ביצוע נבחר: <b>{name}</b>\n{stats_str}"
                            if send_video_by_url(assets[0], caption):
                                SENT_TODAY.add(pid)
                                log_step(step, f"נשלח מהלך בודד כגיבוי עבור {name}")

    except Exception as e:
        log_error(step, f"שגיאה כללית בעיבוד המשחקים: {e}")

# ==========================================================
# MONITORING LOOP - לולאת עבודה
# ==========================================================

def start_monitor():
    global LAST_MORNING_RUN
    notify_admin("הבוט עלה לאוויר ומנטר משחקים 🏀")
    log_step("SYSTEM", "מנטר NBA הופעל בהצלחה.")
    
    # הרצה ראשונית
    process_nba_games(check_35=True)

    while True:
        try:
            now = datetime.now(israel_tz)
            
            # איפוס יומי ב-13:00 - הכנה ללילה החדש
            if now.hour == 13 and now.minute < 15:
                SENT_TODAY.clear()
                log_step("SYSTEM", "רשימת הדיוור אופסה ליום חדש.")
                time.sleep(900)

            # סריקה אקטיבית כל 10 דקות
            process_nba_games(check_35=True)
            
            # ניקוי זכרון למניעת קריסות ב-Railway
            gc.collect()
            
            # המתנה בין סבבים
            time.sleep(600)

        except Exception as e:
            log_error("MAIN_LOOP", f"שגיאה קריטית בלולאה: {e}")
            time.sleep(120)

if __name__ == "__main__":
    try:
        start_monitor()
    except KeyboardInterrupt:
        log_warn("SYSTEM", "הבוט הופסק ידנית.")

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

# רשימת הישראלים למעקב צמוד - מעודכן לכל השלושה
ISRAELI_PLAYERS = {
    "1630166": "דני אבדיה",
    "1642234": "בן שרף",
    "1642300": "דני וולף"
}

# Headers מתקדמים לעקיפת חסימות (מבוסס על הלוגים של Railway)
NBA_STATS_HEADERS = {
    "Host": "stats.nba.com",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "Connection": "keep-alive"
}

GENERAL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0",
    "Referer": "https://www.nba.com/"
}

SENT_TODAY = set()
israel_tz = pytz.timezone("Asia/Jerusalem")

# ==========================================================
# LOGGING & NOTIFICATIONS
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

def alert_telegram(msg):
    """שליחת התראת לוג קריטית לטלגרם"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": f"🚨 LOG: {msg}", "parse_mode": "HTML"}, timeout=5)
    except:
        pass

# ==========================================================
# CREATIVE SOLUTION: ROBUST VIDEO FETCHING
# ==========================================================

def get_nba_video_assets_robust(game_id, player_id):
    """
    פתרון יצירתי: מנגנון סריקה רב-שכבתית עם Backoff
    פותר את שגיאות ה-Read Timeout שראינו בלוגים
    """
    step = "ROBUST_FETCH"
    url = f"https://stats.nba.com/stats/videoeventsasset?GameID={game_id}&PlayerID={player_id}"
    
    for attempt in range(1, 4): # עד 3 ניסיונות
        try:
            log_step(step, f"ניסיון {attempt} לשליפת וידאו עבור {player_id}")
            response = requests.get(url, headers=NBA_STATS_HEADERS, timeout=25)
            
            if response.status_code == 200:
                data = response.json()
                video_urls = data.get('resultSets', {}).get('Meta', {}).get('videoUrls', [])
                
                clips = []
                for vid in video_urls:
                    # עדיפות ל-HD (lhigh) ואז לאיכות רגילה
                    link = vid.get('lhigh') or vid.get('mhigh')
                    if link: clips.append(link)
                
                if clips:
                    log_step(step, f"נמצאו {len(clips)} קטעים עבור {player_id}")
                    return clips
            
            elif response.status_code == 403:
                log_error(step, "חסימת NBA (403). משנה Headers...")
                NBA_STATS_HEADERS["User-Agent"] = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) {random.randint(100,999)}"
                
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            log_warn(step, f"שגיאת תקשורת בניסיון {attempt}: {e}")
            time.sleep(attempt * 5) # השהיה גדלה בין ניסיון לניסיון
            
    return []

# ==========================================================
# VIDEO PROCESSING
# ==========================================================

def create_player_highlight_reel(game_id, player_id, player_name, stats_line):
    """מחבר את כל המהלכים לסרטון אחד בסדר כרונולוגי"""
    step = f"VIDEO_{player_name}"
    
    asset_urls = get_nba_video_assets_robust(game_id, player_id)
    
    if not asset_urls:
        log_warn(step, f"לא נמצאו קליפים זמינים עבור {player_name}")
        return None

    clips = []
    temp_files = []
    
    try:
        # עיבוד מקסימום 12 קליפים למניעת קריסת זיכרון
        for i, url in enumerate(asset_urls[:12]):
            try:
                r = requests.get(url, headers=GENERAL_HEADERS, timeout=20)
                if r.status_code == 200:
                    temp_name = f"tmp_{player_id}_{i}.mp4"
                    with open(temp_name, "wb") as f:
                        f.write(r.content)
                    
                    video_clip = VideoFileClip(temp_name)
                    clips.append(video_clip)
                    temp_files.append(temp_name)
            except Exception as e:
                log_warn(step, f"דילוג על קליפ {i}: {e}")
                continue

        if not clips: return None

        output_filename = f"final_{player_id}_{game_id}.mp4"
        log_step(step, "מתחיל חיבור קליפים (Concatenation)...")
        
        # חיבור המהלכים (הם מגיעים מה-API לפי סדר המהלכים במשחק)
        final_video = concatenate_videoclips(clips, method="compose")
        final_video.write_videofile(output_filename, codec="libx264", audio=True, logger=None, threads=2)
        
        # ניקוי משאבים
        final_video.close()
        for c in clips: c.close()
        for f in temp_files:
            if os.path.exists(f): os.remove(f)
            
        caption = f"🇮🇱 <b>הופעה של {player_name}!</b>\n\n📊 {stats_line}\n⚡ <i>המהלכים מסודרים לפי סדר המשחק</i>"
        if player_id not in ISRAELI_PLAYERS:
            caption = caption.replace("🇮🇱", "🔥")
            
        return output_filename, caption

    except Exception as e:
        log_error(step, f"כשל ביצירת הסרטון: {e}")
        for f in temp_files:
            if os.path.exists(f): os.remove(f)
        return None

# ==========================================================
# CORE SCAN LOGIC
# ==========================================================

def scan_and_process():
    step = "CORE_SCAN"
    log_step(step, "סורק בוקסקור לחיפוש ישראלים והופעות חריגות...")

    try:
        # 1. קבלת רשימת משחקי היום
        sb_url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
        resp = requests.get(sb_url, headers=GENERAL_HEADERS, timeout=15)
        if resp.status_code != 200: return

        games = resp.json().get("scoreboard", {}).get("games", [])
        
        for g in games:
            gid = g["gameId"]
            # סטטוס 3 = הסתיים, סטטוס 2 = פעיל
            if g.get("gameStatus") < 2: continue 

            # 2. שליפת נתוני שחקנים (BoxScore)
            box_url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
            box_resp = requests.get(box_url, headers=GENERAL_HEADERS, timeout=15)
            if box_resp.status_code != 200: continue
            
            game_data = box_resp.json().get("game", {})
            players = game_data.get("homeTeam", {}).get("players", []) + \
                      game_data.get("awayTeam", {}).get("players", [])

            for p in players:
                pid = str(p.get("personId", ""))
                stats = p.get("statistics", {})
                pts = stats.get("points", 0)
                
                # תנאי הפעלה: אבדיה, שרף, וולף או 35+ נקודות
                is_israeli = pid in ISRAELI_PLAYERS
                is_beast = pts >= 35
                
                if (is_israeli or is_beast) and f"{pid}_{gid}" not in SENT_TODAY:
                    name = ISRAELI_PLAYERS.get(pid, f"{p.get('firstName')} {p.get('familyName')}")
                    
                    # בדיקה אם יש נתונים מינימליים (למנוע שליחת סרטון ריק)
                    if pts == 0 and stats.get('assists', 0) == 0 and stats.get('reboundsTotal', 0) == 0:
                        continue

                    log_step(step, f"מטרה זוהתה: {name} עם {pts} נקודות")
                    
                    # בניית שורת סטטיסטיקה מורחבת
                    stls = stats.get('steals', 0)
                    blks = stats.get('blocks', 0)
                    rebs = stats.get('reboundsTotal', 0)
                    asts = stats.get('assists', 0)
                    line = f"{pts} נק', {rebs} רב', {asts} אס'"
                    if stls > 0 or blks > 0:
                        line += f" | {stls} חט', {blks} חס'"

                    # יצירת הסרטון ושליחה
                    result = create_player_highlight_reel(gid, pid, name, line)
                    
                    if result:
                        v_path, caption = result
                        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
                        try:
                            with open(v_path, "rb") as video_file:
                                r = requests.post(url, data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                                               files={"video": video_file}, timeout=120)
                                if r.status_code == 200:
                                    SENT_TODAY.add(f"{pid}_{gid}")
                                    log_step(step, f"סרטון של {name} נשלח בהצלחה.")
                        except Exception as send_err:
                            log_error(step, f"כשל בשליחה לטלגרם: {send_err}")
                        
                        if os.path.exists(v_path): os.remove(v_path)
                    else:
                        log_warn(step, f"לא הצלחתי ליצור סרטון עבור {name} כרגע.")

    except Exception as e:
        log_error(step, f"שגיאה כללית בסריקה: {e}")

# ==========================================================
# TELEGRAM INTERFACE & UTILS
# ==========================================================

def send_telegram_msg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})

# ==========================================================
# MAIN LOOP
# ==========================================================

def main():
    log_step("SYSTEM", "הבוט הופעל. מחפש את אבדיה, שרף ווולף...")
    send_telegram_msg("🚀 <b>הבוט הופעל מחדש!</b>\nבודק ביצועים של הישראלים ב-NBA.")
    
    while True:
        try:
            now = datetime.now(israel_tz)
            
            # איפוס רשימת נשלחו בצהריים (14:00)
            if now.hour == 14 and now.minute < 10:
                SENT_TODAY.clear()
                log_step("SYSTEM", "רשימת הדיוור אופסה.")
                time.sleep(600)

            # הרצת הסריקה
            scan_and_process()
            
            # שינה של 8 דקות בין בדיקות
            log_step("SYSTEM", "סבב הסתיים. נכנס להמתנה...")
            gc.collect() # ניקוי זיכרון אגרסיבי ל-Railway
            time.sleep(60)

        except Exception as e:
            log_error("MAIN_LOOP", f"שגיאה בלולאה הראשית: {e}")
            alert_telegram(f"שגיאה בלולאה: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()

# ==========================================================
# END OF CODE - MAINTAINING STABILITY AND LENGTH
# ==========================================================

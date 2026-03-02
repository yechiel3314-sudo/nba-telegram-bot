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

# רשימת הישראלים למעקב צמוד - כולל ברוקלין ומישיגן
ISRAELI_PLAYERS = {
    "1630166": "דני אבדיה",
    "1642234": "בן שרף",
    "1642300": "דני וולף"
}

# Headers מעודכנים למניעת חסימות ו-Timeouts
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
# LOGGING SYSTEM - התראות לוג מפורטות
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

# ==========================================================
# ROBUST VIDEO FETCHING - פתרון לשגיאות Timeout
# ==========================================================

def get_video_assets_with_retry(game_id, player_id):
    """ניסיון שליפת וידאו עם מנגנון Retry למניעת שגיאות חיבור"""
    step = "ROBUST_FETCH"
    url = f"https://stats.nba.com/stats/videoeventsasset?GameID={game_id}&PlayerID={player_id}"
    
    # ניסיון עד 4 פעמים עם פסק זמן הולך וגדל
    for attempt in range(1, 5):
        try:
            timeout_val = 15 + (attempt * 5)
            log_step(step, f"ניסיון {attempt} עבור {player_id} (Timeout: {timeout_val}s)")
            
            response = requests.get(url, headers=NBA_STATS_HEADERS, timeout=timeout_val)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('resultSets', {}).get('Meta', {}).get('videoUrls', [])
                
                clips = []
                for vid in results:
                    link = vid.get('lhigh') or vid.get('mhigh')
                    if link: clips.append(link)
                
                if clips:
                    log_step(step, f"נמצאו {len(clips)} קליפים.")
                    return clips
                else:
                    log_warn(step, f"ה-API החזיר תשובה תקינה אך ללא לינקים לוידאו.")
                    
            elif response.status_code == 403:
                log_error(step, "חסימת גישה (403). משנה זהות דפדפן...")
                NBA_STATS_HEADERS["User-Agent"] = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) {random.randint(100,999)}"

        except requests.exceptions.RequestException as e:
            log_warn(step, f"שגיאת תקשורת בניסיון {attempt}: {e}")
            time.sleep(attempt * 3)
            
    return []

# ==========================================================
# VIDEO CONCATENATION - חיבור מהלכים כרונולוגי
# ==========================================================

def build_merged_highlights(game_id, player_id, player_name, stats_line):
    """מוריד קליפים ומחבר אותם לסרטון אחד"""
    step = f"VIDEO_BUILDER"
    
    links = get_video_assets_with_retry(game_id, player_id)
    if not links:
        log_warn(step, f"לא ניתן ליצור סרטון עבור {player_name} - אין מקורות.")
        return None

    clips = []
    temp_files = []
    
    try:
        # הגבלה ל-12 קליפים כדי לא לחרוג מזכרון השרת ב-Railway
        for i, url in enumerate(links[:12]):
            try:
                r = requests.get(url, headers=GENERAL_HEADERS, timeout=20)
                if r.status_code == 200:
                    fname = f"tmp_{player_id}_{i}.mp4"
                    with open(fname, "wb") as f:
                        f.write(r.content)
                    
                    video = VideoFileClip(fname)
                    clips.append(video)
                    temp_files.append(fname)
            except:
                continue

        if not clips: return None

        output = f"final_{player_id}_{game_id}.mp4"
        log_step(step, f"מחבר {len(clips)} קטעים עבור {player_name}...")
        
        final_video = concatenate_videoclips(clips, method="compose")
        final_video.write_videofile(output, codec="libx264", audio=True, logger=None, threads=2)
        
        # סגירת קבצים
        final_video.close()
        for c in clips: c.close()
        for f in temp_files:
            if os.path.exists(f): os.remove(f)
            
        icon = "🇮🇱" if player_id in ISRAELI_PLAYERS else "🔥"
        caption = f"{icon} <b>ביצועי {player_name} מהלילה!</b>\n\n📊 {stats_line}\n🏀 <i>המהלכים מסודרים לפי סדר המשחק</i>"
        return output, caption

    except Exception as e:
        log_error(step, f"שגיאה בתהליך בניית הוידאו: {e}")
        for f in temp_files:
            if os.path.exists(f): os.remove(f)
        return None

# ==========================================================
# CORE MONITORING - סריקת משחקים ושחקנים
# ==========================================================

def process_nba_data():
    step = "DATA_SCAN"
    log_step(step, "מתחיל סריקת נתונים עמוקה...")

    try:
        # שליפת לוח המשחקים
        sb_url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
        resp = requests.get(sb_url, headers=GENERAL_HEADERS, timeout=15)
        if resp.status_code != 200: return

        games = resp.json().get("scoreboard", {}).get("games", [])
        
        for g in games:
            gid = g["gameId"]
            if g.get("gameStatus") < 2: continue # דלג אם המשחק טרם החל

            # שליפת בוקסקור (BoxScore)
            box_url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
            box_resp = requests.get(box_url, headers=GENERAL_HEADERS, timeout=15)
            if box_resp.status_code != 200: continue
            
            data = box_resp.json().get("game", {})
            all_players = data.get("homeTeam", {}).get("players", []) + \
                          data.get("awayTeam", {}).get("players", [])

            for p in all_players:
                pid = str(p.get("personId", ""))
                stats = p.get("statistics", {})
                pts = stats.get("points", 0)
                
                # תנאי סף: ישראלי (אבדיה/שרף/וולף) או משחק מפלצתי (35+)
                is_israeli = pid in ISRAELI_PLAYERS
                is_beast = pts >= 35

                if (is_israeli or is_beast) and f"{pid}_{gid}" not in SENT_TODAY:
                    # בדיקה שיש לפחות פעולה אחת מתועדת
                    if pts == 0 and stats.get('assists', 0) == 0 and stats.get('steals', 0) == 0:
                        continue

                    name = ISRAELI_PLAYERS.get(pid, f"{p.get('firstName')} {p.get('familyName')}")
                    log_step(step, f"זוהה שחקן יעד: {name} ({pts} נק')")

                    # הכנת שורת סטטיסטיקה מפורטת (כולל חטיפות וחסימות)
                    rebs = stats.get('reboundsTotal', 0)
                    asts = stats.get('assists', 0)
                    stls = stats.get('steals', 0)
                    blks = stats.get('blocks', 0)
                    
                    line = f"{pts} נק', {rebs} רב', {asts} אס'"
                    if stls > 0 or blks > 0:
                        line += f" | {stls} חט', {blks} חס'"

                    # יצירת הסרטון
                    video_res = build_merged_highlights(gid, pid, name, line)
                    
                    if video_res:
                        v_file, caption = video_res
                        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
                        try:
                            with open(v_file, "rb") as f:
                                r = requests.post(url, data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                                               files={"video": f}, timeout=150)
                                if r.status_code == 200:
                                    SENT_TODAY.add(f"{pid}_{gid}")
                                    log_step(step, f"סרטון של {name} נשלח בהצלחה לקבוצה.")
                        except Exception as e:
                            log_error(step, f"כשל בשליחה לטלגרם: {e}")
                        
                        if os.path.exists(v_file): os.remove(v_file)

    except Exception as e:
        log_error(step, f"שגיאה כללית בעיבוד: {e}")

# ==========================================================
# MAIN LOOP
# ==========================================================

def main():
    log_step("SYSTEM", "הבוט הופעל. מחפש את אבדיה, שרף ווולף...")
    
    while True:
        try:
            now = datetime.now(israel_tz)
            
            # איפוס יומי ב-14:00 (אחרי שכל משחקי הלילה הסתיימו)
            if now.hour == 14 and now.minute < 10:
                SENT_TODAY.clear()
                log_step("SYSTEM", "רשימת הדיוור אופסה.")
                time.sleep(600)

            process_nba_data()
            
            # ניקוי זכרון למניעת קריסות ב-Railway
            gc.collect()
            time.sleep(480) # סריקה כל 8 דקות

        except Exception as e:
            log_error("MAIN_LOOP", f"שגיאה בלולאה: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()

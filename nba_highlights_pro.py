import requests
import time
import os
import gc
import logging
import json
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
# LOGGING SYSTEM
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
# NBA ASSETS API - הפתרון הוודאי
# ==========================================================

def get_nba_video_assets(game_id, player_id):
    """שליפת קליפים ישירות מה-API הרשמי של NBA Stats"""
    step = "NBA_ASSETS"
    url = f"https://stats.nba.com/stats/videoeventsasset?GameID={game_id}&PlayerID={player_id}"
    
    try:
        log_step(step, f"מושך נכסי וידאו עבור שחקן {player_id} במשחק {game_id}")
        response = requests.get(url, headers=NBA_STATS_HEADERS, timeout=15)
        
        if response.status_code != 200:
            log_error(step, f"שגיאת API: {response.status_code}")
            return []

        data = response.json()
        # שליפת ה-URLs מתוך המבנה של NBA Stats
        video_urls = data.get('resultSets', {}).get('Meta', {}).get('videoUrls', [])
        
        valid_clips = []
        for vid in video_urls:
            # lhigh בד"כ מייצג 720p או 1080p
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
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    try:
        with open(video_path, "rb") as f:
            r = requests.post(
                url,
                data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                files={"video": f},
                timeout=180
            )
        return r.status_code == 200
    except Exception as e:
        log_error(step, f"כשל בשליחת קובץ: {e}")
        return False

# ==========================================================
# VIDEO CONCATENATION ENGINE
# ==========================================================

def build_merged_highlights(game_id, game_date, player_id, player_name, stats_line):
    """מחבר קליפים לסרטון אחד אם נמצאו מספר נכסים"""
    step = f"MERGE_{player_name}"
    
    # שלב 1: נסיון לשלוף מה-Assets API
    asset_urls = get_nba_video_assets(game_id, player_id)
    
    if not asset_urls:
        log_warn(step, "לא נמצאו נכסים ב-Stats API, מנסה שיטה חלופית...")
        # כאן אפשר להוסיף את הלוגיקה הישנה כגיבוי במידת הצורך
        return None

    clips = []
    temp_files = []
    
    try:
        # הורדת מקסימום 12 קליפים כדי לא לחרוג מזכרון
        for i, url in enumerate(asset_urls[:12]):
            try:
                r = requests.get(url, headers=GENERAL_HEADERS, timeout=10)
                if r.status_code == 200:
                    fname = f"t_{player_id}_{i}.mp4"
                    with open(fname, "wb") as f:
                        f.write(r.content)
                    clip = VideoFileClip(fname)
                    clips.append(clip)
                    temp_files.append(fname)
            except:
                continue

        if not clips:
            return None

        output = f"final_{player_id}_{game_id}.mp4"
        final_video = concatenate_videoclips(clips, method="compose")
        final_video.write_videofile(output, codec="libx264", audio=True, logger=None)
        
        # ניקוי
        final_video.close()
        for c in clips: c.close()
        for f in temp_files:
            if os.path.exists(f): os.remove(f)
            
        caption = f"{'🇮🇱' if player_id in ISRAELI_PLAYERS else '🔥'} <b>ביצועי {player_name} מהלילה!</b>\n📊 {stats_line}"
        return output, caption

    except Exception as e:
        log_error(step, f"שגיאה בתהליך החיבור: {e}")
        return None

# ==========================================================
# GAME ANALYTICS & CORE LOGIC
# ==========================================================

def process_nba_games(check_35=False):
    step = "CORE_SCAN"
    log_step(step, "מבצע סריקת נתונים עמוקה...")

    try:
        # קבלת לוח התוצאות
        sb_url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
        resp = requests.get(sb_url, headers=GENERAL_HEADERS, timeout=15)
        if resp.status_code != 200: return

        games = resp.json().get("scoreboard", {}).get("games", [])
        
        for g in games:
            # סטטוס 3 = משחק הסתיים
            if g.get("gameStatus") != 3: continue
            
            gid = g["gameId"]
            g_date = g.get("gameDate")
            home_team = g.get("homeTeam", {}).get("teamName")
            
            # שליפת BoxScore
            box_url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
            box_resp = requests.get(box_url, headers=GENERAL_HEADERS, timeout=15)
            if box_resp.status_code != 200: continue
            
            box_data = box_resp.json().get("game", {})
            home_players = box_data.get("homeTeam", {}).get("players", [])
            away_players = box_data.get("awayTeam", {}).get("players", [])
            all_players = home_players + away_players

            # מציאת הכוכב של הבית (למקרה שצריך פוסטר/התמקדות)
            home_star = max(home_players, key=lambda x: x.get("statistics", {}).get("points", 0)) if home_players else None

            for p in all_players:
                stats = p.get("statistics", {})
                pid = str(p.get("personId", ""))
                pts = stats.get("points", 0)
                
                # תנאי סף: ישראלי או 35+ נקודות
                is_israeli = pid in ISRAELI_PLAYERS
                is_beast = (check_35 and pts >= 35)

                if (is_israeli or is_beast) and pid not in SENT_TODAY:
                    name = ISRAELI_PLAYERS.get(pid, f"{p.get('firstName')} {p.get('familyName')}")
                    log_step(step, f"מטרה זוהתה: {name} עם {pts} נקודות")

                    stats_str = f"{pts} נק', {stats.get('reboundsTotal')} רב', {stats.get('assists')} אס'"
                    
                    # ניסיון ליצור סרטון מחובר
                    result = build_merged_highlights(gid, g_date, pid, name, stats_str)
                    
                    if result:
                        v_file, caption = result
                        if send_video_file(v_file, caption):
                            SENT_TODAY.add(pid)
                            log_step(step, f"שחקן {name} נשלח לקבוצה בהצלחה.")
                        if os.path.exists(v_file): os.remove(v_file)
                    else:
                        # אם החיבור נכשל, ננסה לפחות לשלוח את המהלך הכי טוב ב-URL ישיר
                        assets = get_nba_video_assets(gid, pid)
                        if assets:
                            caption = f"🏀 מהלך נבחר: <b>{name}</b>\n📊 {stats_str}"
                            if send_video_by_url(assets[0], caption):
                                SENT_TODAY.add(pid)
                                log_step(step, f"נשלח מהלך בודד עבור {name}")

    except Exception as e:
        log_error(step, f"שגיאה כללית בעיבוד: {e}")

# ==========================================================
# MONITORING LOOP
# ==========================================================

def start_monitor():
    global LAST_MORNING_RUN
    log_step("SYSTEM", "מנטר NBA הופעל בהצלחה.")
    
    # הרצה ראשונה מיידית
    process_nba_games(check_35=True)

    while True:
        try:
            now = datetime.now(israel_tz)
            
            # איפוס יומי ב-13:00 בצהריים
            if now.hour == 13 and now.minute < 10:
                SENT_TODAY.clear()
                log_step("SYSTEM", "רשימת SENT_TODAY אופסה.")
                time.sleep(600)

            # בדיקה שוטפת (כל 10 דקות)
            process_nba_games(check_35=True)
            
            # ניקוי זכרון אגרסיבי
            gc.collect()
            time.sleep(600)

        except Exception as e:
            log_error("MAIN_LOOP", f"שגיאה בלולאה: {e}")
            time.sleep(60)

if __name__ == "__main__":
    start_monitor()

# ==========================================================
# END OF CODE - TOTAL LINES MAINTAINED FOR STABILITY
# ==========================================================

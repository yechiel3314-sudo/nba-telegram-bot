import requests
import time
import os
import gc
import logging
from datetime import datetime
import pytz
from moviepy.editor import VideoFileClip, concatenate_videoclips

# ==========================================================
# CONFIG
# ==========================================================

TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# רשימת הישראלים למעקב צמוד
ISRAELI_PLAYERS = {
    "1630166": "דני אבדיה",
    "1642234": "בן שרף",
    "1642300": "דני וולף"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.nba.com/"
}

SENT_TODAY = set()
LAST_MORNING_RUN = None
israel_tz = pytz.timezone("Asia/Jerusalem")

# ==========================================================
# LOGGING
# ==========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

def log_step(step, message):
    logging.info(f"[{step}] ✅ {message}")

def log_error(step, message):
    logging.error(f"[{step}] ❌ {message}")

# ==========================================================
# TELEGRAM
# ==========================================================

def send_video(video_path, caption):
    step = "TELEGRAM_SEND"
    log_step(step, f"מכין שליחה של וידאו: {video_path}")

    if not os.path.exists(video_path):
        log_error(step, "קובץ הוידאו לא נמצא על השרת.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"

    for attempt in range(1, 4):
        try:
            with open(video_path, "rb") as f:
                r = requests.post(
                    url,
                    data={
                        "chat_id": CHAT_ID,
                        "caption": caption,
                        "parse_mode": "HTML"
                    },
                    files={"video": f},
                    timeout=180
                )

            if r.status_code == 200:
                log_step(step, "הוידאו נשלח בהצלחה לטלגרם!")
                return True
            else:
                log_error(step, f"שגיאת טלגרם: {r.text}")

        except Exception as e:
            log_error(step, f"ניסיון שליחה {attempt} נכשל: {e}")

        time.sleep(5)

    return False

# ==========================================================
# BUILD HIGHLIGHTS
# ==========================================================

def build_highlights(game_id, game_date, player_id, player_name, stats_line):
    step = f"HIGHLIGHTS_{player_name}"
    log_step(step, f"מתחיל איסוף מהלכים עבור {player_name}")

    pbp_url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json"

    try:
        r = requests.get(pbp_url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            log_error(step, f"לא הצלחתי למשוך נתוני מהלכים (סטטוס {r.status_code})")
            return None

        actions = r.json().get("game", {}).get("actions", [])
        log_step(step, f"נמצאו {len(actions)} פעולות במשחק. מסנן מהלכים של השחקן...")

        clips = []
        temp_files = []

        for action in actions:
            event_id = action.get("actionId")
            pid = str(action.get("personId", ""))
            ast = str(action.get("assistPersonId", ""))
            is_fg = action.get("isFieldGoal")

            if event_id and (pid == player_id or ast == player_id) and is_fg:
                video_url = f"https://videos.nba.com/nba/pbp/media/{game_date}/{game_id}/{event_id}/720p.mp4"
                
                try:
                    rv = requests.get(video_url, headers=HEADERS, timeout=15)
                    if rv.status_code == 200:
                        fname = f"temp_{player_id}_{event_id}.mp4"
                        with open(fname, "wb") as f:
                            f.write(rv.content)

                        clip = VideoFileClip(fname)
                        clips.append(clip)
                        temp_files.append(fname)
                        log_step(step, f"קליפ {event_id} הורד בהצלחה")
                    else:
                        continue # הוידאו הספציפי עוד לא מוכן
                except Exception as e:
                    log_error(step, f"שגיאה בהורדת קליפ {event_id}: {e}")

            if len(clips) >= 15: # הגבלה ל-15 מהלכים כדי לא להכביד
                break

        if not clips:
            log_error(step, f"לא נמצאו קליפים זמינים להורדה כרגע עבור {player_name}")
            return None

        log_step(step, f"מחבר {len(clips)} קליפים לסרטון אחד...")
        final = concatenate_videoclips(clips, method="compose")
        output = f"highlights_{player_id}.mp4"
        final.write_videofile(output, codec="libx264", audio=True, logger=None)

        # ניקוי זיכרון
        final.close()
        for c in clips:
            c.close()
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)

        caption = f"{'🇮🇱' if player_id in ISRAELI_PLAYERS else '🔥'} <b>ביצועי {player_name} מהלילה!</b>\n📊 {stats_line}"
        log_step(step, "הסרטון מוכן ומחכה לשליחה")
        gc.collect()
        return output, caption

    except Exception as e:
        log_error(step, f"שגיאה קריטית ביצירת ההיילייטס: {e}")
        return None

# ==========================================================
# PROCESS GAMES
# ==========================================================

def process_games(check_35=False):
    step = "SCOREBOARD_SCAN"
    log_step(step, "מתחיל סריקת משחקים...")

    try:
        url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
        resp = requests.get(url, headers=HEADERS, timeout=20)

        if resp.status_code != 200:
            log_error(step, "כשל במשיכת לוח התוצאות")
            return

        games = resp.json().get("scoreboard", {}).get("games", [])
        log_step(step, f"נמצאו {len(games)} משחקים בלוח.")

        for g in games:
            # סטטוס 3 אומר שהמשחק הסתיים
            if g.get("gameStatus") != 3:
                continue

            gid = g["gameId"]
            game_date = g.get("gameDate")
            log_step(step, f"בודק סטטיסטיקות למשחק {gid}")

            box_url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
            box_resp = requests.get(box_url, headers=HEADERS, timeout=20)
            if box_resp.status_code != 200:
                continue
                
            box = box_resp.json().get("game", {})
            players = box.get("homeTeam", {}).get("players", []) + box.get("awayTeam", {}).get("players", [])

            for p in players:
                s = p.get("statistics", {})
                pid = str(p.get("personId", ""))
                points = s.get("points", 0)

                is_israeli = pid in ISRAELI_PLAYERS
                
                # תנאי סף: ישראלי או מעל 35 נקודות
                if not is_israeli and not (check_35 and points >= 35):
                    continue

                # אם כבר שלחנו אותו בהצלחה היום - דלג
                if pid in SENT_TODAY:
                    continue

                name = ISRAELI_PLAYERS.get(pid, f"{p.get('firstName','')} {p.get('familyName','')}")
                reb = s.get("reboundsTotal", 0)
                ast = s.get("assists", 0)
                stats_line = f"{points} נק', {reb} רב', {ast} אס'"

                log_step(step, f"נמצאה מטרה: {name} ({points} נקודות)")

                result = build_highlights(gid, game_date, pid, name, stats_line)

                if result:
                    vid, cap = result
                    if send_video(vid, cap):
                        SENT_TODAY.add(pid) # מסמן כנשלח רק אם באמת נשלח לטלגרם
                        log_step(step, f"הסתיים הטיפול בשחקן {name}")
                    if os.path.exists(vid):
                        os.remove(vid)
                else:
                    # אם result הוא None, זה אומר שהוידאו לא היה מוכן. 
                    # אנחנו לא מוסיפים ל-SENT_TODAY כדי שהבוט ינסה שוב בסבב הבא!
                    log_step(step, f"הוידאו של {name} עדיין לא מוכן בשרתי ה-NBA. ננסה שוב בסריקה הבאה.")

    except Exception as e:
        log_error(step, f"שגיאה כללית בסריקת הלוח: {e}")

# ==========================================================
# MAIN LOOP
# ==========================================================

def run_bot():
    global LAST_MORNING_RUN
    logging.info("==========================================")
    logging.info("NBA HIGHLIGHTS BOT - STARTED")
    logging.info("==========================================")

    # הרצה ראשונה מיידית עם עליית הקוד
    log_step("STARTUP", "מבצע סריקה ראשונית על הלילה האחרון...")
    process_games(check_35=True)

    last_israeli_check = 0

    while True:
        try:
            now = datetime.now(israel_tz)

            # איפוס רשימת ה"נשלחו" ב-13:00 בצהריים (זמן ישראל) לקראת הלילה הבא
            if now.hour == 13 and now.minute < 5:
                SENT_TODAY.clear()
                log_step("RESET", "התבצע איפוס יומי לרשימת השחקנים.")
                time.sleep(300)

            # סריקת בוקר יסודית לכל מי שקלע 35+
            if now.hour == 10 and now.minute < 5:
                if LAST_MORNING_RUN != now.date():
                    log_step("MORNING_SCAN", "מריץ סריקת 35+ נקודות...")
                    process_games(check_35=True)
                    LAST_MORNING_RUN = now.date()

            # בדיקה שוטפת לישראלים (כל 15 דקות)
            if time.time() - last_israeli_check > 120:
                log_step("ROUTINE_SCAN", "בודק אם יש עדכונים על השחקנים הישראלים...")
                process_games(check_35=True) # שיניתי ל-True כדי שגם יוקיץ' ייתפס אם הוידאו שלו התפנה
                last_israeli_check = time.time()

            time.sleep(30) # המתנה בין בדיקות לולאה

        except Exception as e:
            log_error("MAIN_LOOP", f"שגיאה בלולאה הראשית: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_bot()

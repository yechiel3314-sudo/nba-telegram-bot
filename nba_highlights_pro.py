import requests
import time
import os
import gc
import logging
from datetime import datetime
import pytz
from moviepy.editor import VideoFileClip, concatenate_videoclips

# ==========================================================
# CONFIGURATION
# ==========================================================

TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
RAPID_API_KEY = "7979ea3becmsh0ff9ea48063fda2p14bc4bjsn965773ad1338" # המפתח שלך מהתמונה

ISRAELI_PLAYERS = {
    "1630166": "דני אבדיה",
    "1642234": "בן שרף",
    "1642300": "דני וולף"
}

# זיהוי לפי שם למקרה שה-ID בברוקלין משתנה
ISRAELI_NAMES = ["Ben Saraf", "Danny Wolf", "Deni Avdija"]

SENT_TODAY = set()
israel_tz = pytz.timezone("Asia/Jerusalem")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

def log_status(status, message):
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "ERROR": "❌", "WAIT": "⏳", "SCAN": "🔍"}
    logging.info(f"{icons.get(status, '🔹')} [{status}] {message}")

# ==========================================================
# FUNCTIONS (API & VIDEO)
# ==========================================================

def get_highlights(player_id, game_id, player_name):
    url = "https://nba-highlights-api.p.rapidapi.com/highlights"
    querystring = {"player_id": str(player_id), "game_id": str(game_id)}
    headers = {
        "X-RapidAPI-Key": RAPID_API_KEY,
        "X-RapidAPI-Host": "nba-highlights-api.p.rapidapi.com"
    }
    
    log_status("SCAN", f"בודק ב-API אם קיימים קליפים עבור {player_name}...")
    
    try:
        response = requests.get(url, headers=headers, params=querystring, timeout=30)
        data = response.json()
        videos = data.get("videos", [])
        
        if videos:
            log_status("SUCCESS", f"נמצאו {len(videos)} קליפים ב-API ל-{player_name}!")
        else:
            log_status("INFO", f"ה-API החזיר 0 קטעי וידאו ל-{player_name} (למרות שהמשחק הסתיים).")
            
        return videos
    except Exception as e:
        log_status("ERROR", f"שגיאה בתקשורת עם ה-API: {e}")
        return []

def create_video(player_id, player_name, video_list):
    clips, temp_files = [], []
    try:
        total = len(video_list[:12])
        log_status("WAIT", f"מתחיל הורדה של {total} קליפים עבור {player_name}...")
        
        for i, v in enumerate(video_list[:12]):
            v_url = v.get("url")
            if not v_url: continue
            
            # לוג התקדמות הורדה
            if i % 3 == 0 and i > 0: 
                log_status("WAIT", f"הורדו {i}/{total} קליפים ל-{player_name}...")

            r = requests.get(v_url, stream=True)
            fname = f"tmp_{player_id}_{i}.mp4"
            with open(fname, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024*1024): f.write(chunk)
            clips.append(VideoFileClip(fname))
            temp_files.append(fname)
        
        if not clips: return None
        
        log_status("WAIT", f"מעבד ומחבר את הסרטון הסופי של {player_name} (זה עשוי לקחת דקה)...")
        
        output = f"{player_id}.mp4"
        final = concatenate_videoclips(clips, method="compose")
        final.write_videofile(output, codec="libx264", audio=True, logger=None)
        
        # ניקוי משאבים
        final.close()
        for c in clips: c.close()
        for f in temp_files: os.remove(f)
        
        log_status("SUCCESS", f"הקובץ המוכן של {player_name} נוצר בהצלחה!")
        return output
    except Exception as e:
        log_status("ERROR", f"שגיאה בזמן יצירת הוידאו של {player_name}: {e}")
        return None

# ==========================================================
# MAIN BOT LOGIC
# ==========================================================

def run_bot():
    log_status("SCAN", "בודק משחקים...")
    sb_url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
    try:
        resp = requests.get(sb_url, timeout=20).json()
        games = resp.get("scoreboard", {}).get("games", [])
    except: return

    for g in games:
        gid = g["gameId"]
        if g.get("gameStatus") < 2: continue 

        box_url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
        try:
            box = requests.get(box_url).json().get("game", {})
            # איחוד כל שחקני הבית והחוץ לסריקה אחת
            all_players = box.get("homeTeam", {}).get("players", []) + box.get("awayTeam", {}).get("players", [])
        except: continue

        for p in all_players:
            pid = str(p.get("personId"))
            f_name = p.get("firstName", "")
            l_name = p.get("familyName", "")
            full_en = f"{f_name} {l_name}"
            
            # בדיקה: האם זה ישראלי שלנו? (לפי ID או שם)
            if (pid in ISRAELI_PLAYERS or any(n in full_en for n in ISRAELI_NAMES)) and f"{pid}_{gid}" not in SENT_TODAY:
                stats = p.get("statistics", {})
                name_heb = ISRAELI_PLAYERS.get(pid, full_en)

                if stats.get("points", 0) == 0 and stats.get("assists", 0) == 0:
                    continue

                log_status("SUCCESS", f"ביצוע של {name_heb} זוהה!")
                v_list = get_highlights(pid, gid, name_heb)
                
                if v_list:
                    res_path = create_video(pid, name_heb, v_list)
                    
                    if res_path:
                        log_status("WAIT", f"מעלה את הסרטון של {name_heb} לטלגרם עכשיו...")
                        
                        cap = f"🇮🇱 <b>{name_heb}</b>\n📊 {stats['points']} נק', {stats['reboundsTotal']} רב', {stats['assists']} אס'"
                        try:
                            with open(res_path, "rb") as vf:
                                requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo",
                                             data={"chat_id": CHAT_ID, "caption": cap, "parse_mode": "HTML"},
                                             files={"video": vf})
                            
                            SENT_TODAY.add(f"{pid}_{gid}")
                            log_status("SUCCESS", f"נשלח בהצלחה! השחקן {name_heb} עודכן במערכת.")
                        except Exception as e:
                            log_status("ERROR", f"כשל בשליחה הסופית: {e}")
                        
                        if os.path.exists(res_path):
                            os.remove(res_path)
                            
                    
def main():
    log_status("INFO", "הבוט רץ: אבדיה, שרף ווולף.")
    while True:
        try:
            if datetime.now(israel_tz).hour == 14: SENT_TODAY.clear()
            run_bot()
            gc.collect() # מניעת קריסת RAM ב-Railway
            time.sleep(900)
        except Exception as e:
            log_status("ERROR", f"שגיאה: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()

import requests
import time
import os
import gc
import logging
from datetime import datetime
import pytz
from moviepy.editor import VideoFileClip, concatenate_videoclips

# ==========================================================
# CONFIGURATION - הגדרות (ישראלים בלבד)
# ==========================================================

TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
RAPID_API_KEY = "YOUR_API_KEY_HERE" # הכנס כאן את המפתח שקיבלת

# רשימת המעקב הבלעדית - למניעת חריגה מהמכסה
ISRAELI_PLAYERS = {
    "1630166": "דני אבדיה",
    "1642234": "בן שרף",
    "1642300": "דני וולף"
}

SENT_TODAY = set()
israel_tz = pytz.timezone("Asia/Jerusalem")

# הגדרת לוגים מפורטת
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

def log_status(status, message):
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "ERROR": "❌", "WAIT": "⏳", "SCAN": "🔍"}
    logging.info(f"{icons.get(status, '🔹')} [{status}] {message}")

# ==========================================================
# RAPID-API ENGINE - שליפת מהלכים
# ==========================================================

def get_highlights(player_id, game_id, player_name):
    url = "https://nba-highlights-api.p.rapidapi.com/highlights"
    querystring = {"player_id": player_id, "game_id": game_id}
    headers = {
        "X-RapidAPI-Key": RAPID_API_KEY,
        "X-RapidAPI-Host": "nba-highlights-api.p.rapidapi.com"
    }
    
    log_status("WAIT", f"פונה ל-RapidAPI עבור {player_name}...")
    try:
        response = requests.get(url, headers=headers, params=querystring, timeout=30)
        if response.status_code == 200:
            videos = response.json().get("videos", [])
            log_status("SUCCESS", f"נמצאו {len(videos)} קליפים עבור {player_name}")
            return videos
        else:
            log_status("ERROR", f"RapidAPI החזיר שגיאה {response.status_code} עבור {player_name}")
            return []
    except Exception as e:
        log_status("ERROR", f"נכשלה הפנייה ל-RapidAPI: {str(e)}")
        return []

# ==========================================================
# VIDEO ENGINE - יצירת הסרטון המאוחד
# ==========================================================

def create_video(player_id, player_name, video_list):
    clips = []
    temp_files = []
    log_status("WAIT", f"מתחיל הורדת {len(video_list[:12])} קליפים וחיבורם עבור {player_name}...")
    
    try:
        for i, v in enumerate(video_list[:12]):
            v_url = v.get("url")
            if not v_url: continue
            
            r = requests.get(v_url, stream=True)
            fname = f"tmp_{player_id}_{i}.mp4"
            with open(fname, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    f.write(chunk)
            
            clips.append(VideoFileClip(fname))
            temp_files.append(fname)

        if not clips: 
            log_status("ERROR", f"לא הצלחתי להוריד אף קליפ עבור {player_name}")
            return None

        output = f"{player_id}.mp4"
        final = concatenate_videoclips(clips, method="compose")
        final.write_videofile(output, codec="libx264", audio=True, logger=None)
        
        log_status("SUCCESS", f"הסרטון המלא של {player_name} מוכן!")
        
        # ניקוי משאבים למניעת קריסת RAM
        final.close()
        for c in clips: c.close()
        for f in temp_files: os.remove(f)
        
        return output
    except Exception as e:
        log_status("ERROR", f"שגיאה בתהליך העריכה של {player_name}: {str(e)}")
        return None

# ==========================================================
# SCANNER - סריקה ממוקדת ישראלים
# ==========================================================

def run_bot():
    log_status("SCAN", "בודק לוח משחקים ב-NBA...")
    sb_url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
    
    try:
        resp = requests.get(sb_url, timeout=20).json()
        games = resp.get("scoreboard", {}).get("games", [])
    except Exception as e:
        log_status("ERROR", f"לא ניתן לגשת ללוח המשחקים: {str(e)}")
        return

    for g in games:
        gid = g["gameId"]
        if g.get("gameStatus") < 2: continue # דלג על משחקים שלא התחילו

        box_url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
        try:
            box = requests.get(box_url).json().get("game", {})
            players = box.get("homeTeam", {}).get("players", []) + box.get("awayTeam", {}).get("players", [])
        except: continue

        for p in players:
            pid = str(p.get("personId"))
            
            # בדיקה אם זה אחד משלושת הישראלים
            if pid in ISRAELI_PLAYERS and f"{pid}_{gid}" not in SENT_TODAY:
                stats = p.get("statistics", {})
                name = ISRAELI_PLAYERS[pid]
                
                # בדיקה אם השחקן באמת עלה על המגרש
                if stats.get("points", 0) == 0 and stats.get("assists", 0) == 0:
                    log_status("INFO", f"{name} ברשימה אך לא רשם סטטיסטיקה עדיין.")
                    continue

                log_status("SUCCESS", f"זוהה ביצוע של {name}! מפיק היילייטס...")
                v_list = get_highlights(pid, gid, name)
                
                if v_list:
                    res_path = create_video(pid, name, v_list)
                    if res_path:
                        cap = f"🇮🇱 <b>{name}</b>\n📊 {stats['points']} נק', {stats['reboundsTotal']} רב', {stats['assists']} אס'"
                        try:
                            with open(res_path, "rb") as vf:
                                requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo",
                                             data={"chat_id": CHAT_ID, "caption": cap, "parse_mode": "HTML"},
                                             files={"video": vf})
                            log_status("SUCCESS", f"סרטון של {name} נשלח לטלגרם!")
                            SENT_TODAY.add(f"{pid}_{gid}")
                        except Exception as e:
                            log_status("ERROR", f"כשל בשליחת הוידאו לטלגרם: {str(e)}")
                        
                        if os.path.exists(res_path): os.remove(res_path)

def main():
    log_status("INFO", "הבוט הופעל. סורק את: אבדיה, שרף ווולף בלבד.")
    while True:
        try:
            # איפוס רשימת השליחה בצהריים
            if datetime.now(israel_tz).hour == 14: 
                SENT_TODAY.clear()
                log_status("INFO", "איפוס מכסה יומית של הבוט.")

            run_bot()
            gc.collect() # ניקוי זיכרון RAM
            time.sleep(900) # סריקה כל 15 דקות לחיסכון במכסה
        except Exception as e:
            log_status("ERROR", f"שגיאה בלופ הראשי: {str(e)}")
            time.sleep(60)

if __name__ == "__main__":
    main()

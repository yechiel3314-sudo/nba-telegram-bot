import requests
import time
import os
import gc
from datetime import datetime, timedelta
import pytz
from moviepy.editor import VideoFileClip, concatenate_videoclips

# ==========================================
# CONFIG
# ==========================================

TELEGRAM_TOKEN = "PUT_YOUR_TOKEN"
CHAT_ID = "PUT_YOUR_CHAT_ID"

ISRAELI_PLAYERS = {
    "1630166": "דני אבדיה",
    "1642234": "בן שרף",
    "1642300": "דני וולף"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

SENT_TODAY = set()
LAST_MORNING_RUN = None

israel_tz = pytz.timezone("Asia/Jerusalem")

# ==========================================
# TELEGRAM
# ==========================================

def send_video_to_telegram(video_path, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    
    for attempt in range(3):
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
                return True
            else:
                print("Telegram error:", r.text)
        except Exception as e:
            print("Telegram attempt failed:", e)
        
        time.sleep(5)
    
    return False

# ==========================================
# HIGHLIGHTS
# ==========================================

def build_highlights(game_id, game_date, player_id, player_name, stats_line):
    pbp_url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json"
    
    try:
        r = requests.get(pbp_url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            print("Failed playbyplay")
            return None
        
        data = r.json()
        actions = data.get("game", {}).get("actions", [])
        
        clips = []
        temp_files = []
        
        for action in actions:
            event_id = action.get("actionId")
            p_id = str(action.get("personId", ""))
            ast_id = str(action.get("assistPersonId", ""))
            is_fg = action.get("isFieldGoal")
            
            if event_id and (p_id == player_id or ast_id == player_id) and is_fg:
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
                except Exception as e:
                    print("Clip error:", e)
            
            if len(clips) >= 15:
                break
        
        if not clips:
            print("No clips found")
            return None
        
        final = concatenate_videoclips(clips, method="compose")
        output_name = f"highlights_{player_id}.mp4"
        final.write_videofile(output_name, codec="libx264", audio=True, logger=None)
        
        final.close()
        for c in clips:
            c.close()
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)
        
        prefix = "🇮🇱" if player_id in ISRAELI_PLAYERS else "🔥"
        caption = f"{prefix} <b>ביצועי {player_name} מהלילה!</b> {prefix}\n📊 {stats_line}"
        
        gc.collect()
        return output_name, caption
    
    except Exception as e:
        print("Build error:", e)
        return None

# ==========================================
# SCOREBOARD
# ==========================================

def process_games(check_all=False):
    scoreboard_url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
    
    try:
        resp = requests.get(scoreboard_url, headers=HEADERS, timeout=15).json()
        games = resp.get("scoreboard", {}).get("games", [])
        
        for g in games:
            if g.get("gameStatus") != 3:
                continue
            
            gid = g["gameId"]
            game_date = g.get("gameDate")
            
            box_url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
            box_resp = requests.get(box_url, headers=HEADERS, timeout=15).json()
            box = box_resp.get("game", {})
            
            players = (
                box.get("homeTeam", {}).get("players", []) +
                box.get("awayTeam", {}).get("players", [])
            )
            
            for p in players:
                s = p.get("statistics", {})
                p_id = str(p.get("personId", ""))
                points = s.get("points", 0)
                
                is_israeli = p_id in ISRAELI_PLAYERS
                
                should_send = False
                
                if is_israeli:
                    should_send = True
                elif check_all and points >= 35:
                    should_send = True
                
                if not should_send:
                    continue
                
                if p_id in SENT_TODAY:
                    continue
                
                first = p.get("firstName", "")
                last = p.get("familyName", "")
                display_name = ISRAELI_PLAYERS.get(p_id, f"{first} {last}")
                
                reb = s.get("reboundsTotal", 0)
                ast = s.get("assists", 0)
                
                stats_line = f"{points} נק', {reb} רב', {ast} אס'"
                
                print("Processing:", display_name)
                
                result = build_highlights(gid, game_date, p_id, display_name, stats_line)
                
                if result:
                    vid, cap = result
                    if send_video_to_telegram(vid, cap):
                        SENT_TODAY.add(p_id)
                        print("Sent:", display_name)
                    
                    if os.path.exists(vid):
                        os.remove(vid)
    
    except Exception as e:
        print("Scoreboard error:", e)

# ==========================================
# INITIAL NIGHT CHECK
# ==========================================

def check_last_night():
    print("Running last night full scan...")
    process_games(check_all=True)

# ==========================================
# MAIN LOOP
# ==========================================

def run_bot():
    global LAST_MORNING_RUN
    
    print("NBA Highlights Bot Started")
    
    check_last_night()
    
    last_israeli_check = 0
    
    while True:
        now = datetime.now(israel_tz)
        
        # איפוס יומי ב-13:00
        if now.hour == 13 and now.minute < 5:
            SENT_TODAY.clear()
        
        # סריקת בוקר 10:00 פעם ביום
        if now.hour == 10 and now.minute < 5:
            if LAST_MORNING_RUN != now.date():
                print("Morning full scan")
                process_games(check_all=True)
                LAST_MORNING_RUN = now.date()
        
        # ישראלים כל 15 דקות
        if time.time() - last_israeli_check > 900:
            print("Israeli scan")
            process_games(check_all=False)
            last_israeli_check = time.time()
        
        time.sleep(20)

# ==========================================

if __name__ == "__main__":
    run_bot()

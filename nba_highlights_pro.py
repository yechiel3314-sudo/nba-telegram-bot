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

TELEGRAM_TOKEN = "PUT_TOKEN"
CHAT_ID = "PUT_CHAT_ID"

ISRAELI_PLAYERS = {
    "1630166": "דני אבדיה",
    "1642234": "בן שרף",
    "1642300": "דני וולף"
}

HEADERS = {"User-Agent": "Mozilla/5.0"}
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
    logging.info(f"[{step}] {message}")

def log_error(step, message):
    logging.error(f"[{step}] {message}")

# ==========================================================
# TELEGRAM
# ==========================================================

def send_video(video_path, caption):
    step = "TELEGRAM_SEND"
    log_step(step, f"Preparing to send video {video_path}")

    if not os.path.exists(video_path):
        log_error(step, "Video file not found.")
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
                log_step(step, "Video sent successfully.")
                return True
            else:
                log_error(step, f"Telegram error: {r.text}")

        except Exception as e:
            log_error(step, f"Attempt {attempt} failed: {e}")

        time.sleep(5)

    return False

# ==========================================================
# BUILD HIGHLIGHTS
# ==========================================================

def build_highlights(game_id, game_date, player_id, player_name, stats_line):
    step = f"HIGHLIGHTS_{player_name}"
    log_step(step, "Fetching playbyplay data")

    pbp_url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json"

    try:
        r = requests.get(pbp_url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            log_error(step, "Failed to fetch playbyplay")
            return None

        actions = r.json().get("game", {}).get("actions", [])
        log_step(step, f"Total actions found: {len(actions)}")

        clips = []
        temp_files = []

        for action in actions:
            event_id = action.get("actionId")
            pid = str(action.get("personId", ""))
            ast = str(action.get("assistPersonId", ""))
            is_fg = action.get("isFieldGoal")

            if event_id and (pid == player_id or ast == player_id) and is_fg:
                video_url = f"https://videos.nba.com/nba/pbp/media/{game_date}/{game_id}/{event_id}/720p.mp4"
                log_step(step, f"Downloading clip {event_id}")

                try:
                    rv = requests.get(video_url, headers=HEADERS, timeout=15)
                    if rv.status_code == 200:
                        fname = f"temp_{player_id}_{event_id}.mp4"
                        with open(fname, "wb") as f:
                            f.write(rv.content)

                        clip = VideoFileClip(fname)
                        clips.append(clip)
                        temp_files.append(fname)
                    else:
                        log_error(step, f"Clip not available {event_id}")

                except Exception as e:
                    log_error(step, f"Clip error {event_id}: {e}")

            if len(clips) >= 15:
                break

        if not clips:
            log_error(step, "No valid clips found.")
            return None

        log_step(step, f"Concatenating {len(clips)} clips")
        final = concatenate_videoclips(clips, method="compose")
        output = f"highlights_{player_id}.mp4"
        final.write_videofile(output, codec="libx264", audio=True, logger=None)

        final.close()
        for c in clips:
            c.close()

        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)

        caption = f"{'🇮🇱' if player_id in ISRAELI_PLAYERS else '🔥'} <b>ביצועי {player_name} מהלילה!</b>\n📊 {stats_line}"

        log_step(step, "Video built successfully")
        gc.collect()
        return output, caption

    except Exception as e:
        log_error(step, f"Fatal highlight error: {e}")
        return None

# ==========================================================
# PROCESS GAMES
# ==========================================================

def process_games(check_35=False):
    step = "SCOREBOARD"
    log_step(step, "Fetching scoreboard")

    try:
        url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
        resp = requests.get(url, headers=HEADERS, timeout=20)

        if resp.status_code != 200:
            log_error(step, "Failed scoreboard fetch")
            return

        games = resp.json().get("scoreboard", {}).get("games", [])
        log_step(step, f"Games found: {len(games)}")

        for g in games:
            if g.get("gameStatus") != 3:
                continue

            gid = g["gameId"]
            game_date = g.get("gameDate")

            log_step(step, f"Processing game {gid}")

            box_url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
            box = requests.get(box_url, headers=HEADERS, timeout=20).json().get("game", {})

            players = box.get("homeTeam", {}).get("players", []) + box.get("awayTeam", {}).get("players", [])

            for p in players:
                s = p.get("statistics", {})
                pid = str(p.get("personId", ""))
                points = s.get("points", 0)

                is_israeli = pid in ISRAELI_PLAYERS

                if not is_israeli and not (check_35 and points >= 35):
                    continue

                if pid in SENT_TODAY:
                    continue

                name = ISRAELI_PLAYERS.get(pid, f"{p.get('firstName','')} {p.get('familyName','')}")
                reb = s.get("reboundsTotal", 0)
                ast = s.get("assists", 0)
                stats_line = f"{points} נק', {reb} רב', {ast} אס'"

                log_step(step, f"Target found: {name}")

                result = build_highlights(gid, game_date, pid, name, stats_line)

                if result:
                    vid, cap = result
                    if send_video(vid, cap):
                        SENT_TODAY.add(pid)
                        log_step(step, f"Completed send for {name}")
                    if os.path.exists(vid):
                        os.remove(vid)

    except Exception as e:
        log_error(step, f"Scoreboard fatal error: {e}")

# ==========================================================
# MAIN LOOP
# ==========================================================

def run_bot():
    global LAST_MORNING_RUN

    logging.info("NBA BOT STARTED")

    # בדיקה מיידית על הלילה האחרון
    process_games(check_35=True)

    last_israeli_check = 0

    while True:
        now = datetime.now(israel_tz)

        # איפוס יומי
        if now.hour == 13 and now.minute < 5:
            SENT_TODAY.clear()
            log_step("RESET", "Daily reset complete")

        # סריקת בוקר 35+
        if now.hour == 10 and now.minute < 5:
            if LAST_MORNING_RUN != now.date():
                log_step("MORNING_SCAN", "Running 35+ scan")
                process_games(check_35=True)
                LAST_MORNING_RUN = now.date()

        # ישראלים כל 15 דקות
        if time.time() - last_israeli_check > 900:
            log_step("ISRAELI_SCAN", "Running Israeli scan")
            process_games(check_35=False)
            last_israeli_check = time.time()

        time.sleep(20)

# ==========================================================

if __name__ == "__main__":
    run_bot()

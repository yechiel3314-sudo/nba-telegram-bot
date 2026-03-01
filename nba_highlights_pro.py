import requests
import time
import os
import gc
from moviepy.editor import VideoFileClip, concatenate_videoclips
from deep_translator import GoogleTranslator

# הגדרות
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

ISRAELI_PLAYERS = {
    "1630166": "דני אבדיה",
    "1642234": "בן שרף",
    "1642300": "דני וולף"
}

# כותרת דפדפן כדי למנוע חסימות מ-Railway
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

PROCESSED_GAMES = set()
translator = GoogleTranslator(source='en', target='iw')

def get_player_highlights(game_id, player_id, player_name, is_israeli, stats_line):
    pbp_url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json"
    try:
        r_pbp = requests.get(pbp_url, headers=HEADERS)
        if r_pbp.status_code != 200: return None
        
        data = r_pbp.json()
        game_date = data['game']['gameEt'].split('T')[0].replace('-', '/')
        actions = data['game']['actions']
        
        video_clips = []
        temp_files = []

        for action in actions:
            p_id = str(action.get('personId'))
            ast_id = str(action.get('assistPersonId'))
            
            if (p_id == player_id or ast_id == player_id) and action.get('isFieldGoal') == 1:
                event_id = action['actionId']
                video_url = f"https://videos.nba.com/nba/pbp/media/{game_date}/{game_id}/{event_id}/720p.mp4"
                
                # ניסיון הורדה עם Headers
                r = requests.get(video_url, headers=HEADERS, timeout=5)
                if r.status_code == 200:
                    fname = f"temp_{player_id}_{event_id}.mp4"
                    with open(fname, 'wb') as f: f.write(r.content)
                    clip = VideoFileClip(fname)
                    video_clips.append(clip)
                    temp_files.append(fname)
            
            if len(video_clips) >= 15: break

        if not video_clips: return None

        final_video = concatenate_videoclips(video_clips, method="compose")
        output_name = f"highlights_{player_id}.mp4"
        final_video.write_videofile(output_name, codec="libx264", audio=True, logger=None)
        
        final_video.close()
        for clip in video_clips: clip.close()

        h_name = player_name if is_israeli else translator.translate(player_name)
        prefix = "🇮🇱" if is_israeli else "🔥"
        caption = f"{prefix} <b>ביצועי {h_name} מהלילה!</b> {prefix}\n📊 {stats_line}"

        for f in temp_files:
            if os.path.exists(f): os.remove(f)
        
        gc.collect()
        return output_name, caption

    except Exception as e:
        print(f"Error: {e}")
        return None

def run_highlights_hunter():
    print("🚀 הבוט תוקן ומתחיל לסרוק...")
    while True:
        try:
            resp = requests.get("https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json", headers=HEADERS).json()
            for g in resp['scoreboard']['games']:
                gid = g['gameId']
                
                if g['gameStatus'] == 3 and gid not in PROCESSED_GAMES:
                    box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json", headers=HEADERS).json()['game']
                    all_p = box['homeTeam']['players'] + box['awayTeam']['players']
                    
                    for p in all_p:
                        s = p['statistics']
                        p_id = str(p['personId'])
                        is_israeli = p_id in ISRAELI_PLAYERS
                        
                        if is_israeli or s['points'] >= 30 or s['assists'] >= 20:
                            p_name = ISRAELI_PLAYERS.get(p_id, f"{p['firstName']} {p['familyName']}")
                            stats = f"{s['points']} נק', {s['reboundsTotal']} רב', {s['assists']} אס'"
                            
                            res = get_player_highlights(gid, p_id, p_name, is_israeli, stats)
                            if res:
                                vid, cap = res
                                with open(vid, 'rb') as v:
                                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo", 
                                                  data={'chat_id': CHAT_ID, 'caption': cap, 'parse_mode': 'HTML'}, files={'video': v})
                                os.remove(vid)
                    
                    PROCESSED_GAMES.add(gid)
        except Exception as e:
            print(f"Loop Error: {e}")
        
        time.sleep(60)

if __name__ == "__main__":
    run_highlights_hunter()

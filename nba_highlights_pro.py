import requests
import time
import os
from moviepy.editor import VideoFileClip, concatenate_videoclips
from deep_translator import GoogleTranslator

# ==========================================
# הגדרות מערכת
# ==========================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

ISRAELI_PLAYERS = {
    "1630166": "דני אבדיה",
    "1642234": "בן שרף",
    "1642300": "דני וולף"
}

PROCESSED_GAMES = set()
translator = GoogleTranslator(source='en', target='iw')

def translate_name(name):
    """מתרגם שם שחקן לעברית אם הוא לא ישראלי מוכר"""
    try:
        return translator.translate(name)
    except:
        return name

def get_player_highlights(game_id, player_id, player_name, is_israeli, stats_line):
    """מוריד קליפים, מחבר ושולח"""
    pbp_url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json"
    try:
        r_pbp = requests.get(pbp_url)
        if r_pbp.status_code != 200: return None
        
        data = r_pbp.json()
        game_date = data['game']['gameEt'].split('T')[0].replace('-', '/')
        actions = data['game']['actions']
        
        video_clips = []
        temp_files = []

        for action in actions:
            # מוריד סלים או אסיסטים של השחקן
            if (str(action.get('personId')) == player_id or str(action.get('assistPersonId')) == player_id) and action.get('isFieldGoal') == 1:
                event_id = action['actionId']
                video_url = f"https://videos.nba.com/nba/pbp/media/{game_date}/{game_id}/{event_id}/720p.mp4"
                
                r = requests.get(video_url, timeout=10)
                if r.status_code == 200:
                    fname = f"temp_{player_id}_{event_id}.mp4"
                    with open(fname, 'wb') as f: f.write(r.content)
                    video_clips.append(VideoFileClip(fname))
                    temp_files.append(fname)
            
            if len(video_clips) >= 15: break

        if not video_clips: return None

        # חיבור הסרטון
        final_video = concatenate_videoclips(video_clips, method="compose")
        output_name = f"highlights_{player_id}.mp4"
        final_video.write_videofile(output_name, codec="libx264", audio=True)

        # כותרת ההודעה
        hebrew_name = player_name if is_israeli else translate_name(player_name)
        if is_israeli:
            caption = f"🇮🇱 <b>היילייטס: {hebrew_name} מהלילה!</b> 🇮🇱\n📊 סטטיסטיקה: {stats_line}"
        else:
            caption = f"🔥 <b>הופעת ענק ב-NBA!</b> 🔥\n👤 שחקן: {hebrew_name}\n📊 סטטיסטיקה: {stats_line}"

        # ניקוי
        for f in temp_files:
            if os.path.exists(f): os.remove(f)
            
        return output_name, caption

    except Exception as e:
        print(f"Error: {e}")
        return None

def run_highlights_hunter():
    print("🎯 צייד ההיילייטס פעיל 24/7 (ישראלים, 40+ נק', 20+ אס')...")
    while True:
        try:
            # בדיקת לוח משחקים
            resp = requests.get("https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json").json()
            for g in resp['scoreboard']['games']:
                gid = g['gameId']
                
                # אם המשחק הסתיים (סטטוס 3) ולא עובד עדיין
                if g['gameStatus'] == 3 and gid not in PROCESSED_GAMES:
                    box_url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
                    box_data = requests.get(box_url).json()['game']
                    all_players = box_data['homeTeam']['players'] + box_data['awayTeam']['players']
                    
                    for p in all_players:
                        p_id = str(p['personId'])
                        s = p['statistics']
                        is_israeli = p_id in ISRAELI_PLAYERS
                        # תנאי סף: ישראלי או 40 נקודות או 20 אסיסטים
                        if is_israeli or s['points'] >= 30 or s['assists'] >= 20:
                            p_full_name = f"{p['firstName']} {p['familyName']}"
                            p_display_name = ISRAELI_PLAYERS.get(p_id, p_full_name)
                            
                            stats = f"{s['points']} נק', {s['reboundsTotal']} רב', {s['assists']} אס'"
                            
                            res = get_player_highlights(gid, p_id, p_display_name, is_israeli, stats)
                            if res:
                                vid, cap = res
                                with open(vid, 'rb') as v:
                                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo", 
                                                  data={'chat_id': CHAT_ID, 'caption': cap, 'parse_mode': 'HTML'}, 
                                                  files={'video': v})
                                if os.path.exists(vid): os.remove(vid)
                    
                    PROCESSED_GAMES.add(gid)
        except Exception as e:
            print(f"Loop Error: {e}")
        
        time.sleep(60) # בדיקה כל 10 דקות (עובד כל היום)

if __name__ == "__main__":
    run_highlights_hunter()

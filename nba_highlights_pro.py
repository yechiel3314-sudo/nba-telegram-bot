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

def get_player_highlights(game_id, player_id, player_name, is_israeli, stats_line, home_star):
    """מוריד קליפים, מחבר אותם ושולח לטלגרם"""
    pbp_url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json"
    
    try:
        r_pbp = requests.get(pbp_url)
        if r_pbp.status_code != 200: return None
        
        data = r_pbp.json()
        actions = data['game']['actions']
        # חילוץ תאריך דינמי כדי למנוע שגיאות 404 מהלוגים הקודמים
        game_date = data['game']['gameEt'].split('T')[0].replace('-', '/')
        
        video_clips = []
        temp_files = []

        for action in actions:
            p_id = str(action.get('personId'))
            ast_id = str(action.get('assistPersonId'))
            
            # בדיקת מהלכים של השחקן או אסיסטים שלו
            if p_id == player_id or ast_id == player_id:
                if action['isFieldGoal'] == 1 or action['type'] in ['block', 'steal']:
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

        print(f"🎬 מחבר {len(video_clips)} קטעים עבור {player_name}...")
        final_video = concatenate_videoclips(video_clips, method="compose")
        output_name = f"highlights_{player_id}.mp4"
        final_video.write_videofile(output_name, codec="libx264", audio=True)

        # יצירת כותרת עם כוכב הבית לפי הבקשה שלך
        prefix = "🇮🇱" if is_israeli else "🔥"
        caption = (f"{prefix} <b>ביצועי {player_name}</b> {prefix}\n"
                   f"🏀 נגד כוכב הבית: {home_star}\n"
                   f"📊 {stats_line}")

        # ניקוי
        for f in temp_files:
            if os.path.exists(f): os.remove(f)
            
        return output_name, caption

    except Exception as e:
        print(f"Error: {e}")
        return None

def run_highlights_hunter():
    """לולאת החיפוש שרצה ב-Railway"""
    print("🎯 צייד ההיילייטס באוויר (מחפש ישראלים + כוכבים)...")
    while True:
        try:
            # בדיקת לוח משחקים מעודכן ל-2026
            resp = requests.get("https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json").json()
            for g in resp['scoreboard']['games']:
                gid = g['gameId']
                
                if g['gameStatus'] == 3 and gid not in PROCESSED_GAMES:
                    box_url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
                    box = requests.get(box_url).json()['game']
                    
                    # זיהוי כוכב הבית לפי ההוראות השמורות שלך [cite: 2026-03-01]
                    home_players = box['homeTeam']['players']
                    top_home_player = max(home_players, key=lambda x: x['statistics']['points'])
                    home_star_name = f"{top_home_player['firstName']} {top_home_player['familyName']}"
                    
                    all_players = home_players + box['awayTeam']['players']
                    
                    for p in all_players:
                        p_id = str(p['personId'])
                        s = p['statistics']
                        is_israeli = p_id in ISRAELI_PLAYERS
                        is_elite = s['points'] >= 40 or s['assists'] >= 20
                        
                        if is_israeli or is_elite:
                            p_name = ISRAELI_PLAYERS.get(p_id, f"{p['firstName']} {p['familyName']}")
                            stats = f"{s['points']} נק', {s['assists']} אס', {s['reboundsTotal']} רב'"
                            
                            res = get_player_highlights(gid, p_id, p_name, is_israeli, stats, home_star_name)
                            if res:
                                vid, cap = res
                                # שליחה לטלגרם
                                with open(vid, 'rb') as v:
                                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo", 
                                                  data={'chat_id': CHAT_ID, 'caption': cap, 'parse_mode': 'HTML'}, 
                                                  files={'video': v})
                                if os.path.exists(vid): os.remove(vid)
                    
                    PROCESSED_GAMES.add(gid)
        except Exception as e:
            print(f"Loop Error: {e}")
        
        time.sleep(45) # בדיקה כל 5 דקות

if __name__ == "__main__":
    run_highlights_hunter()

import requests
import os
from moviepy.editor import VideoFileClip, concatenate_videoclips

# נתונים לבדיקה - IDs רשמיים
TEST_PLAYERS = [
    {"id": "1642234", "name": "בן שרף", "game_id": "0022500860"}, 
    {"id": "1642300", "name": "דני וולף", "game_id": "0022500865"}
]

def get_full_highlight(game_id, player_id, player_name):
    print(f"🔍 מחפש מהלכים עבור {player_name}...")
    pbp_url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json"
    
    try:
        data = requests.get(pbp_url).json()
        actions = data['game']['actions']
        clips = []
        temp_files = []

        for action in actions:
            # מחפשים סלים, אסיסטים, חסימות וחטיפות
            if str(action.get('personId')) == player_id or str(action.get('assistPersonId')) == player_id:
                if action['isFieldGoal'] == 1 or action['type'] in ['block', 'steal']:
                    event_id = action['actionId']
                    # הכתובת הדינמית לוידאו (מעודכן ל-2026)
                    video_url = f"https://videos.nba.com/nba/pbp/media/2026/03/01/{game_id}/{event_id}/720p.mp4"
                    
                    r = requests.get(video_url)
                    if r.status_code == 200:
                        fname = f"temp_{event_id}.mp4"
                        with open(fname, 'wb') as f:
                            f.write(r.content)
                        clips.append(VideoFileClip(fname))
                        temp_files.append(fname)

        if clips:
            print(f"🎬 מחבר {len(clips)} קטעים עבור {player_name}...")
            final = concatenate_videoclips(clips, method="compose")
            output = f"{player_name}_Highlights.mp4"
            final.write_videofile(output, codec="libx264")
            
            # ניקוי זבל
            for f in temp_files: os.remove(f)
            return output
        
        print(f"❌ לא נמצאו מהלכים זמינים עבור {player_name}")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

# הרצת הבדיקה
for p in TEST_PLAYERS:
    get_full_highlight(p['game_id'], p['id'], p['name'])

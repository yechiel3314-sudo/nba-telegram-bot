import requests
import os
from moviepy.editor import VideoFileClip, concatenate_videoclips

# הגדרות מערכת
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

def get_player_highlights(game_id, player_id, player_name):
    print(f"🔍 מחפש מהלכים עבור {player_name}...")
    pbp_url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json"
    
    try:
        data = requests.get(pbp_url).json()
        actions = data['game']['actions']
        video_clips = []
        temp_files = []

        # ננסה שני תאריכים אפשריים (ארה"ב וישראל) כדי לא לפספס
        possible_dates = ["2026/02/28", "2026/03/01"]
        
        for action in actions:
            p_id = str(action.get('personId'))
            if p_id == player_id and action.get('isFieldGoal') == 1:
                event_id = action['actionId']
                
                # בדיקת לינקים בשרתי ה-NBA
                for date_str in possible_dates:
                    video_url = f"https://videos.nba.com/nba/pbp/media/{date_str}/{game_id}/{event_id}/720p.mp4"
                    r = requests.get(video_url, timeout=5)
                    if r.status_code == 200:
                        fname = f"temp_{event_id}.mp4"
                        with open(fname, 'wb') as f:
                            f.write(r.content)
                        video_clips.append(VideoFileClip(fname))
                        temp_files.append(fname)
                        break # מצאנו את התאריך הנכון, עוברים למהלך הבא
            
            if len(video_clips) >= 6: break # מספיק 6 מהלכים לבדיקה מהירה

        if not video_clips:
            return None

        print(f"🎬 מחבר {len(video_clips)} קטעים...")
        final_video = concatenate_videoclips(video_clips, method="compose")
        output = f"highlights_{player_id}.mp4"
        final_video.write_videofile(output, codec="libx264", audio=True)
        
        for f in temp_files: 
            if os.path.exists(f): os.remove(f)
            
        return output

    except Exception as e:
        print(f"❌ שגיאה: {e}")
        return None

def send_video(video_path, name):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    with open(video_path, 'rb') as v:
        requests.post(url, data={'chat_id': CHAT_ID, 'caption': f"🇮🇱 היילייטס: {name} נגד בוסטון 🇮🇱"}, files={'video': v})

if __name__ == "__main__":
    # הרצת הבדיקה על דני וולף (היה לו משחק מצוין עם 18 נק')
    res = get_player_highlights("0022500863", "1642300", "דני וולף")
    if res:
        send_video(res, "דני וולף")
        os.remove(res)
    else:
        print("❌ עדיין לא נמצאו קטעים. ה-NBA כנראה חסמו את הגישה הישירה למשחק הזה.")

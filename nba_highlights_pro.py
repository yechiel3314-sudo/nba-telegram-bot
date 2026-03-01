import requests
import os
import time
from moviepy.editor import VideoFileClip, concatenate_videoclips

# הגדרות מערכת
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

def get_player_highlights(game_id, player_id, player_name):
    print(f"🔍 מחפש מהלכים עבור {player_name} במשחק {game_id}...")
    pbp_url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json"
    
    try:
        data = requests.get(pbp_url).json()
        actions = data['game']['actions']
        video_clips = []
        temp_files = []

        # שרת ה-NBA עובד לפי שעון ארה"ב, אז נבדוק את היום ואת אתמול
        possible_dates = ["2026/03/01", "2026/02/28"]
        
        for action in actions:
            # מחפשים סלים של השחקן (isFieldGoal)
            if str(action.get('personId')) == player_id and action.get('isFieldGoal') == 1:
                event_id = action['actionId']
                
                # מנסים למצוא לינק וידאו שעובד
                found_video = False
                for d_str in possible_dates:
                    video_url = f"https://videos.nba.com/nba/pbp/media/{d_str}/{game_id}/{event_id}/720p.mp4"
                    r = requests.get(video_url, timeout=5)
                    if r.status_code == 200:
                        print(f"✅ נמצא וידאו למהלך {event_id}")
                        fname = f"temp_{event_id}.mp4"
                        with open(fname, 'wb') as f:
                            f.write(r.content)
                        video_clips.append(VideoFileClip(fname))
                        temp_files.append(fname)
                        found_video = True
                        break
            
            if len(video_clips) >= 10: break # הגבלה ל-10 מהלכים לבדיקה

        if not video_clips:
            print(f"❌ לא נמצאו קטעי וידאו זמינים עבור {player_name}.")
            return None

        print(f"🎬 מחבר {len(video_clips)} קטעים עבור {player_name}...")
        final_video = concatenate_videoclips(video_clips, method="compose")
        output = f"highlights_{player_id}.mp4"
        final_video.write_videofile(output, codec="libx264", audio=True)
        
        # ניקוי קבצים זמניים
        for f in temp_files:
            if os.path.exists(f): os.remove(f)
            
        return output

    except Exception as e:
        print(f"❌ שגיאה: {e}")
        return None

def send_to_telegram(video_path, name):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    with open(video_path, 'rb') as v:
        requests.post(url, data={'chat_id': CHAT_ID, 'caption': f"🇮🇱 ביצועי {name} מהלילה 🇮🇱"}, files={'video': v})

if __name__ == "__main__":
    # בדיקה על דני וולף (1642300) מהמשחק האחרון
    res = get_player_highlights("0022500863", "1642300", "דני וולף")
    if res:
        send_to_telegram(res, "דני וולף")
        os.remove(res)
    else:
        # אם וולף לא נמצא, ננסה את בן שרף (1642234)
        print("🔄 מנסה את בן שרף...")
        res_saraf = get_player_highlights("0022500863", "1642234", "בן שרף")
        if res_saraf:
            send_to_telegram(res_saraf, "בן שרף")
            os.remove(res_saraf)

import requests
import os
import time
from moviepy.editor import VideoFileClip, concatenate_videoclips

# הגדרות מערכת
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

def get_player_highlights(game_id, player_id, player_name, is_israeli):
    """פונקציה שמורידה קטעים ומחברת אותם"""
    print(f"🔍 מחפש מהלכים עבור {player_name} במשחק {game_id}...")
    pbp_url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json"
    
    try:
        data = requests.get(pbp_url).json()
        actions = data['game']['actions']
        video_clips = []
        temp_files = []

        # מחפשים סלים, אסיסטים, חסימות וחטיפות
        for action in actions:
            p_id = str(action.get('personId'))
            ast_id = str(action.get('assistPersonId'))
            
            if p_id == player_id or ast_id == player_id:
                if action['isFieldGoal'] == 1 or action['type'] in ['block', 'steal']:
                    event_id = action['actionId']
                    # הכתובת לוידאו - מעודכנת להיום (01/03/2026)
                    video_url = f"https://videos.nba.com/nba/pbp/media/2026/03/01/{game_id}/{event_id}/720p.mp4"
                    
                    r = requests.get(video_url, timeout=10)
                    if r.status_code == 200:
                        fname = f"temp_{event_id}.mp4"
                        with open(fname, 'wb') as f:
                            f.write(r.content)
                        video_clips.append(VideoFileClip(fname))
                        temp_files.append(fname)
                    
                    # בדיקה: לוקח רק עד 10 קטעים כדי שהשרת לא יקרוס בבדיקה
                    if len(video_clips) >= 10: break

        if not video_clips:
            return None

        print(f"🎬 מחבר {len(video_clips)} קטעים עבור {player_name}...")
        final_video = concatenate_videoclips(video_clips, method="compose")
        output = f"highlights_{player_id}.mp4"
        final_video.write_videofile(output, codec="libx264", audio=True)
        
        # ניקוי קבצים זמניים
        for f in temp_files: 
            if os.path.exists(f): os.remove(f)
            
        caption = f"🇮🇱 היילייטס: {player_name} נגד בוסטון 🇮🇱" if is_israeli else f"היילייטס: {player_name}"
        return output, caption

    except Exception as e:
        print(f"❌ שגיאה ביצירת וידאו: {e}")
        return None

def send_video(video_path, caption):
    """שולח לטלגרם"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    with open(video_path, 'rb') as v:
        requests.post(url, data={'chat_id': CHAT_ID, 'caption': caption, 'parse_mode': 'HTML'}, files={'video': v})

# --- החלק שמריץ את הבדיקה מיד כשאתה מעלה לשרת ---
if __name__ == "__main__":
    print("🚀 מריץ בדיקת וידאו על ברוקלין (דני וולף) מהלילה...")
    
    # נתוני המשחק נגד בוסטון (מהלילה)
    test_gid = "0022500863" 
    test_pid = "1642300" # Player ID המעודכן של דני וולף
    test_name = "דני וולף"
    
    result = get_player_highlights(test_gid, test_pid, test_name, True)
    
    if result:
        vid_path, vid_caption = result
        send_video(vid_path, vid_caption)
        print("✅ נשלח בהצלחה!")
        os.remove(vid_path)
    else:
        print("❌ לא נמצאו קטעים. מנסה את בן שרף...")
        # בן שרף (1642234)
        result_saraf = get_player_highlights(test_gid, "1642234", "בן שרף", True)
        if result_saraf:
            send_video(result_saraf[0], result_saraf[1])
            print("✅ הסרטון של בן שרף נשלח!")
            os.remove(result_saraf[0])

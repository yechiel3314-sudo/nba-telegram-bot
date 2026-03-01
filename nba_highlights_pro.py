import requests
import time
import os
from moviepy.editor import VideoFileClip, concatenate_videoclips

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

def get_player_highlights(game_id, player_id, player_name, is_israeli, stats_line=""):
    """מוריד קליפים ומחבר אותם לסרטון אחד"""
    print(f"🔍 מתחיל לאסוף מהלכים עבור {player_name}...")
    pbp_url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json"
    
    try:
        data = requests.get(pbp_url).json()
        actions = data['game']['actions']
        video_clips = []
        temp_files = []

        for action in actions:
            p_id = str(action.get('personId'))
            ast_id = str(action.get('assistPersonId'))
            
            if p_id == player_id or ast_id == player_id:
                if action['isFieldGoal'] == 1 or action['type'] in ['block', 'steal']:
                    event_id = action['actionId']
                    # הקישור לוידאו - מעודכן לתאריך המשחק נגד בוסטון (01/03/2026)
                    video_url = f"https://videos.nba.com/nba/pbp/media/2026/03/01/{game_id}/{event_id}/720p.mp4"
                    
                    r = requests.get(video_url, timeout=10)
                    if r.status_code == 200:
                        fname = f"temp_{event_id}.mp4"
                        with open(fname, 'wb') as f:
                            f.write(r.content)
                        video_clips.append(VideoFileClip(fname))
                        temp_files.append(fname)
            
            if len(video_clips) >= 8: break # בדיקה מהירה של 8 מהלכים

        if not video_clips:
            print("❌ לא נמצאו קטעי וידאו זמינים בשרת ה-NBA.")
            return None

        print(f"🎬 מחבר {len(video_clips)} קטעים...")
        final_video = concatenate_videoclips(video_clips, method="compose")
        output_name = f"test_{player_id}.mp4"
        final_video.write_videofile(output_name, codec="libx264", audio=True)

        # ניקוי
        for f in temp_files: 
            if os.path.exists(f): os.remove(f)
            
        caption = f"🇮🇱 <b>בדיקת מערכת: {player_name}</b> 🇮🇱\n📊 {stats_line}"
        return output_name, caption

    except Exception as e:
        print(f"Error: {e}")
        return None

def send_video(video_path, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    with open(video_path, 'rb') as video:
        requests.post(url, data={'chat_id': CHAT_ID, 'caption': caption, 'parse_mode': 'HTML'}, files={'video': video})

# ==========================================
# פקודת הבדיקה (תרוץ מיד כשתעלה ל-Railway)
# ==========================================
if __name__ == "__main__":
    # נתוני אמת מהמשחק נגד בוסטון (הלילה)
    test_game_id = "0022500863" 
    test_player_id = "1642300" # דני וולף
    test_player_name = "דני וולף"
    test_stats = "18 נק', 9 רב', 7 אס'" #

    print(f"🚀 מריץ בדיקה על המשחק מול בוסטון...")
    result = get_player_highlights(test_game_id, test_player_id, test_player_name, True, test_stats)
    
    if result:
        send_video(result[0], result[1])
        print("✅ נשלח לטלגרם!")
        if os.path.exists(result[0]): os.remove(result[0])

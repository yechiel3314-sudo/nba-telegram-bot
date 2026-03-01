import requests
import os
from datetime import datetime
from moviepy.editor import VideoFileClip, concatenate_videoclips

# הגדרות (וודא שהן נכונות)
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
WEMBY_ID = "1641705"
GAME_ID = "0022500858" # ה-ID של המשחק מהלילה (סן אנטוניו)

def run_immediate_test():
    print(f"🚀 מתחיל בדיקה על משחק {GAME_ID} (וומבניאמה)...")
    
    # 1. ניסיון למשוך את תאריך המשחק בצורה בטוחה
    pbp_url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{GAME_ID}.json"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        res = requests.get(pbp_url, headers=headers, timeout=15).json()
        game_data = res.get('game', {})
        # חילוץ תאריך בפורמט YYYY/MM/DD
        game_date = game_data.get('gameEt', datetime.now().isoformat()).split('T')[0].replace('-', '/')
        actions = game_data.get('actions', [])
        
        video_clips = []
        temp_files = []

        print(f"📂 נמצאו {len(actions)} פעולות במשחק. מחפש סלים של וומבי...")

        for action in actions:
            act_id = action.get('actionId')
            p_id = str(action.get('personId'))
            ast_id = str(action.get('assistPersonId'))
            
            # בדיקה אם זה סל או אסיסט של וומבי
            if act_id and (p_id == WEMBY_ID or ast_id == WEMBY_ID) and action.get('isFieldGoal') == 1:
                video_url = f"https://videos.nba.com/nba/pbp/media/{game_date}/{GAME_ID}/{act_id}/720p.mp4"
                
                r = requests.get(video_url, headers=headers, timeout=5)
                if r.status_code == 200:
                    fname = f"temp_test_{act_id}.mp4"
                    with open(fname, 'wb') as f: f.write(r.content)
                    try:
                        clip = VideoFileClip(fname)
                        video_clips.append(clip)
                        temp_files.append(fname)
                        print(f"✅ הורד קטע {len(video_clips)}")
                    except:
                        if os.path.exists(fname): os.remove(fname)
            
            if len(video_clips) >= 10: break

        if not video_clips:
            print("❌ לא נמצאו קטעי וידאו זמינים. ייתכן והשרת עדיין מעבד אותם.")
            return

        print(f"🎬 מחבר {len(video_clips)} קטעים...")
        final_video = concatenate_videoclips(video_clips, method="compose")
        output_name = "wemby_test_final.mp4"
        final_video.write_videofile(output_name, codec="libx264", audio=True, logger=None)

        print(f"📤 שולח לטלגרם...")
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
        with open(output_name, 'rb') as f:
            requests.post(url, data={'chat_id': CHAT_ID, 'caption': "🤖 <b>בדיקת מערכת מוצלחת!</b>\nויקטור וומבניאמה", 'parse_mode': 'HTML'}, files={'video': f})
        
        # ניקוי
        final_video.close()
        for clip in video_clips: clip.close()
        for f in temp_files + [output_name]:
            if os.path.exists(f): os.remove(f)
            
        print("✨ סיימנו! בדוק את הטלגרם שלך.")

    except Exception as e:
        print(f"❌ שגיאה בבדיקה: {e}")

if __name__ == "__main__":
    run_immediate_test()

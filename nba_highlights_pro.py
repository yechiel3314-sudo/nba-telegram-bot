import requests
import os
from moviepy.editor import VideoFileClip, concatenate_videoclips

# הגדרות (העתקתי מהקוד שלך)
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

def run_test():
    # נתוני אמת לבדיקה: דני אבדיה מהלילה
    game_id = "0022500850" 
    player_id = "1630166"
    player_name = "דני אבדיה"
    
    print(f"🧪 מתחיל בדיקה על אמת עבור {player_name}...")
    
    pbp_url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json"
    try:
        data = requests.get(pbp_url).json()
        actions = data['game']['actions']
        
        video_clips = []
        temp_files = []

        # נוריד רק את 5 המהלכים הראשונים כדי שהבדיקה תהיה מהירה
        count = 0
        for action in actions:
            if count >= 5: break
            
            p_id = str(action.get('personId'))
            if p_id == player_id and (action['isFieldGoal'] == 1 or action['type'] in ['block', 'steal']):
                event_id = action['actionId']
                # הכתובת הרשמית של ה-NBA לוידאו
                video_url = f"https://videos.nba.com/nba/pbp/media/2026/03/01/{game_id}/{event_id}/720p.mp4"
                
                print(f"📥 מוריד מהלך {event_id}...")
                r = requests.get(video_url, timeout=10)
                if r.status_code == 200:
                    fname = f"test_{event_id}.mp4"
                    with open(fname, 'wb') as f:
                        f.write(r.content)
                    video_clips.append(VideoFileClip(fname))
                    temp_files.append(fname)
                    count += 1

        if not video_clips:
            print("❌ לא נמצאו קטעי וידאו. יכול להיות שהשרת של ה-NBA עוד לא עיבד אותם.")
            return

        print(f"🎬 מחבר {len(video_clips)} קטעים...")
        final_video = concatenate_videoclips(video_clips, method="compose")
        output = "test_highlights.mp4"
        final_video.write_videofile(output, codec="libx264")

        # שליחה לטלגרם
        print("📤 שולח לערוץ...")
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
        with open(output, 'rb') as v:
            requests.post(url, data={
                'chat_id': CHAT_ID, 
                'caption': f"🇮🇱 בדיקת מערכת: ההיילייטס של {player_name} 🇮🇱",
                'parse_mode': 'HTML'
            }, files={'video': v})
        
        print("✅ הצלחה! בדוק את הטלגרם.")
        
        # ניקוי
        for f in temp_files + [output]:
            if os.path.exists(f): os.remove(f)

    except Exception as e:
        print(f"❌ שגיאה: {e}")

if __name__ == "__main__":
    run_test()

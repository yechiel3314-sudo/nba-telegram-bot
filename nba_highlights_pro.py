import requests
import os
import gc
from datetime import datetime
from moviepy.editor import VideoFileClip, concatenate_videoclips
from deep_translator import GoogleTranslator

# ==========================================
# הגדרות מערכת (וודא שהטוקנים נכונים)
# ==========================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
HEADERS = {"User-Agent": "Mozilla/5.0"}
translator = GoogleTranslator(source='en', target='iw')

def get_player_highlights(game_id, player_id, player_name, stats_line):
    """פונקציה לייצור הסרטון"""
    pbp_url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json"
    
    try:
        print(f"🔍 [1/4] אוסף מהלכים עבור {player_name}...")
        r_pbp = requests.get(pbp_url, headers=HEADERS, timeout=10).json()
        game_date = r_pbp['game'].get('gameEt', datetime.now().isoformat()).split('T')[0].replace('-', '/')
        actions = r_pbp['game']['actions']
        
        video_clips = []
        temp_files = []

        print(f"📥 [2/4] מוריד קטעים משרתי ה-NBA...")
        for action in actions:
            # בודק אם השחקן קלע או מסר אסיסט
            if (str(action.get('personId')) == player_id or str(action.get('assistPersonId')) == player_id) and action.get('isFieldGoal') == 1:
                event_id = action['actionId']
                video_url = f"https://videos.nba.com/nba/pbp/media/{game_date}/{game_id}/{event_id}/720p.mp4"
                
                r = requests.get(video_url, headers=HEADERS, timeout=5)
                if r.status_code == 200:
                    fname = f"test_{event_id}.mp4"
                    with open(fname, 'wb') as f: f.write(r.content)
                    try:
                        clip = VideoFileClip(fname)
                        video_clips.append(clip)
                        temp_files.append(fname)
                    except:
                        if os.path.exists(fname): os.remove(fname)
            
            if len(video_clips) >= 10: break # בבדיקה ניקח רק 10 קטעים כדי שיהיה מהיר

        if not video_clips:
            print("❌ לא נמצאו קטעי וידאו להורדה.")
            return None

        print(f"🎬 [3/4] מחבר קטעים...")
        final_video = concatenate_videoclips(video_clips, method="compose")
        output_name = "wembanyama_test.mp4"
        final_video.write_videofile(output_name, codec="libx264", audio=True, logger=None)
        
        final_video.close()
        for clip in video_clips: clip.close()
        for f in temp_files: 
            if os.path.exists(f): os.remove(f)

        return output_name
    except Exception as e:
        print(f"❌ שגיאה: {e}")
        return None

def run_test():
    print("🧪 מתחיל בדיקה מיידית על ויקטור וומבניאמה...")
    
    # 1. משיכת לוח המשחקים כדי למצוא את ה-GameID של סן אנטוניו
    resp = requests.get("https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json", headers=HEADERS).json()
    
    target_game_id = None
    for g in resp['scoreboard']['games']:
        if "Spurs" in g['homeTeam']['teamName'] or "Spurs" in g['awayTeam']['teamName']:
            target_game_id = g['gameId']
            print(f"🏀 נמצא משחק של סן אנטוניו! ID: {target_game_id}")
            break
    
    if not target_game_id:
        print("❌ לא נמצא משחק של סן אנטוניו בלוח התוצאות של היום.")
        return

    # 2. חיפוש ה-ID של וומבניאמה בתוך ה-Boxscore
    box_resp = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{target_game_id}.json", headers=HEADERS).json()
    wemby_id = "1641705" # ה-ID הרשמי של וומבניאמה
    
    # שליפת סטטיסטיקה בסיסית
    stats_text = "בדיקת היילייטס"
    for p in box_resp['game']['homeTeam']['players'] + box_resp['game']['awayTeam']['players']:
        if str(p['personId']) == wemby_id:
            s = p['statistics']
            stats_text = f"{s['points']} נק', {s['reboundsTotal']} רב', {s['assists']} אס'"
            break

    # 3. הרצת תהליך ההיילייטס
    video_file = get_player_highlights(target_game_id, wemby_id, "ויקטור וומבניאמה", stats_text)
    
    if video_file:
        print(f"📤 [4/4] שולח לטלגרם...")
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
        with open(video_file, 'rb') as f:
            requests.post(url, data={'chat_id': CHAT_ID, 'caption': f"🧪 <b>בדיקת מערכת: וומבניאמה</b>\n📊 {stats_text}", 'parse_mode': 'HTML'}, files={'video': f})
        
        if os.path.exists(video_file): os.remove(video_file)
        print("✨ הבדיקה הושלמה בהצלחה!")
    else:
        print("❌ הבדיקה נכשלה - ייתכן ואין עדיין קטעי וידאו זמינים למשחק הזה.")

if __name__ == "__main__":
    run_test()

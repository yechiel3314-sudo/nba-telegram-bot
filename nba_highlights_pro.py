import requests
import os
import gc
from datetime import datetime
from moviepy.editor import VideoFileClip, concatenate_videoclips
from deep_translator import GoogleTranslator

# ==========================================
# הגדרות מערכת
# ==========================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
HEADERS = {"User-Agent": "Mozilla/5.0"}
WEMBY_ID = "1641705" # ID רשמי של ויקטור וומבניאמה
translator = GoogleTranslator(source='en', target='iw')

def get_test_highlights(game_id, player_id, player_name, stats_line):
    pbp_url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json"
    
    try:
        print(f"🔍 [1/4] אוסף מהלכים עבור {player_name}...")
        r_pbp = requests.get(pbp_url, headers=HEADERS, timeout=15).json()
        
        # תיקון שגיאת gameEt - שימוש ב-get בטוח
        game_data = r_pbp.get('game', {})
        game_date = game_data.get('gameEt', datetime.now().isoformat()).split('T')[0].replace('-', '/')
        actions = game_data.get('actions', [])
        
        video_clips = []
        temp_files = []

        print(f"📥 [2/4] מוריד קטעים (בודק זמינות בשרת)...")
        for action in actions:
            # תיקון שגיאת actionId - בדיקה אם השדה קיים
            act_id = action.get('actionId')
            p_id = str(action.get('personId'))
            ast_id = str(action.get('assistPersonId'))
            
            if act_id and (p_id == player_id or ast_id == player_id) and action.get('isFieldGoal') == 1:
                video_url = f"https://videos.nba.com/nba/pbp/media/{game_date}/{game_id}/{act_id}/720p.mp4"
                
                try:
                    r = requests.get(video_url, headers=HEADERS, timeout=5)
                    if r.status_code == 200:
                        fname = f"test_{act_id}.mp4"
                        with open(fname, 'wb') as f: f.write(r.content)
                        clip = VideoFileClip(fname)
                        video_clips.append(clip)
                        temp_files.append(fname)
                        print(f"✅ הורד מהלך {len(video_clips)}")
                except:
                    continue
            
            if len(video_clips) >= 8: break # בבדיקה ניקח 8 קטעים למהירות

        if not video_clips:
            print("❌ לא נמצאו קטעי וידאו זמינים בשרתי ה-NBA כרגע.")
            return None

        print(f"🎬 [3/4] מחבר קטעים לסרטון...")
        final_video = concatenate_videoclips(video_clips, method="compose")
        output_name = "test_wemby.mp4"
        final_video.write_videofile(output_name, codec="libx264", audio=True, logger=None)
        
        final_video.close()
        for clip in video_clips: clip.close()
        for f in temp_files: 
            if os.path.exists(f): os.remove(f)

        return output_name
    except Exception as e:
        print(f"❌ שגיאה בתהליך: {e}")
        return None

def run_test():
    print("🧪 מתחיל בדיקת מערכת חסינת שגיאות על וומבניאמה...")
    
    # מציאת המשחק של סן אנטוניו
    try:
        resp = requests.get("https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json", headers=HEADERS).json()
        target_game_id = None
        for g in resp['scoreboard']['games']:
            if "Spurs" in g['homeTeam']['teamName'] or "Spurs" in g['awayTeam']['teamName']:
                target_game_id = g['gameId']
                print(f"🏀 נמצא משחק של סן אנטוניו: {target_game_id}")
                break
        
        if not target_game_id:
            print("❌ לא נמצא משחק של סן אנטוניו בלוח של היום.")
            return

        # שליפת נתוני שחקן מהמשחק
        box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{target_game_id}.json", headers=HEADERS).json()['game']
        stats_text = "בדיקה"
        for p in box['homeTeam']['players'] + box['awayTeam']['players']:
            if str(p['personId']) == WEMBY_ID:
                s = p['statistics']
                stats_text = f"{s['points']} נק', {s['reboundsTotal']} רב', {s['assists']} אס'"
                break

        # יצירת הסרטון
        video_file = get_test_highlights(target_game_id, WEMBY_ID, "ויקטור וומבניאמה", stats_text)
        
        if video_file:
            print(f"📤 [4/4] שולח לטלגרם...")
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
            with open(video_file, 'rb') as f:
                requests.post(url, data={
                    'chat_id': CHAT_ID, 
                    'caption': f"🧪 <b>בדיקת מערכת: וומבניאמה</b>\n📊 {stats_text}", 
                    'parse_mode': 'HTML'
                }, files={'video': f})
            
            if os.path.exists(video_file): os.remove(video_file)
            print("✨ הבדיקה הושלמה! בדוק את הטלגרם.")
        else:
            print("❌ לא הצלחתי לייצר וידאו (ייתכן והמהלכים עדיין לא עלו לשרת ה-NBA).")
            
    except Exception as e:
        print(f"❌ שגיאה כללית בבדיקה: {e}")

if __name__ == "__main__":
    run_test()

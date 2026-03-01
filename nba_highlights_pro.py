import requests
import time
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

ISRAELI_PLAYERS = {
    "1630166": "דני אבדיה",
    "1642234": "בן שרף",
    "1642300": "דני וולף"
}

# מעקב אחרי שחקנים שכבר נשלחו כדי למנוע כפילויות
SENT_TODAY = set()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

translator = GoogleTranslator(source='en', target='iw')

def get_player_highlights(game_id, player_id, player_name, is_israeli, stats_line):
    """תהליך יצירת ההיילייטס עם דיווח שלבים וחסינות לשגיאות"""
    pbp_url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json"
    
    try:
        print(f"🔍 [1/5] מתחיל איסוף מהלכים עבור {player_name}...")
        r_pbp = requests.get(pbp_url, headers=HEADERS, timeout=15)
        if r_pbp.status_code != 200:
            print(f"❌ שגיאה בשלב 1: לא ניתן לגשת לנתוני המשחק {game_id}")
            return None
        
        data = r_pbp.json()
        game_obj = data.get('game', {})
        game_date = game_obj.get('gameEt', datetime.now().isoformat()).split('T')[0].replace('-', '/')
        actions = game_obj.get('actions', [])
        
        video_clips = []
        temp_files = []

        print(f"📥 [2/5] מוריד קטעי וידאו משרתי ה-NBA...")
        for action in actions:
            event_id = action.get('actionId')
            p_id = str(action.get('personId', ''))
            ast_id = str(action.get('assistPersonId', ''))
            
            if event_id and (p_id == player_id or ast_id == player_id) and action.get('isFieldGoal') == 1:
                video_url = f"https://videos.nba.com/nba/pbp/media/{game_date}/{game_id}/{event_id}/720p.mp4"
                
                try:
                    r = requests.get(video_url, headers=HEADERS, timeout=7)
                    if r.status_code == 200:
                        fname = f"temp_{player_id}_{event_id}.mp4"
                        with open(fname, 'wb') as f:
                            f.write(r.content)
                        
                        clip = VideoFileClip(fname)
                        video_clips.append(clip)
                        temp_files.append(fname)
                except:
                    if 'fname' in locals() and os.path.exists(fname): os.remove(fname)
                    continue

            if len(video_clips) >= 15: break

        if not video_clips:
            print(f"⚠️ שלב 2 נכשל: לא נמצאו קטעים זמינים עבור {player_name}")
            return None

        print(f"🎬 [3/5] מחבר {len(video_clips)} קטעים לסרטון אחד...")
        final_video = concatenate_videoclips(video_clips, method="compose")
        output_name = f"highlights_{player_id}.mp4"
        final_video.write_videofile(output_name, codec="libx264", audio=True, logger=None)
        
        final_video.close()
        for clip in video_clips: clip.close()
        for f in temp_files:
            if os.path.exists(f): os.remove(f)

        print(f"✅ [4/5] הסרטון מוכן! מתרגם כיתוב...")
        try:
            h_name = player_name if is_israeli else translator.translate(player_name)
        except:
            h_name = player_name

        prefix = "🇮🇱" if is_israeli else "🔥"
        caption = f"{prefix} <b>ביצועי {h_name} מהלילה!</b> {prefix}\n📊 {stats_line}"
        
        gc.collect() 
        return output_name, caption

    except Exception as e:
        print(f"❌ שגיאה קריטית בתהליך: {e}")
        return None

def process_scoreboard(only_israelis=False):
    """סורק את לוח התוצאות ומעבד שחקנים רלוונטיים"""
    try:
        scoreboard_url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
        resp = requests.get(scoreboard_url, headers=HEADERS, timeout=10).json()
        games = resp.get('scoreboard', {}).get('games', [])
        
        for g in games:
            if g.get('gameStatus') == 3: # המשחק הסתיים
                gid = g['gameId']
                box_url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
                box_resp = requests.get(box_url, headers=HEADERS, timeout=10).json()
                box = box_resp.get('game', {})
                
                all_players = box.get('homeTeam', {}).get('players', []) + box.get('awayTeam', {}).get('players', [])
                
                for p in all_players:
                    s = p.get('statistics', {})
                    p_id = str(p.get('personId', ''))
                    is_israeli = p_id in ISRAELI_PLAYERS
                    points = s.get('points', 0)
                    
                    # בדיקה אם השחקן עומד בתנאי (ישראלי בסריקה שוטפת, או 35+ בסריקת בוקר)
                    should_process = False
                    if is_israeli and p_id not in SENT_TODAY:
                        should_process = True
                    elif not only_israelis and points >= 35 and p_id not in SENT_TODAY:
                        should_process = True
                    
                    if should_process:
                        p_raw_name = f"{p['firstName']} {p['familyName']}"
                        p_display_name = ISRAELI_PLAYERS.get(p_id, p_raw_name)
                        stats_text = f"{points} נק', {s.get('reboundsTotal')} רב', {s.get('assists')} אס'"
                        
                        print(f"🎯 מטרה נמצאה: {p_display_name} ({stats_text})")
                        result = get_player_highlights(gid, p_id, p_display_name, is_israeli, stats_text)
                        
                        if result:
                            vid_path, caption_text = result
                            print(f"📤 [5/5] שולח וידאו לטלגרם...")
                            
                            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
                            with open(vid_path, 'rb') as video_file:
                                r = requests.post(url, data={'chat_id': CHAT_ID, 'caption': caption_text, 'parse_mode': 'HTML'}, files={'video': video_file}, timeout=60)
                            
                            if r.status_code == 200:
                                print(f"✨ הצלחה מלאה! הסרטון של {p_display_name} נשלח.")
                                SENT_TODAY.add(p_id)
                            
                            if os.path.exists(vid_path): os.remove(vid_path)
    except Exception as e:
        print(f"⚠️ שגיאה בסריקת לוח התוצאות: {e}")

def run_highlights_hunter():
    print("🚀 צייד ההיילייטס המפוצל הופעל. בודק ישראלים כל 15 דקות וכוכבים ב-10:00.")
    last_israeli_check = 0
    
    while True:
        now = datetime.now()
        
        # 1. איפוס הרשימה היומית בצהריים
        if now.hour == 13 and now.minute == 0:
            SENT_TODAY.clear()
            print("🧹 רשימת השחקנים היומית אופסה.")
            time.sleep(60)

        # 2. סריקת בוקר כללית (ישראלים שפוספסו + שחקני 35+ נקודות)
        if now.hour == 10 and now.minute == 0:
            print(f"⏰ השעה 10:00. מתחיל סריקת בוקר כוללת...")
            process_scoreboard(only_israelis=False)
            time.sleep(61)

        # 3. סריקת ישראלים כל 15 דקות (בכל שעה שהיא לא 10:00)
        current_ts = time.time()
        if (current_ts - last_israeli_check) >= 900: # 900 שניות = 15 דקות
            if now.hour != 10:
                print(f"⏳ בדיקה תקופתית לישראלים ({now.strftime('%H:%M')})...")
                process_scoreboard(only_israelis=True)
            last_israeli_check = current_ts

        time.sleep(15)

if __name__ == "__main__":
    run_highlights_hunter()

import requests
import time
import os
import gc
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

PROCESSED_GAMES = set()
translator = GoogleTranslator(source='en', target='iw')

def get_player_highlights(game_id, player_id, player_name, is_israeli, stats_line):
    """מוריד קטעים, מחבר אותם ושולח לטלגרם עם לוגים מפורטים"""
    pbp_url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json"
    start_time = time.time()
    
    try:
        print(f"🔍 [שלב 1] מתחיל איסוף מהלכים עבור {player_name}...")
        r_pbp = requests.get(pbp_url, headers=HEADERS, timeout=10)
        if r_pbp.status_code != 200: 
            print(f"❌ שגיאה: לא הצלחתי למשוך Play-by-Play למשחק {game_id}")
            return None
        
        data = r_pbp.json()
        game_date = data['game']['gameEt'].split('T')[0].replace('-', '/')
        actions = data['game']['actions']
        
        video_clips = []
        temp_files = []

        # איסוף מהלכים
        for action in actions:
            p_id = str(action.get('personId'))
            ast_id = str(action.get('assistPersonId'))
            
            if (p_id == player_id or ast_id == player_id) and action.get('isFieldGoal') == 1:
                event_id = action['actionId']
                video_url = f"https://videos.nba.com/nba/pbp/media/{game_date}/{game_id}/{event_id}/720p.mp4"
                
                r = requests.get(video_url, headers=HEADERS, timeout=5)
                if r.status_code == 200:
                    fname = f"temp_{player_id}_{event_id}.mp4"
                    with open(fname, 'wb') as f:
                        f.write(r.content)
                    
                    try:
                        clip = VideoFileClip(fname)
                        video_clips.append(clip)
                        temp_files.append(fname)
                    except:
                        if os.path.exists(fname): os.remove(fname)

            if len(video_clips) >= 15: break

        if not video_clips:
            print(f"⚠️ לא נמצאו קטעי וידאו זמינים עבור {player_name}")
            return None

        print(f"📂 [שלב 2] הורדו {len(video_clips)} קטעים. מתחיל חיבור וידאו (זה עשוי לקחת זמן)...")
        
        # עריכת הוידאו
        final_video = concatenate_videoclips(video_clips, method="compose")
        output_name = f"highlights_{player_id}.mp4"
        final_video.write_videofile(output_name, codec="libx264", audio=True, logger=None)
        
        # שחרור זיכרון
        final_video.close()
        for clip in video_clips: clip.close()

        print(f"🎬 [שלב 3] הוידאו מוכן: {output_name}")

        # תרגום שם
        try:
            h_name = player_name if is_israeli else translator.translate(player_name)
        except:
            h_name = player_name

        prefix = "🇮🇱" if is_israeli else "🔥"
        caption = f"{prefix} <b>ביצועי {h_name} מהלילה!</b> {prefix}\n📊 {stats_line}"

        # ניקוי קבצים זמניים
        for f in temp_files:
            if os.path.exists(f): os.remove(f)
        
        duration = round(time.time() - start_time, 2)
        print(f"✨ [שלב 4] תהליך העריכה הסתיים בהצלחה! (זמן כולל: {duration} שניות)")
        
        gc.collect() 
        return output_name, caption

    except Exception as e:
        print(f"❌ שגיאה קריטית ביצירת היילייטס: {e}")
        return None

def run_highlights_hunter():
    print("🚀 צייד ההיילייטס באוויר! סורק משחקים שהסתיימו...")
    
    while True:
        try:
            scoreboard_url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
            resp = requests.get(scoreboard_url, headers=HEADERS, timeout=10).json()
            
            for g in resp['scoreboard']['games']:
                gid = g['gameId']
                
                # סטטוס 3 = משחק הסתיים
                if g['gameStatus'] == 3 and gid not in PROCESSED_GAMES:
                    print(f"\n🏀 משחק הסתיים: {g['awayTeam']['teamName']} נגד {g['homeTeam']['teamName']}")
                    
                    box_url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
                    box_resp = requests.get(box_url, headers=HEADERS, timeout=10).json()
                    box = box_resp['game']
                    
                    all_players = box['homeTeam']['players'] + box['awayTeam']['players']
                    
                    for p in all_players:
                        s = p['statistics']
                        p_id = str(p['personId'])
                        is_israeli = p_id in ISRAELI_PLAYERS
                        
                        # תנאי להיילייטס (ישראלי או הופעה מטורפת)
                        if is_israeli or s['points'] >= 35:
                            p_raw_name = f"{p['firstName']} {p['familyName']}"
                            p_display_name = ISRAELI_PLAYERS.get(p_id, p_raw_name)
                            stats_text = f"{s['points']} נק', {s['reboundsTotal']} רב', {s['assists']} אס'"
                            
                            print(f"🎯 מטרה זוהתה: {p_display_name}. מתחיל תהליך...")
                            
                            result = get_player_highlights(gid, p_id, p_display_name, is_israeli, stats_text)
                            
                            if result:
                                vid_path, caption_text = result
                                print(f"📤 [שלב 5] שולח לטלגרם...")
                                
                                url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
                                with open(vid_path, 'rb') as video_file:
                                    r = requests.post(url, data={
                                        'chat_id': CHAT_ID, 
                                        'caption': caption_text, 
                                        'parse_mode': 'HTML'
                                    }, files={'video': video_file}, timeout=60)
                                    
                                if r.status_code == 200:
                                    print(f"✅ הצלחה! היילייטס של {p_display_name} נשלחו.")
                                else:
                                    print(f"❌ שגיאה בשליחה לטלגרם: {r.text}")
                                
                                if os.path.exists(vid_path): os.remove(vid_path)
                    
                    PROCESSED_GAMES.add(gid)
                    
        except Exception as e:
            print(f"⚠️ שגיאה בלולאה הראשית: {e}")
        
        time.sleep(60)

if __name__ == "__main__":
    run_highlights_hunter()

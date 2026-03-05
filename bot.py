import requests
import time
import json
import os
from datetime import datetime
from deep_translator import GoogleTranslator

# ==========================================
# הגדרות מערכת וטוקנים
# ==========================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
CACHE_FILE = "nba_cache.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}

translator = GoogleTranslator(source='en', target='iw')

NBA_TEAMS_HEBREW = {
    "Atlanta Hawks": "אטלנטה הוקס", "Boston Celtics": "בוסטון סלטיקס",
    "Brooklyn Nets": "ברוקלין נטס", "Charlotte Hornets": "שארלוט הורנטס",
    "Chicago Bulls": "שיקגו בולס", "Cleveland Cavaliers": "קליבלנד קאבלירס",
    "Dallas Mavericks": "דאלאס מאבריקס", "Denver Nuggets": "דנבר נאגטס",
    "Detroit Pistons": "דטרויט פיסטונס", "Golden State Warriors": "גולדן סטייט ווריורס",
    "Houston Rockets": "יוסטון רוקטס", "Indiana Pacers": "אינדיאנה פייסרס",
    "LA Clippers": "לוס אנג'לס קליפרס", "Los Angeles Lakers": "לוס אנג'לס לייקרס",
    "Memphis Grizzlies": "ממפיס גריזליס", "Miami Heat": "מיאמי היט",
    "Milwaukee Bucks": "מילווקי באקס", "Minnesota Timberwolves": "מינסוטה טימברוולבס",
    "New Orleans Pelicans": "ניו אורלינס פליקנס", "New York Knicks": "ניו יורק ניקס",
    "Oklahoma City Thunder": "אוקלהומה סיטי ת'אנדר", "Orlando Magic": "אורלנדו מג'יק",
    "Philadelphia 76ers": "פילדלפיה 76", "Phoenix Suns": "פיניקס סאנס",
    "Portland Trail Blazers": "פורטלנד טרייל בלייזרס", "Sacramento Kings": "סקרמנטו קינגס",
    "San Antonio Spurs": "סן אנטוניו ספרס", "Toronto Raptors": "טורונטו ראפטורס",
    "Utah Jazz": "יוטה ג'אז", "Washington Wizards": "וושינגטון וויזארדס"
}

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "names" not in data: data["names"] = {}
                if "games" not in data: data["games"] = {}
                return data
        except: pass
    return {"names": {}, "games": {}}

cache = load_cache()

def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=4, ensure_ascii=False)

def translate_name(name):
    if not name: return ""
    if name in NBA_TEAMS_HEBREW: return NBA_TEAMS_HEBREW[name]
    for en_full, heb_full in NBA_TEAMS_HEBREW.items():
        if en_full.lower() in name.lower(): return heb_full
    if name in cache["names"]: return cache["names"][name]
    try:
        clean_name = name.replace("Jr.", "").replace("Sr.", "").strip()
        res = translator.translate(clean_name)
        res = res.replace("שקנאים", "פליקנס").replace("ג'ז", "ג'אז").replace("ניקס של ניו יורק", "ניו יורק ניקס")
        cache["names"][name] = res
        save_cache()
        return res
    except: return name

def get_stat_line(p):
    s = p['statistics']
    line = f"{s['points']} נק', {s['reboundsTotal']} רב', {s['assists']} אס'"
    if s.get('steals', 0) > 0: line += f", {s['steals']} חט'"
    if s.get('blocks', 0) > 0: line += f", {s['blocks']} חס'"
    return line

def format_msg(box, label, is_final=False, is_start=False, is_drama=False):
    photo_url = None
    away, home = box['awayTeam'], box['homeTeam']
    
    # שינוי 1: שם מלא (עיר + כינוי) בכל ההודעות בכותרת
    a_full = translate_name(f"{away['teamCity']} {away['teamName']}")
    h_full = translate_name(f"{home['teamCity']} {home['teamName']}")
    
    period = box.get('period', 0)
    s_space = "ㅤ" 
    
    combined_len = len(a_full) + len(h_full)
    padding = max(0, 22 - combined_len)
    
    if is_drama: header_emoji = "😱"
    elif is_final: header_emoji = "🏁"
    elif is_start: header_emoji = "🚀"
    else: header_emoji = "⏱️"
    
    header_text = f"{header_emoji} <b>{label}</b> {header_emoji}"
    msg = f"\u200f{header_text}\n"
    msg += f"\u200f🏀 <b>{a_full} 🆚 {h_full}</b> 🏀{s_space * padding}\n\n"

    if is_start:
        if period == 1:
            for team in [away, home]:
                # שינוי 2: שם מלא בחמישיות
                t_full_name = translate_name(f"{team['teamCity']} {team['teamName']}")
                starters = [translate_name(f"{p['firstName']} {p['familyName']}") for p in team['players'] if p.get('starter') == '1']
                out = [translate_name(f"{p['firstName']} {p['familyName']}") for p in team['players'] if p.get('status') == 'INACTIVE']
                
                msg += f"\u200f🏀 <b>{t_full_name}</b>\n"
                msg += f"\u200f📍 <b>חמישייה:</b> {', '.join(starters) if starters else 'טרם פורסם'}\n"
                if out:
                    msg += f"\u200f❌ <b>חיסורים:</b> {', '.join(out[:5])}\n"
                msg += "\n"
        
        # שינוי 3: ביטול תמונה בפתיחה
        return msg, None

    score_str = f"<b>{max(away['score'], home['score'])} - {min(away['score'], home['score'])}</b>"
    
    if is_drama:
        msg += f"\u200f🔥 <b>טירוף! שוויון {score_str} הולכים להארכה!</b> 🔥\n\n"
        return msg, None # ביטול תמונה בדרמה

    leader_name = a_full if away['score'] > home['score'] else h_full
    win_emoji = "🏆" if is_final else "🔥"
    if away['score'] == home['score']:
        msg += f"\u200f🔥 <b>שוויון {score_str}</b> 🔥\n\n"
    else:
        action = "מנצחת" if is_final else "מובילה"
        msg += f"\u200f{win_emoji} <b>{leader_name} {action} {score_str}</b> {win_emoji}\n\n"

    count = 3 if (period >= 4 or is_final) else 2
    for team in [away, home]:
        # שינוי 4: שם מלא מעל רשימת הסטטיסטיקה (📍 הקבוצה המלאה:)
        t_full_stats = translate_name(f"{team['teamCity']} {team['teamName']}")
        msg += f"\u200f📍 <b>{t_full_stats}:</b>\n"
        top = sorted([p for p in team['players'] if p['statistics']['points'] > 0], 
                     key=lambda x: x['statistics']['points'], reverse=True)[:count]
        for i, p in enumerate(top):
            medal = ["🥇", "🥈", "🥉"][i]
            msg += f"\u200f{medal} <b>{translate_name(p['firstName']+' '+p['familyName'])}</b>: {get_stat_line(p)}\n"
        msg += "\n"

    if is_final:
        all_p = away['players'] + home['players']
        mvp = max(all_p, key=lambda x: x['statistics']['points'] + x['statistics']['reboundsTotal'] + x['statistics']['assists'])
        msg += f"\u200f🏆 <b>ה-MVP של המשחק: {translate_name(mvp['firstName']+' '+mvp['familyName'])}</b>\n"
        msg += f"\u200f📊 {get_stat_line(mvp)}\n"
        # שינוי 5: ביטול תמונה בסיום (MVP)
        photo_url = None
    
    return msg, photo_url

def send_telegram(text, photo_url=None):
    payload = {"chat_id": CHAT_ID, "parse_mode": "HTML"}
    try:
        if photo_url:
            r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto", data={**payload, "photo": photo_url, "caption": text}, timeout=20)
            if r.status_code == 200: return
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={**payload, "text": text}, timeout=15)
    except: pass

def run():
    print("🚀 בוט NBA משודרג - גרסה מלאה (250+ שורות) - כולל הארכות ופוסטר כוכב ביתי!")
    while True:
        try:
            current_time = datetime.now().strftime("%H:%M:%S")
            print(f"🔍 [{current_time}] סורק משחקים...")
            resp = requests.get(NBA_URL, headers=HEADERS, timeout=10).json()
            games = resp.get('scoreboard', {}).get('games', [])

            for g in games:
                gid, status, period, txt = g['gameId'], g['gameStatus'], g.get('period', 0), g.get('gameStatusText', '').lower()
                if gid not in cache["games"]: cache["games"][gid] = []
                log = cache["games"][gid]
                game_final_key = "FINAL_SENT"

                # --- 1. הודעות יצא לדרך (רבע 1 עם חמישיות, רבע 3 פשוט) ---
                if status == 2 and period in [1, 3] and f"q{period}" in txt:
                    s_key = f"start_q{period}"
                    if (period == 1 or period == 3) and s_key not in log:
                        b_resp = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json", headers=HEADERS).json()
                        label = "המשחק יצא לדרך!" if period == 1 else f"רבע {period} יצא לדרך!"
                        m, p = format_msg(b_resp['game'], label, is_start=True)
                        send_telegram(m, p)
                        log.append(s_key)
                        save_cache()
                        print(f"✅ נשלחה פתיחת רבע {period}: {gid}")

                # --- 2. לוגיקת הארכה (שוויון בסיום רבע 4 ומעלה) ---
                if status == 2 and period >= 4 and "end" in txt and g['homeTeam']['score'] == g['awayTeam']['score']:
                    d_key = f"drama_period_{period}"
                    if d_key not in log:
                        b_resp = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json", headers=HEADERS).json()
                        m, p = format_msg(b_resp['game'], "דרמה ב-NBA!", is_drama=True)
                        send_telegram(m, p)
                        log.append(d_key)
                        log.append(txt) # מונע הודעת סיום רבע רגילה בשוויון
                        save_cache()
                        print(f"😱 נשלחה הודעת דרמה (הארכה): {gid}")

                # --- 3. הודעות סיום מסודרות ללא כפילויות ---
                if status == 3 and game_final_key not in log:
                   
                        b_resp = requests.get(
                            f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json",
                            headers=HEADERS
                        ).json()

                        m, p = format_msg(b_resp['game'], "סיום המשחק", is_final=True)
                        send_telegram(m, p)

                        log.append(game_final_key)
                        save_cache()
                        print(f"🏁 נשלח סיום משחק {gid}")
                        
                # ⛔ אם המשחק לא הסתיים – מטפלים רק במחצית ורבעים
                elif status != 3:

                        # מחצית
                        if "half" in txt and txt not in log:
                            b_resp = requests.get(
                                f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json",
                                headers=HEADERS
                            ).json()

                            m, p = format_msg(b_resp['game'], "סיום מחצית")
                            send_telegram(m, p)

                            log.append(txt)
                            save_cache()
                            print(f"⏸ נשלחה מחצית {gid}")

                        # סיום רבע רגיל (רק רבעים 1-3)
                        elif "end" in txt and txt not in log and period < 4:
                            b_resp = requests.get(
                                f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json",
                                headers=HEADERS
                            ).json()

                            m, p = format_msg(b_resp['game'], f"סיום רבע {period}")
                            send_telegram(m, p)

                            log.append(txt)
                            save_cache()
                            print(f"⏱ נשלח סיום רבע {period} {gid}")

                        # סיום הארכה בלבד
                        elif "end" in txt and txt not in log and period > 4:
                            b_resp = requests.get(
                                f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json",
                                headers=HEADERS
                            ).json()

                            m, p = format_msg(b_resp['game'], f"סיום הארכה {period-4}")
                            send_telegram(m, p)

                            log.append(txt)
                            save_cache()
                            print(f"⏱ נשלחה הארכה {gid}")

        except Exception as e:
            print(f"❌ שגיאה בלוגיקה: {e}")
        
        time.sleep(15)

if __name__ == "__main__":
    run()


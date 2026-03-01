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
    "LA Clippers": "לאק קליפרס", "Los Angeles Lakers": "לוס אנג'לס לייקרס",
    "Memphis Grizzlies": "ממפיס גריזליס", "Miami Heat": "מיאמי היט",
    "Milwaukee Bucks": "מילווקי באקס", "Minnesota Timberwolves": "מינסוטה טימברוולבס",
    "New Orleans Pelicans": "ניו אורלינס פליקנס", "New York Knicks": "ניו יורק ניקס",
    "Oklahoma City Thunder": "אוקלהומה סיטי ת'אנדר", "Orlando Magic": "אורלנדו מג'יק",
    "Philadelphia 76ers": "פילדלפיה 76", "Phoenix Suns": "פיניקס סאנס",
    "Portland Trail Blazers": "פורטלנד טרייל בלייזרס", "Sacramento Kings": "סקרמנטו קינגס",
    "San Antonio Spurs": "סן אנתוניו ספרס", "Toronto Raptors": "טורונטו ראפטורס",
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
    
    # בדיקה אם השם המלא מכיל את שם הקבוצה המוכר
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
    except:
        return name

def get_stat_line(p):
    s = p['statistics']
    line = f"{s['points']} נק', {s['reboundsTotal']} רב', {s['assists']} אס'"
    if s.get('steals', 0) > 0: line += f", {s['steals']} חט'"
    if s.get('blocks', 0) > 0: line += f", {s['blocks']} חס'"
    return line

def format_msg(box, label, is_final=False, is_start=False):
    photo_url = None
    away, home = box['awayTeam'], box['homeTeam']
    
    # שמות מלאים (עיר + שם קבוצה)
    a_full = translate_name(f"{away['teamCity']} {away['teamName']}")
    h_full = translate_name(f"{home['teamCity']} {home['teamName']}")
    
    period = box.get('period', 0)
    s_space = "ㅤ" 
    
    # חישוב Padding לכותרת
    combined_len = len(a_full) + len(h_full)
    padding = max(0, 22 - combined_len)
    
    header_emoji = "🏁" if is_final else ("🚀" if is_start else "⏱️")
    header_text = f"{header_emoji} <b>{label}</b> {header_emoji}"

    # סדר כותרות: הכותרת (למשל סיום מחצית) מופיעה תמיד מעל הקבוצות
    msg = f"\u200f{header_text}\n"
    msg += f"\u200f🏀 <b>{a_full} 🆚 {h_full}</b> 🏀{s_space * padding}\n\n"

    # הודעת יצא לדרך - מופיעה רק ברבע 1 (עם חמישיות) וברבע 3 (בלי)
    if is_start:
        if period == 1:
            for team in [away, home]:
                t_name = translate_name(team['teamName'])
                starters = [translate_name(f"{p['firstName']} {p['familyName']}") for p in team['players'] if p.get('starter') == '1']
                out = [translate_name(f"{p['firstName']} {p['familyName']}") for p in team['players'] if p.get('status') == 'INACTIVE']
                msg += f"\u200f📍 <b>חמישיית {t_name}:</b>\n"
                msg += f"\u200f{', '.join(starters) if starters else 'טרם פורסם'}\n"
                if out: msg += f"\u200f❌ <b>חיסורים:</b> {', '.join(out[:5])}\n"
                msg += "\n"
        return msg, photo_url

    # לוגיקת תוצאה ומובילה
    leader_name = a_full if away['score'] > home['score'] else h_full
    score_str = f"<b>{max(away['score'], home['score'])} - {min(away['score'], home['score'])}</b>"
    win_emoji = "🏆" if is_final else "🔥"
    
    if away['score'] == home['score']:
        msg += f"\u200f🔥 <b>שוויון {score_str}</b> 🔥\n\n"
    else:
        action = "מנצחת" if is_final else "מובילה"
        msg += f"\u200f{win_emoji} <b>{leader_name} {action} {score_str}</b> {win_emoji}\n\n"

    # סטטיסטיקות שחקנים (3 בסוף משחק/רבע 4, 2 בשאר)
    count = 3 if (period >= 4 or is_final) else 2
    for team in [away, home]:
        msg += f"\u200f📍 <b>{translate_name(team['teamName'])}:</b>\n"
        top = sorted([p for p in team['players'] if p['statistics']['points'] > 0], 
                     key=lambda x: x['statistics']['points'], reverse=True)[:count]
        for i, p in enumerate(top):
            medal = ["🥇", "🥈", "🥉"][i]
            p_full = translate_name(f"{p['firstName']} {p['familyName']}")
            msg += f"\u200f{medal} <b>{p_full}</b>: {get_stat_line(p)}\n"
        msg += "\n"

    if is_final:
        all_p = away['players'] + home['players']
        mvp = max(all_p, key=lambda x: x['statistics']['points'] + x['statistics']['reboundsTotal'] + x['statistics']['assists'])
        mvp_full_name = translate_name(f"{mvp['firstName']} {mvp['familyName']}")
        msg += f"\u200f🏆 <b>ה-MVP של המשחק: {mvp_full_name}</b>\n"
        msg += f"\u200f📊 {get_stat_line(mvp)}\n"
        photo_url = f"https://a.espncdn.com/combiner/i?img=/i/headshots/nba/players/full/{mvp['personId']}.png&w=420&h=310"
    
    return msg, photo_url

def send_telegram(text, photo_url=None):
    payload = {"chat_id": CHAT_ID, "parse_mode": "HTML"}
    try:
        if photo_url and photo_url.strip():
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
            r = requests.post(url, data={**payload, "photo": photo_url, "caption": text}, timeout=20)
            if r.status_code == 200: return
            else: print(f"Photo failed: {r.text}")
        
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={**payload, "text": text}, timeout=15)
    except Exception as e:
        print(f"Telegram Error: {e}")

def run():
    print("🚀 בוט NBA משודרג באוויר - גרסת 230 שורות מלאה...")
    while True:
        current_time = datetime.now().strftime("%H:%M:%S")
        print(f"🔍 [{current_time}] סורק משחקים...")
        
        try:
            response = requests.get(NBA_URL, headers=HEADERS, timeout=10)
            if response.status_code != 200:
                time.sleep(15)
                continue
                
            resp = response.json()
            games = resp.get('scoreboard', {}).get('games', [])

            for g in games:
                gid, status, period = g['gameId'], g['gameStatus'], g.get('period', 0)
                txt = g.get('gameStatusText', '').lower()
                
                if gid not in cache["games"]: cache["games"][gid] = []
                log = cache["games"][gid]

                # --- הודעות יצא לדרך (רק רבע 1 ורבע 3) ---
                if status == 2:
                    is_start_time = "12:00" in txt or "q"+str(period) in txt
                    
                    # רבע 1 - כולל חמישיות וחיסורים
                    if period == 1 and is_start_time and "start_q1" not in log:
                        box_resp = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json", headers=HEADERS)
                        if box_resp.status_code == 200:
                            box = box_resp.json()['game']
                            msg, p = format_msg(box, "המשחק יצא לדרך!", is_start=True)
                            send_telegram(msg, p)
                            log.append("start_q1")
                            print(f"✅ נשלחה פתיחת משחק: {gid}")

                    # רבע 3 - הודעה קצרה ללא חמישיות
                    if period == 3 and is_start_time and "start_q3" not in log:
                        box_resp = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json", headers=HEADERS)
                        if box_resp.status_code == 200:
                            box = box_resp.json()['game']
                            msg, p = format_msg(box, "רבע 3 יצא לדרך!", is_start=True)
                            send_telegram(msg, p)
                            log.append("start_q3")
                            print(f"✅ נשלחה פתיחת רבע 3: {gid}")

                # --- הודעות סיום (רבעים, מחצית, משחק) ---
                if ("end" in txt or "half" in txt or status == 3) and txt not in log:
                    box_resp = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json", headers=HEADERS)
                    if box_resp.status_code == 200:
                        box = box_resp.json()['game']
                        
                        if status == 3: label = "סיום המשחק"
                        elif "half" in txt: label = "סיום מחצית"
                        else: label = f"סיום רבע {period}"
                        
                        m, p = format_msg(box, label, is_final=(status == 3))
                        send_telegram(m, p)
                        log.append(txt)
                        save_cache()
                        print(f"✅ נשלח עדכון {label} למשחק {gid}")

        except Exception as e: 
            print(f"❌ Error logic: {e}")
        
        time.sleep(15)

if __name__ == "__main__":
    run()

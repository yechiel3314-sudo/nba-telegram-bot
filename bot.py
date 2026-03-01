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
                return json.load(f)
        except: pass
    return {"names": {}, "games": {}}

cache = load_cache()

def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=4, ensure_ascii=False)

def translate_name(name):
    if not name: return ""
    if name in NBA_TEAMS_HEBREW: return NBA_TEAMS_HEBREW[name]
    if name in cache["names"]: return cache["names"][name]
    
    try:
        # ניקוי השם לפני תרגום לתוצאה טובה יותר
        clean_name = name.replace("Jr.", "").replace("Sr.", "").strip()
        res = translator.translate(clean_name)
        # תיקונים ידניים לתרגומים נפוצים של גוגל
        res = res.replace("שקנאים", "פליקנס").replace("ג'ז", "ג'אז").replace("ניקס של ניו יורק", "ניו יורק ניקס")
        cache["names"][name] = res
        save_cache()
        return res
    except:
        return name

def get_stat_line(p):
    s = p['statistics']
    return f"{s['points']} נק', {s['reboundsTotal']} רב', {s['assists']} אס'"

def format_msg(box, label, is_final=False, is_start=False):
    photo_url = None
    away, home = box['awayTeam'], box['homeTeam']
    a_name, h_name = translate_name(away['teamName']), translate_name(home['teamName'])
    period = box.get('period', 0)
    s_space = "ㅤ" 
    
    combined_len = len(a_name) + len(h_name)
    padding = max(0, 20 - combined_len)
    
    header_emoji = "🏁" if is_final else ("🚀" if is_start else "⏱️")
    header_text = f"{header_emoji} <b>{label}</b> {header_emoji}"

    # סדר כותרות: תמיד הכותרת (סיום רבע/מחצית) מעל שמות הקבוצות
    msg = f"\u200f{header_text}\n"
    msg += f"\u200f🏀 <b>{a_name} 🆚 {h_name}</b> 🏀{s_space * padding}\n\n"

    if is_start:
        for team in [away, home]:
            t_name = translate_name(team['teamName'])
            starters = [translate_name(f"{p['firstName']} {p['familyName']}") for p in team['players'] if p.get('starter') == '1']
            msg += f"\u200f📍 <b>חמישיית {t_name}:</b>\n"
            msg += f"\u200f{', '.join(starters) if starters else 'טרם פורסם'}\n\n"
        return msg, photo_url

    leader_name = a_name if away['score'] > home['score'] else h_name
    score_str = f"<b>{max(away['score'], home['score'])} - {min(away['score'], home['score'])}</b>"
    win_emoji = "🏆" if is_final else "🔥"
    
    if away['score'] == home['score']:
        msg += f"\u200f🔥 <b>שוויון {score_str}</b> 🔥\n\n"
    else:
        action = "מנצחת" if is_final else "מובילה"
        msg += f"\u200f{win_emoji} <b>{leader_name} {action} {score_str}</b> {win_emoji}\n\n"

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
            r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto", data={**payload, "photo": photo_url, "caption": text}, timeout=20)
            if r.status_code == 200: return
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={**payload, "text": text}, timeout=15)
    except Exception as e: print(f"❌ Telegram Error: {e}")

def run():
    print("🚀 בוט NBA משודרג באוויר - סדר הודעות מתוקן ותרגום משופר...")
    while True:
        current_time = datetime.now().strftime("%H:%M:%S")
        print(f"🔍 [{current_time}] סורק משחקים...")
        try:
            response = requests.get(NBA_URL, headers=HEADERS, timeout=10)
            if response.status_code == 200:
                games = response.json().get('scoreboard', {}).get('games', [])
                for g in games:
                    gid, status, period = g['gameId'], g['gameStatus'], g.get('period', 0)
                    txt = g.get('gameStatusText', '').lower()
                    
                    if gid not in cache["games"]: cache["games"][gid] = []
                    log = cache["games"][gid]

                    # זיהוי פתיחת רבע (1, 2, 3, 4)
                    start_key = f"start_q{period}"
                    if status == 2 and ("12:00" in txt or "q"+str(period) in txt) and start_key not in log:
                        box_resp = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json", headers=HEADERS)
                        if box_resp.status_code == 200:
                            box = box_resp.json()['game']
                            label = "המשחק יצא לדרך!" if period == 1 else f"רבע {period} יצא לדרך!"
                            msg, p = format_msg(box, label, is_start=True)
                            send_telegram(msg, p)
                            log.append(start_key)
                            print(f"✅ נשלחה פתיחת רבע {period} למשחק {gid}")

                    # זיהוי סיום רבע / מחצית / משחק
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

        except Exception as e: print(f"❌ Error: {e}")
        time.sleep(15)

if __name__ == "__main__":
    run()

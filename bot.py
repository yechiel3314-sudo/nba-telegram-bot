import requests
import time
import json
import os
from deep_translator import GoogleTranslator

# ==========================================
# הגדרות מערכת וטוקנים
# ==========================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
CACHE_FILE = "nba_cache.json"

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
    "San Antonio Spurs": "סן אנטוניו ספרס", "Toronto Raptors": "טורונטו ראפפורס",
    "Utah Jazz": "יוטה ג'אז", "Washington Wizards": "וושינגטון וויזארדס"
}

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"names": {}, "games": {}}

cache = load_cache()

def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=4, ensure_ascii=False)

def translate_name(name):
    if name in NBA_TEAMS_HEBREW: return NBA_TEAMS_HEBREW[name]
    for en, heb in NBA_TEAMS_HEBREW.items():
        if name.lower() in en.lower(): return heb
    if name in cache["names"]: return cache["names"][name]
    try:
        res = translator.translate(name)
        res = res.replace("שקנאים", "ניו אורלינס פליקנס").replace("ג'ז", "יוטה ג'אז")
        cache["names"][name] = res
        return res
    except: return name

def get_stat_line(p):
    s = p['statistics']
    return f"<b>{s['points']}</b> נק', <b>{s['reboundsTotal']}</b> רב', <b>{s['assists']}</b> אס'"

def format_msg(box, label, is_final=False):
    away, home = box['awayTeam'], box['homeTeam']
    a_name, h_name = translate_name(away['teamName']), translate_name(home['teamName'])
    period = box.get('period', 0)
    
    header = f"🏁 <b>{label}</b> 🏁" if is_final else f"⏱️ <b>{label}</b>"
    if "דרמה" in label: header = f"😱 <b>{label}</b> 😱"
    elif "יצא לדרך" in label: header = f"🚀 <b>{label}</b>"

    msg = f"\u200f{header}\n"
    msg += f"\u200f🏀 <b>{a_name} 🆚 {h_name}</b> 🏀\n\n"

    # הודעת "יצא לדרך" עם חמישיות וחיסורים
    if "יצא לדרך" in label:
        for team in [away, home]:
            t_name = translate_name(team['teamName'])
            starters = [translate_name(f"{p['firstName']} {p['familyName']}") for p in team['players'] if p.get('starter') == '1']
            out = [translate_name(f"{p['firstName']} {p['familyName']}") for p in team['players'] if p.get('status') == 'INACTIVE']
            
            msg += f"\u200f📍 <b>חמישיית {t_name}:</b>\n"
            msg += f"\u200f{', '.join(starters) if starters else 'טרם פורסם'}\n"
            if out:
                msg += f"\u200f❌ <b>חיסורים:</b> {', '.join(out[:5])}\n"
            msg += "\n"
        return msg, None

    leader_name = a_name if away['score'] > home['score'] else h_name
    action = "מנצחת" if is_final else "מובילה"
    score_str = f"<b>{max(away['score'], home['score'])} - {min(away['score'], home['score'])}</b>"
    
    if away['score'] == home['score']:
        msg += f"\u200f🔥 <b>שוויון {score_str}</b> 🔥\n\n"
    else:
        msg += f"\u200f🔥 <b>{leader_name} {action} {score_str}</b> 🔥\n\n"

    if "דרמה" in label: return msg, None

    count = 3 if (period >= 4 or is_final) else 2
    for team in [away, home]:
        msg += f"\u200f📍 <b>סטטיסטיקה {translate_name(team['teamName'])}:</b>\n"
        top = sorted([p for p in team['players'] if p['statistics']['points'] > 0], 
                     key=lambda x: x['statistics']['points'], reverse=True)[:count]
        for i, p in enumerate(top):
            medal = "🥇" if i == 0 else ("🥈" if i == 1 else "🥉")
            p_full = translate_name(f"{p['firstName']} {p['familyName']}")
            msg += f"\u200f{medal} <b>{p_full}</b>: {get_stat_line(p)}\n"
        msg += "\n"

    photo_url = None
    if is_final:
        # MVP אמיתי מכל המגרש
        all_p = away['players'] + home['players']
        mvp = max(all_p, key=lambda x: x['statistics']['points'])
        # תמונה של כוכב המארחת (Home Team) לפי ההוראה שלך
        home_star = max(home['players'], key=lambda x: x['statistics']['points'])
        
        msg += f"\u200f🏆 <b>ה-MVP של המשחק: {translate_name(f'{mvp['firstName']} {mvp['familyName']}')}</b>\n"
        msg += f"\u200f📊 {get_stat_line(mvp)}\n"
        
        # תמונת אקשן איכותית
        photo_url = f"https://cdn.nba.com/headshots/nba/latest/1040x760/{home_star['personId']}.png"

    return msg, photo_url

def send_telegram(text, photo_url=None):
    payload = {"chat_id": CHAT_ID, "parse_mode": "HTML"}
    if photo_url:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        payload.update({"photo": photo_url, "caption": text})
    else:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload.update({"text": text})
    try:
        requests.post(url, json=payload, timeout=15)
    except: pass

def run():
    print("🚀 הבוט המלא באוויר - כולל חמישיות, רבע 3 והארכות...")
    while True:
        try:
            resp = requests.get(NBA_URL, timeout=10).json()
            for g in resp.get('scoreboard', {}).get('games', []):
                gid, status, period = g['gameId'], g['gameStatus'], g.get('period', 0)
                txt = g.get('gameStatusText', '').lower()
                if gid not in cache["games"]: cache["games"][gid] = []
                log = cache["games"][gid]

                # 1. יצא לדרך (חמישיות וחיסורים)
                if status == 2 and period == 1 and "12:00" in txt and "start_game" not in log:
                    box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']
                    msg, _ = format_msg(box, "המשחק יצא לדרך!")
                    send_telegram(msg); log.append("start_game")

                # 2. רבע 3
                if period == 3 and ("start" in txt or "12:00" in txt) and "q3_s" not in log:
                    box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']
                    msg, _ = format_msg(box, "רבע 3 יצא לדרך")
                    send_telegram(msg); log.append("q3_s")

                # 3. סיומי רבעים/מחצית/משחק
                if ("end" in txt or "half" in txt or status == 3) and txt not in log:
                    box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']
                    if period == 4 and "end" in txt and box['awayTeam']['score'] == box['homeTeam']['score'] and "drama" not in log:
                        msg, _ = format_msg(box, "דרמה ב-NBA: הולכים להארכה!")
                        send_telegram(msg); log.append("drama")
                    
                    label = "סיום המשחק" if status == 3 else ("מחצית" if "half" in txt else f"סיום רבע {period}")
                    m, p = format_msg(box, label, is_final=(status == 3))
                    send_telegram(m, p); log.append(txt); save_cache()

                # 4. התחלת הארכה
                if period > 4 and "start" in txt and f"ot{period}_s" not in log:
                    box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']
                    msg, _ = format_msg(box, f"הארכה {period-4} יצאה לדרך!")
                    send_telegram(msg); log.append(f"ot{period}_s")

        except: pass
        time.sleep(15)

if __name__ == "__main__":
    run()

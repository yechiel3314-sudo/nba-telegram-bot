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
    "San Antonio Spurs": "סן אנתוניו ספרס", "Toronto Raptors": "טורונטו ראפטורס",
    "Utah Jazz": "יוטה ג'אז", "Washington Wizards": "וושינגטון וויזארדס"
}

def load_cache():
    # גרסה נקייה שמוחקת את הזיכרון הישן כדי שהתמונות יישלחו מחדש כעת
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
    return f"{s['points']} נק', {s['reboundsTotal']} רב', {s['assists']} אס'"

def format_msg(box, label, is_final=False):
    away, home = box['awayTeam'], box['homeTeam']
    a_name, h_name = translate_name(away['teamName']), translate_name(home['teamName'])
    period = box.get('period', 0)
    
    s = "ㅤ" 
    
    header = f"🏁 <b>{label}</b> 🏁" if is_final else f"⏱️ <b>{label}</b>"
    if "דרמה" in label: header = f"😱 <b>{label}</b> 😱"
    elif "יצא לדרך" in label: header = f"🚀 <b>{label}</b>"

    wide_header = f"\u200f🏀{s*12}<b>{a_name} 🆚 {h_name}</b>{s*12}🏀"

    photo_url = None 

    if "יצא לדרך" in label:
        for team in [away, home]:
            t_name = translate_name(team['teamName'])
            starters = [translate_name(f"{p['firstName']} {p['familyName']}") for p in team['players'] if p.get('starter') == '1']
            out = [translate_name(f"{p['firstName']} {p['familyName']}") for p in team['players'] if p.get('status') == 'INACTIVE']
            msg += f"\u200f📍 <b>חמישיית {t_name}:</b>\n"
            msg += f"\u200f{', '.join(starters) if starters else 'טרם פורסם'}\n"
            if out: msg += f"\u200f❌ <b>חיסורים:</b> {', '.join(out[:5])}\n"
            msg += "\n"
        return msg, photo_url

    leader_name = a_name if away['score'] > home['score'] else h_name
    action = "מנצחת" if is_final else "מובילה"
    score_str = f"<b>{max(away['score'], home['score'])} - {min(away['score'], home['score'])}</b>"
    
    # שינוי האימוג'י בסיום משחק ל-🏆 כפי שביקשת
    win_emoji = "🏆" if is_final else "🔥"
    
    if away['score'] == home['score']:
        msg += f"\u200f🔥 <b>שוויון {score_str}</b> 🔥\n\n"
    else:
        msg += f"\u200f{win_emoji} <b>{leader_name} {action} {score_str}</b> {win_emoji}\n\n"

    if "דרמה" in label: return msg, photo_url

    count = 3 if (period >= 4 or is_final) else 2
    for team in [away, home]:
        # משאיר רק את שם הקבוצה עם האייקון, בלי המילה "סטטיסטיקה"
        msg += f"\u200f📍 <b>{translate_name(team['teamName'])}:</b>\n"
        top = sorted([p for p in team['players'] if p['statistics']['points'] > 0], 
                     key=lambda x: x['statistics']['points'], reverse=True)[:count]
        for i, p in enumerate(top):
            medal = "🥇" if i == 0 else ("🥈" if i == 1 else "🥉")
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
    # שליחה בפורמט data במקום json פותרת את בעיית הצגת התמונות מכתובת URL
    payload = {"chat_id": CHAT_ID, "parse_mode": "HTML"}
    
    try:
        if photo_url and photo_url.strip():
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
            # שימוש ב-data=payload במקום json=payload
            r = requests.post(url, data={**payload, "photo": photo_url, "caption": text}, timeout=20)
            if r.status_code == 200:
                return
            else:
                print(f"Photo failed: {r.text}")
        
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={**payload, "text": text}, timeout=15)
        
    except Exception as e:
        print(f"Telegram Error: {e}")

def run():
    print("🚀 בוט NBA באוויר - גרסת תמונות וגביעים...")
    while True:
        try:
            response = requests.get(NBA_URL, timeout=10)
            if response.status_code != 200:
                time.sleep(15)
                continue
                
            resp = response.json()
            if 'scoreboard' not in resp or 'games' not in resp['scoreboard']:
                time.sleep(15)
                continue

            for g in resp['scoreboard']['games']:
                gid, status, period = g['gameId'], g['gameStatus'], g.get('period', 0)
                txt = g.get('gameStatusText', '').lower()
                
                if gid not in cache["games"]: 
                    cache["games"][gid] = []
                log = cache["games"][gid]

                if status == 2 and period == 1 and ("12:00" in txt or "q1" in txt) and "start_alert" not in log:
                    box_resp = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json")
                    if box_resp.status_code == 200:
                        box = box_resp.json()['game']
                        msg, p = format_msg(box, "המשחק יצא לדרך!")
                        send_telegram(msg, p)
                        log.append("start_alert")

                if ("end" in txt or "half" in txt or status == 3) and txt not in log:
                    box_resp = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json")
                    if box_resp.status_code == 200:
                        box = box_resp.json()['game']
                        label = "סיום המשחק" if status == 3 else ("מחצית" if "half" in txt else f"סיום רבע {period}")
                        m, p = format_msg(box, label, is_final=(status == 3))
                        send_telegram(m, p)
                        log.append(txt)
                        save_cache()

        except Exception as e: 
            print(f"Error logic: {e}")
        time.sleep(15)

if __name__ == "__main__":
    run()









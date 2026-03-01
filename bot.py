import requests
import time
import json
import os
from deep_translator import GoogleTranslator

# ==========================================
# הגדרות מערכת
# ==========================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
CACHE_FILE = "nba_cache.json"

translator = GoogleTranslator(source='en', target='iw')

# ==========================================
# ניהול תרגום וזיכרון
# ==========================================

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"names": {}, "games": {}}

cache = load_cache()

def translate_name(name):
    """תרגום שם שחקן/קבוצה ושמירה בזיכרון"""
    if name in cache["names"]:
        return cache["names"][name]
    try:
        res = translator.translate(name)
        cache["names"][name] = res
        return res
    except:
        return name

# ==========================================
# עיצוב הודעות
# ==========================================

def get_stat_line(p):
    s = p['statistics']
    return f"{s['points']} נק', {s['reboundsTotal']} רב', {s['assists']} אס'"

def format_msg(box, label, is_final=False):
    away, home = box['awayTeam'], box['homeTeam']
    a_name = translate_name(away['teamName'])
    h_name = translate_name(home['teamName'])
    period = box.get('period', 0)
    
    # אייקון כותרת
    icon = "🏁" if is_final else ("🚀" if "יצא לדרך" in label else "⏱️")
    if "דרמה" in label: icon = "😱"

    msg = f"\u200f{icon} **{label}**\n"
    msg += f"\u200f🏀 **{a_name} 🆚 {h_name}** 🏀\n"

    # שורת תוצאה
    leader = a_name if away['score'] > home['score'] else h_name
    if away['score'] == home['score']:
        msg += f"\u200f🔥 **שוויון {away['score']} - {home['score']}** 🔥\n\n"
    else:
        msg += f"\u200f🔥 **{leader} מובילה {max(away['score'], home['score'])} - {min(away['score'], home['score'])}** 🔥\n\n"

    if "יצא לדרך" in label or "דרמה" in label:
        return msg, None

    # לוגיקת כמות שחקנים: 
    # רבע 4, הארכות וסיום = 3 שחקנים. רבעים 1-3 = 2 שחקנים.
    count = 3 if (period >= 4 or is_final) else 2

    for team in [away, home]:
        t_heb = translate_name(team['teamName'])
        msg += f"\u200f📍 **{t_heb}**\n"
        top = sorted(team['players'], key=lambda x: x['statistics']['points'], reverse=True)[:count]
        for i, p in enumerate(top):
            medal = "🥇" if i == 0 else ("🥈" if i == 1 else "🥉")
            p_full = translate_name(f"{p['firstName']} {p['familyName']}")
            msg += f"\u200f{medal} **{p_full}**: {get_stat_line(p)}\n"
        msg += "\n"

    # תמונת MVP בסיום (גם לאחר הארכות)
    photo_url = None
    if is_final:
        mvp = max(away['players'] + home['players'], key=lambda x: x['statistics']['points'])
        mvp_name = translate_name(f"{mvp['firstName']} {mvp['familyName']}")
        msg += f"\u200f⭐ **ה-MVP של הלילה: {mvp_name}**\n"
        msg += f"\u200f📊 {get_stat_line(mvp)}"
        photo_url = f"https://ak-static.cms.nba.com/wp-content/uploads/headshots/nba/latest/260x190/{mvp['personId']}.png"

    return msg, photo_url

# ==========================================
# שליחה לטלגרם
# ==========================================

def send_telegram(text, photo_url=None):
    if photo_url:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        payload = {"chat_id": CHAT_ID, "photo": photo_url, "caption": text, "parse_mode": "Markdown"}
    else:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except: pass

# ==========================================
# לוגיקה ראשית
# ==========================================

def run():
    print("🚀 הבוט התחיל (בדיקה כל 15 שניות)...")
    while True:
        try:
            resp = requests.get(NBA_URL, timeout=10).json()
            for g in resp['scoreboard']['games']:
                gid = g['gameId']
                status = g['gameStatus']
                txt = g.get('gameStatusText', '').lower()
                period = g.get('period', 0)
                
                if gid not in cache["games"]: cache["games"][gid] = []
                log = cache["games"][gid]

                # 1. פתיחת רבע 3
                if period == 3 and "q3" in txt and "start" in txt and "q3_s" not in log:
                    box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']
                    msg, _ = format_msg(box, "רבע 3 יצא לדרך")
                    send_telegram(msg)
                    log.append("q3_s")

                # 2. סיום רבעים / משחק
                if ("end" in txt or "half" in txt or status == 3) and txt not in log:
                    box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']
                    
                    # נוהל דרמה (סיום רבע 4 בשוויון)
                    if period == 4 and "end" in txt and box['awayTeam']['score'] == box['homeTeam']['score'] and "drama" not in log:
                        msg, _ = format_msg(box, "דרמה ב-NBA: הולכים להארכה!")
                        send_telegram(msg)
                        log.append("drama")

                    # כותרת ההודעה
                    if status == 3: label = "סיום המשחק"
                    elif period > 4: label = f"סיום הארכה {period-4}"
                    else: label = "מחצית" if "half" in txt else f"סיום רבע {period}"
                    
                    msg_text, photo = format_msg(box, label, is_final=(status == 3))
                    send_telegram(msg_text, photo)
                    log.append(txt)
                    
                    with open(CACHE_FILE, "w", encoding="utf-8") as f:
                        json.dump(cache, f, indent=4, ensure_ascii=False)

                # 3. פתיחת הארכה
                if period > 4 and "ot" in txt and "start" in txt and f"ot{period}_s" not in log:
                    box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']
                    msg, _ = format_msg(box, f"הארכה {period-4} יצאה לדרך!")
                    send_telegram(msg)
                    log.append(f"ot{period}_s")

        except Exception as e: print(f"Error: {e}")
        time.sleep(15)

if __name__ == "__main__":
    run()

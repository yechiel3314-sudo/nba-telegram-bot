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

# מילון שמות מלא ומקצועי - מונע "שקנאים", "ג'ז" וקיצורים
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
    "San Antonio Spurs": "סן אנטוניו ספרס", "Toronto Raptors": "טורונטו ראפטורס",
    "Utah Jazz": "יוטה ג'אז", "Washington Wizards": "וושינגטון וויזארדס"
}

# ==========================================
# ניהול תרגום וזיכרון
# ==========================================

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
    """תרגום עם עדיפות למילון המלא למניעת שמות חלקיים"""
    if name in NBA_TEAMS_HEBREW:
        return NBA_TEAMS_HEBREW[name]
    if name in cache["names"]:
        return cache["names"][name]
    try:
        res = translator.translate(name)
        # תיקון ידני לתרגומים נפוצים של גוגל שנוטים להתקצר
        res = res.replace("שקנאים", "ניו אורלינס פליקנס").replace("ג'ז", "יוטה ג'אז")
        cache["names"][name] = res
        return res
    except:
        return name

# ==========================================
# עיצוב הודעות
# ==========================================

def get_stat_line(p):
    """פתרון מחוץ לקופסה: שימוש בתו \u200e (LTR mark) כדי להבטיח הדגשה בעברית"""
    s = p['statistics']
    ltr = "\u200e" 
    return f"{ltr}**{s['points']}**{ltr} נק', {ltr}**{s['reboundsTotal']}**{ltr} רב', {ltr}**{s['assists']}**{ltr} אס'"

def format_msg(box, label, is_final=False):
    away, home = box['awayTeam'], box['homeTeam']
    # שימוש בשמות המלאים מהמילון
    a_name = translate_name(away['teamName'])
    h_name = translate_name(home['teamName'])
    period = box.get('period', 0)
    
    if is_final:
        header = f"🏁 **{label}** 🏁"
    elif "דרמה" in label:
        header = f"😱 **{label}** 😱"
    elif "יצא לדרך" in label:
        header = f"🚀 **{label}**"
    else:
        header = f"⏱️ **{label}**"

    msg = f"\u200f{header}\n"
    msg += f"\u200f🏀 **{a_name} 🆚 {h_name}** 🏀\n\n"

    leader_name = a_name if away['score'] > home['score'] else h_name
    action = "מנצחת" if is_final else "מובילה"
    
    if away['score'] == home['score']:
        msg += f"\u200f🔥 **שוויון {away['score']} - {home['score']}** 🔥\n\n"
    else:
        msg += f"\u200f🔥 **{leader_name} {action} {max(away['score'], home['score'])} - {min(away['score'], home['score'])}** 🔥\n\n"

    if "יצא לדרך" in label or "דרמה" in label:
        return msg, None

    count = 3 if (period >= 4 or is_final) else 2

    for team in [away, home]:
        t_heb = translate_name(team['teamName'])
        msg += f"\u200f📍 **סטטיסטיקה {t_heb}:**\n"
        top = sorted(team['players'], key=lambda x: x['statistics']['points'], reverse=True)[:count]
        for i, p in enumerate(top):
            medal = "🥇" if i == 0 else ("🥈" if i == 1 else "🥉")
            p_full = translate_name(f"{p['firstName']} {p['familyName']}")
            msg += f"\u200f{medal} **{p_full}**: {get_stat_line(p)}\n"
        msg += "\n"

    photo_url = None
    if is_final:
        # דרישה: תמיד הכוכב של קבוצת הבית (Home Team)
        home_star = max(home['players'], key=lambda x: x['statistics']['points'])
        star_name = translate_name(f"{home_star['firstName']} {home_star['familyName']}")
        msg += f"\u200f⭐ **ה-MVP של המשחק: {star_name}**\n"
        msg += f"\u200f📊 {get_stat_line(home_star)}"
        # תמונת אקשן בגודל מלא
        photo_url = f"https://cdn.nba.com/headshots/nba/latest/1040x760/{home_star['personId']}.png"

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
        r = requests.post(url, json=payload, timeout=12)
        if photo_url and r.status_code != 200:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                          json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})
    except: pass

# ==========================================
# לוגיקה ראשית
# ==========================================

def run():
    print("🚀 הבוט באוויר - סורק משחקים...")
    while True:
        try:
            resp = requests.get(NBA_URL, timeout=10).json()
            games = resp.get('scoreboard', {}).get('games', [])

            for g in games:
                gid, status, period = g['gameId'], g['gameStatus'], g.get('period', 0)
                txt = g.get('gameStatusText', '').lower()
                
                if gid not in cache["games"]: cache["games"][gid] = []
                log = cache["games"][gid]

                # פתיחת רבע 3
                if period == 3 and ("start" in txt or "12:00" in txt) and "q3_s" not in log:
                    box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']
                    msg, _ = format_msg(box, "רבע 3 יצא לדרך")
                    send_telegram(msg); log.append("q3_s")

                # סיום רבעים / משחק
                if ("end" in txt or "half" in txt or status == 3) and txt not in log:
                    box_resp = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()
                    box = box_resp['game']
                    
                    if period == 4 and "end" in txt and box['awayTeam']['score'] == box['homeTeam']['score'] and "drama" not in log:
                        msg, _ = format_msg(box, "דרמה ב-NBA: הולכים להארכה!")
                        send_telegram(msg); log.append("drama")

                    if status == 3: label = "סיום המשחק"
                    elif period > 4: label = f"סיום הארכה {period-4}"
                    else: label = "מחצית" if "half" in txt else f"סיום רבע {period}"
                    
                    msg_text, photo = format_msg(box, label, is_final=(status == 3))
                    send_telegram(msg_text, photo)
                    log.append(txt); save_cache()

                # פתיחת הארכה
                if period > 4 and "start" in txt and f"ot{period}_s" not in log:
                    box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']
                    msg, _ = format_msg(box, f"הארכה {period-4} יצאה לדרך!")
                    send_telegram(msg); log.append(f"ot{period}_s")

        except Exception as e: print(f"Error: {e}")
        time.sleep(15)

if __name__ == "__main__":
    run()

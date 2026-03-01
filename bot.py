import requests
import time
import json
import os
from googletrans import Translator

# =================================================================
# הגדרות מערכת - גרסה מלאה (220 שורות) עם Google Translate
# =================================================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
CACHE_FILE = "nba_bot_cache.json"

translator = Translator()

# מילון תיקונים ידני - הוספתי את אבדיה והארדן כפי שביקשת
PLAYER_OVERRIDES = {
    "Deni Avdija": "דני אבדיה",
    "James Harden": "ג'יימס הארדן",
    "Jrue Holiday": "ג'רו הולידיי",
    "Giannis Antetokounmpo": "יאניס אנדטוקומבו",
    "Shai Gilgeous-Alexander": "שיי גילג'ס-אלכסנדר",
    "Luka Doncic": "לוקה דונצ'יץ'",
    "Nikola Jokic": "ניקולה יוקיץ'",
    "Joel Embiid": "ג'ואל אמביד",
    "Tyrese Haliburton": "טייריס הליברטון",
    "Domantas Sabonis": "דומנטאס סאבוניס",
    "Kristaps Porzingis": "קריסטפס פורזינגיס",
    "Victor Wembanyama": "ויקטור וומבניאמה",
    "Chet Holmgren": "צ'ט הולמגרן",
    "Alperen Sengun": "אלפרן שנגון",
    "Karl-Anthony Towns": "קארל-אנתוני טאונס",
    "Kyrie Irving": "קיירי אירווינג",
    "Anthony Edwards": "אנתוני אדוארדס",
    "Kevin Durant": "קוין דוראנט",
    "Stephen Curry": "סטפן קרי",
    "LeBron James": "לברון ג'יימס",
    "Devin Booker": "דבין בוקר",
    "Jayson Tatum": "ג'ייסון טייטום",
    "Jaylen Brown": "ג'יילן בראון",
    "Damian Lillard": "דמיאן לילארד",
    "Donovan Mitchell": "דונובן מיטשל",
    "Ja Morant": "ג'ה מוראנט",
    "Zion Williamson": "זאיון וויליאמסון",
    "Trae Young": "טריי יאנג",
    "De'Aaron Fox": "דיארון פוקס",
    "Kawhi Leonard": "קוואי לנארד",
    "Paul George": "פול ג'ורג'",
    "Jimmy Butler": "ג'ימי באטלר",
    "Bam Adebayo": "באם אדבאיו"
}

TEAM_TRANSLATIONS = {
    "Hawks": "אטלנטה הוקס", "Celtics": "בוסטון סלטיקס", "Nets": "ברוקלין נטס", 
    "Hornets": "שארלוט הורנטס", "Bulls": "שיקגו בולס", "Cavaliers": "קליבלנד קאבלירס", 
    "Mavericks": "דאלאס מאבריקס", "Nuggets": "דנבר נאגטס", "Pistons": "דטרויט פיסטונס", 
    "Warriors": "גולדן סטייט ווריורס", "Rockets": "יוסטון רוקטס", "Pacers": "אינדיאנה פייסרס", 
    "Clippers": "לוס אנג'לס קליפרס", "Lakers": "לוס אנג'לס לייקרס", "Grizzlies": "ממפיס גריזליס", 
    "Heat": "מיאמי היט", "Bucks": "מילווקי באקס", "Timberwolves": "מינסוטה טימברוולבס", 
    "Pelicans": "ניו אורלינס פליקנס", "Knicks": "ניו יורק ניקס", "Thunder": "אוקלהומה סיטי ת'אנדר", 
    "Magic": "אורלנדו מג'יק", "76ers": "פילדלפיה 76", "Suns": "פיניקס סאנס", 
    "Trail Blazers": "פורטלנד טרייל בלייזרס", "Kings": "סקרמנטו קינגס", "Spurs": "סן אנטוניו ספרס", 
    "Raptors": "טורונטו ראפטורס", "Jazz": "יוטה ג'אז", "Wizards": "וושינגטון ויזארדס"
}

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception: pass
    return {"names": {}, "games": {}}

cache = load_cache()

def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=4, ensure_ascii=False)

def translate_player_name(english_name):
    if english_name in PLAYER_OVERRIDES:
        return PLAYER_OVERRIDES[english_name]
    if english_name in cache["names"]:
        return cache["names"][english_name]
    try:
        translated = translator.translate(english_name, src='en', dest='he').text
        if translated:
            cache["names"][english_name] = translated
            save_cache()
            return translated
    except Exception: pass
    return english_name

def get_lineups_and_injuries(box):
    data = {"away": {"starters": [], "out": []}, "home": {"starters": [], "out": []}}
    for side in ['awayTeam', 'homeTeam']:
        key = 'away' if side == 'awayTeam' else 'home'
        players = box.get(side, {}).get('players', [])
        for p in players:
            p_full = f"{p['firstName']} {p['familyName']}"
            heb_name = translate_player_name(p_full)
            if p.get('starter') == "1":
                data[key]['starters'].append(heb_name)
            if p.get('status') == "INACTIVE":
                data[key]['out'].append(heb_name)
    return data

def get_stat_line(p):
    s = p['statistics']
    return f"{s['points']} נק', {s['reboundsTotal']} רב', {s['assists']} אס'"

def format_msg(box, label, is_final=False):
    away, home = box['awayTeam'], box['homeTeam']
    a_name = TEAM_TRANSLATIONS.get(away['teamName'], away['teamName'])
    h_name = TEAM_TRANSLATIONS.get(home['teamName'], home['teamName'])
    period = box.get('period', 0)
    rtl = "\u200f"
    def b(text): return f"<b>{str(text).strip()}</b>"

    # סטופר בצד אחד בתחילת השורה
    msg = f"{rtl}⏱️ {b(label)}\n"
    msg += f"{rtl}🏀 {b(a_name)} 🆚 {b(h_name)} 🏀\n\n"

    # הודעת פתיחה עם חמישיות ופוסטר כוכב הבית
    if "יצא לדרך" in label and period == 1:
        lineups = get_lineups_and_injuries(box)
        try:
            h_players = home.get('players', [])
            starters = [p for p in h_players if p.get('starter') == "1"]
            # פוסטר כוכב הבית
            p_id = starters[0]['personId'] if starters else home['teamId']
            photo_url = f"https://www.nba.com/stats/api/v1/playerActionPhoto/{p_id}"
        except:
            photo_url = f"https://cdn.nba.com/logos/leagues/L/nba/matchups/{away['teamId']}-vs-{home['teamId']}.png"

        for team_key, name in [('away', a_name), ('home', h_name)]:
            msg += f"{rtl}📍 {b(name)}\n"
            msg += f"{rtl}🏀 {b('חמישייה:')} {', '.join(lineups[team_key]['starters']) if lineups[team_key]['starters'] else 'טרם פורסם'}\n"
            if lineups[team_key]['out']:
                msg += f"{rtl}❌ {b('חיסורים:')} {', '.join(lineups[team_key]['out'][:5])}\n"
            msg += "\n"
        return msg, photo_url

    # הודעות תוצאה ורבעים
    leader = a_name if away['score'] > home['score'] else h_name
    verb = "מנצחת" if is_final else "מובילה"
    
    if away['score'] == home['score']:
        msg += f"{rtl}🔥 {b('שוויון ' + str(away['score']) + ' - ' + str(home['score']))} 🔥\n\n"
    else:
        msg += f"{rtl}🔥 {b(leader)} {verb} {b(str(max(away['score'], home['score'])) + ' - ' + str(min(away['score'], home['score'])))} 🔥\n\n"

    count = 3 if (period >= 4 or is_final) else 2
    for team, t_name in [(away, a_name), (home, h_name)]:
        msg += f"{rtl}📍 {b(t_name)}\n"
        players = sorted(team.get('players', []), key=lambda x: x['statistics']['points'], reverse=True)[:count]
        for i, p in enumerate(players):
            medal = ["🥇", "🥈", "🥉"][i]
            p_full = translate_player_name(f"{p['firstName']} {p['familyName']}")
            msg += f"{rtl}{medal} {b(p_full)}: {get_stat_line(p)}\n"
        msg += "\n"

    photo_url = None
    if is_final:
        all_p = away.get('players', []) + home.get('players', [])
        mvp = max(all_p, key=lambda x: x['statistics']['points'])
        msg += f"{rtl}⭐ {b('ה-MVP: ' + translate_player_name(f'{mvp[u'firstName']} {mvp[u'familyName']}'))}\n"
        msg += f"{rtl}📊 {get_stat_line(mvp)}"
        photo_url = f"https://www.nba.com/stats/api/v1/playerActionPhoto/{mvp['personId']}"

    return msg, photo_url

def send_telegram(text, photo_url=None):
    base_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    try:
        if photo_url:
            requests.post(f"{base_url}/sendPhoto", json={"chat_id": CHAT_ID, "photo": photo_url, "caption": text, "parse_mode": "HTML"}, timeout=15)
        else:
            requests.post(f"{base_url}/sendMessage", json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
    except Exception as e: print(f"Telegram Error: {e}")

def run():
    print("🚀 הבוט באוויר - גרסת טרנסלייט מלאה...")
    while True:
        try:
            resp = requests.get(NBA_URL, timeout=10).json()
            games = resp.get('scoreboard', {}).get('games', [])
            for g in games:
                gid, status, period = g['gameId'], g['gameStatus'], g['period']
                txt = g.get('gameStatusText', '').lower()
                
                if gid not in cache["games"]: cache["games"][gid] = []
                
                if ("end" in txt or "half" in txt or status == 3) and txt not in cache["games"][gid]:
                    box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']
                    label = "סיום המשחק" if status == 3 else ("מחצית" if "half" in txt else f"סיום רבע {period}")
                    msg, photo = format_msg(box, label, is_final=(status == 3))
                    send_telegram(msg, photo)
                    cache["games"][gid].append(txt)
                    save_cache()

                if "start" in txt and f"start_{period}" not in cache["games"][gid]:
                    box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']
                    label = "המשחק יצא לדרך" if period == 1 else f"רבע {period} יצא לדרך"
                    msg, photo = format_msg(box, label)
                    send_telegram(msg, photo)
                    cache["games"][gid].append(f"start_{period}")
                    save_cache()

        except Exception as e: print(f"Error: {e}")
        time.sleep(15)

if __name__ == "__main__":
    run()

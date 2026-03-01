import requests
import time
import json
import os
from google import genai

# =================================================================
# הגדרות מערכת - מפתח ה-API שלך מוטמע כאן בצורה מאובטחת
# =================================================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
GEMINI_API_KEY = "AIzaSyBljGNa2qMXfDXbJM3gI2ai88rbfepqcyQ"

# אתחול לקוח Google AI
client = genai.Client(api_key=GEMINI_API_KEY)

# מקורות נתונים
NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
CACHE_FILE = "nba_bot_cache.json"

# מילון תרגום קבוצות NBA לעברית
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

# =================================================================
# ניהול זיכרון (Cache)
# =================================================================

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"names": {}, "games": {}}

cache = load_cache()

def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=4, ensure_ascii=False)

# =================================================================
# תרגום שמות שחקנים בעזרת AI
# =================================================================

def get_team_name(eng_name):
    return TEAM_TRANSLATIONS.get(eng_name, eng_name)

def translate_player_name(english_name):
    if english_name in cache["names"]:
        return cache["names"][english_name]
    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=f"Translate the NBA player name '{english_name}' to Hebrew. Output ONLY the full name."
        )
        translated = response.text.strip()
        cache["names"][english_name] = translated
        save_cache()
        return translated
    except Exception as e:
        print(f"AI Error: {e}")
        return english_name

# =================================================================
# שליפת חמישיות וחיסורים
# =================================================================

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

# =================================================================
# בניית ההודעה ועיצוב פוסטרים
# =================================================================

def get_stat_line(p):
    s = p['statistics']
    return f"{s['points']} נק', {s['reboundsTotal']} רב', {s['assists']} אס'"

def format_msg(box, label, is_final=False):
    away, home = box['awayTeam'], box['homeTeam']
    a_name = get_team_name(away['teamName'])
    h_name = get_team_name(home['teamName'])
    period = box.get('period', 0)
    
    photo_url = None
    
    # --- הודעת פתיחה משופרת (חמישיות וחיסורים) ---
    if "יצא לדרך" in label and period == 1:
        header = f"🚀 **המשחק יצא לדרך**"
        msg = f"\u200f{header}\n"
        msg += f"\u200f🏀 **{a_name} 🆚 {h_name}** 🏀\n\n"
        
        lineups = get_lineups_and_injuries(box)
        
        # קבוצה א' (אורחת)
        msg += f"\u200f📍 **{a_name}**\n"
        msg += f"\u200f🏀 **חמישייה:** {', '.join(lineups['away']['starters']) if lineups['away']['starters'] else '(טרם פורסם)'}\n"
        if lineups['away']['out']:
            msg += f"\u200f❌ **חיסורים:** {', '.join(lineups['away']['out'][:5])}\n"
        msg += "\n"
        
        # קבוצה ב' (מארחת)
        msg += f"\u200f📍 **{h_name}**\n"
        msg += f"\u200f🏀 **חמישייה:** {', '.join(lineups['home']['starters']) if lineups['home']['starters'] else '(טרם פורסם)'}\n"
        if lineups['home']['out']:
            msg += f"\u200f❌ **חיסורים:** {', '.join(lineups['home']['out'][:5])}\n"
        msg += "\n"
            
        photo_url = f"https://cdn.nba.com/logos/leagues/L/nba/matchups/{away['teamId']}-vs-{home['teamId']}.png"
        return msg, photo_url

    # --- הודעות סיום/רבעים ---
    header = f"🏁 **{label}** 🏁" if is_final else f"⏱️ **{label}**"
    msg = f"\u200f{header}\n"
    msg += f"\u200f🏀 **{a_name} 🆚 {h_name}** 🏀\n\n"

    leader = a_name if away['score'] > home['score'] else h_name
    verb = "מנצחת" if is_final else "מובילה"
    
    if away['score'] == home['score']:
        msg += f"\u200f🔥 **שוויון {away['score']} - {home['score']}** 🔥\n\n"
    else:
        msg += f"\u200f🔥 **{leader} {verb} {max(away['score'], home['score'])} - {min(away['score'], home['score'])}** 🔥\n\n"

    count = 3 if (period >= 4 or is_final) else 2
    for team, t_name in [(away, a_name), (home, h_name)]:
        msg += f"\u200f📍 **{t_name}**\n"
        players = sorted(team.get('players', []), key=lambda x: x['statistics']['points'], reverse=True)[:count]
        for i, p in enumerate(players):
            medal = "🥇" if i == 0 else ("🥈" if i == 1 else "🥉")
            p_full = translate_player_name(f"{p['firstName']} {p['familyName']}")
            msg += f"\u200f{medal} **{p_full}**: {get_stat_line(p)}\n"
        msg += "\n"

    if is_final:
        all_p = away.get('players', []) + home.get('players', [])
        mvp = max(all_p, key=lambda x: x['statistics']['points'])
        mvp_name = translate_player_name(f"{mvp['firstName']} {mvp['familyName']}")
        msg += f"\u200f⭐ **ה-MVP של הלילה: {mvp_name}**\n"
        msg += f"\u200f📊 {get_stat_line(mvp)}"
        photo_url = f"https://www.nba.com/stats/api/v1/playerActionPhoto/{mvp['personId']}"

    return msg, photo_url

# =================================================================
# שליחה לטלגרם
# =================================================================

def send_telegram(text, photo_url=None):
    base_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    try:
        if photo_url:
            payload = {"chat_id": CHAT_ID, "photo": photo_url, "caption": text, "parse_mode": "Markdown"}
            requests.post(f"{base_url}/sendPhoto", json=payload, timeout=15)
        else:
            payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
            requests.post(f"{base_url}/sendMessage", json=payload, timeout=15)
    except Exception as e:
        print(f"Telegram Error: {e}")

# =================================================================
# לוגיקה ראשית
# =================================================================

def run():
    print("🚀 הבוט באוויר. בודק חמישיות ועדכונים...")
    while True:
        try:
            resp = requests.get(NBA_URL, timeout=10).json()
            games = resp.get('scoreboard', {}).get('games', [])
            for g in games:
                gid, status, period = g['gameId'], g['gameStatus'], g['period']
                txt = g.get('gameStatusText', '').lower()
                if gid not in cache["games"]: cache["games"][gid] = []
                game_log = cache["games"][gid]

                # סיום רבע / משחק
                if ("end" in txt or "half" in txt or status == 3) and txt not in game_log:
                    box_data = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']
                    label = "סיום המשחק" if status == 3 else ("מחצית" if "half" in txt else f"סיום רבע {period}")
                    msg, photo = format_msg(box_data, label, is_final=(status == 3))
                    send_telegram(msg, photo)
                    game_log.append(txt)
                    save_cache()

                # יצא לדרך
                if "start" in txt and f"start_{period}" not in game_log:
                    box_data = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']
                    label = "רבע 3 יצא לדרך" if period == 3 else (f"הארכה {period-4} יצאה לדרך" if period > 4 else f"רבע {period} יצא לדרך")
                    msg, photo = format_msg(box_data, label)
                    send_telegram(msg, photo)
                    game_log.append(f"start_{period}")
                    save_cache()

        except Exception as e:
            print(f"Polling Error: {e}")
        time.sleep(15)

if __name__ == "__main__":
    run()


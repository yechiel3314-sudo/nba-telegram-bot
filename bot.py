import requests
import time
import json
import os
from google import genai

# ==========================================
# הגדרות מערכת - הנתונים שלך מוטמעים כאן
# ==========================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
# המפתח שהוצאת מ-Google AI Studio (מנוקה מרווחים)
GEMINI_API_KEY = "AIzaSyD-L0K7H6v1Xj_n4X_k_X_l_X_X_JDHs" 

# אתחול הלקוח של גוגל
client = genai.Client(api_key=GEMINI_API_KEY)
NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
CACHE_FILE = "nba_bot_cache.json"

# מילון שמות קבוצות מלאים לעברית
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

# ==========================================
# ניהול זיכרון (Cache)
# ==========================================

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

# ==========================================
# פונקציות תרגום
# ==========================================

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
        print(f"AI Translation Error: {e}")
        return english_name

# ==========================================
# עיבוד נתונים ועיצוב הודעה
# ==========================================

def get_stat_line(p):
    s = p['statistics']
    return f"{s['points']} נק', {s['reboundsTotal']} רב', {s['assists']} אס'"

def format_msg(box, label, is_final=False):
    away, home = box['awayTeam'], box['homeTeam']
    a_name = get_team_name(away['teamName'])
    h_name = get_team_name(home['teamName'])
    period = box.get('period', 0)
    
    icon = "🏁" if is_final else ("🚀" if "יצא לדרך" in label else "⏱️")
    if "דרמה" in label: icon = "😱"

    msg = f"\u200f{icon} **{label}**\n"
    msg += f"\u200f🏀 **{a_name} 🆚 {h_name}** 🏀\n"

    leader = a_name if away['score'] > home['score'] else h_name
    if away['score'] == home['score']:
        msg += f"\u200f🔥 **שוויון {away['score']} - {home['score']}** 🔥\n\n"
    else:
        msg += f"\u200f🔥 **{leader} מובילה {max(away['score'], home['score'])} - {min(away['score'], home['score'])}** 🔥\n\n"

    if "יצא לדרך" in label or "דרמה" in label:
        return msg, None

    count = 3 if (period >= 4 or is_final) else 2
    for team, t_name in [(away, a_name), (home, h_name)]:
        msg += f"\u200f📍 **{t_name}**\n"
        players = team.get('players', [])
        top = sorted(players, key=lambda x: x['statistics']['points'], reverse=True)[:count]
        for i, p in enumerate(top):
            medal = "🥇" if i == 0 else ("🥈" if i == 1 else "🥉")
            p_full = translate_player_name(f"{p['firstName']} {p['familyName']}")
            msg += f"\u200f{medal} **{p_full}**: {get_stat_line(p)}\n"
        msg += "\n"

    photo_url = None
    if is_final:
        all_players = away.get('players', []) + home.get('players', [])
        if all_players:
            mvp = max(all_players, key=lambda x: x['statistics']['points'])
            mvp_name = translate_player_name(f"{mvp['firstName']} {mvp['familyName']}")
            msg += f"\u200f⭐ **ה-MVP של הלילה: {mvp_name}**\n"
            msg += f"\u200f📊 {get_stat_line(mvp)}"
            photo_url = f"https://ak-static.cms.nba.com/wp-content/uploads/headshots/nba/latest/260x190/{mvp['personId']}.png"

    return msg, photo_url

# ==========================================
# שליחה לטלגרם
# ==========================================

def send_telegram(text, photo_url=None):
    base_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    try:
        if photo_url:
            requests.post(f"{base_url}/sendPhoto", json={"chat_id": CHAT_ID, "photo": photo_url, "caption": text, "parse_mode": "Markdown"}, timeout=10)
        else:
            requests.post(f"{base_url}/sendMessage", json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

# ==========================================
# לוגיקה ראשית (Polling)
# ==========================================

def run():
    print("🚀 בוט ה-NBA באוויר. ממתין למשחקים...")
    while True:
        try:
            resp = requests.get(NBA_URL, timeout=10).json()
            games = resp.get('scoreboard', {}).get('games', [])
            for g in games:
                gid, status, period = g['gameId'], g['gameStatus'], g['period']
                txt = g.get('gameStatusText', '').lower()
                
                if gid not in cache["games"]: cache["games"][gid] = []
                game_log = cache["games"][gid]

                if ("end" in txt or "half" in txt or status == 3) and txt not in game_log:
                    box_resp = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()
                    box = box_resp['game']
                    label = "סיום המשחק" if status == 3 else ("מחצית" if "half" in txt else f"סיום רבע {period}")
                    msg_text, photo = format_msg(box, label, is_final=(status == 3))
                    send_telegram(msg_text, photo)
                    game_log.append(txt)
                    save_cache()

                if period >= 3 and "start" in txt and f"start_{period}" not in game_log:
                    box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']
                    label = "רבע 3 יצא לדרך" if period == 3 else f"הארכה {period-4} יצאה לדרך"
                    msg, _ = format_msg(box, label)
                    send_telegram(msg)
                    game_log.append(f"start_{period}")

        except Exception as e:
            print(f"Global Error: {e}")
        time.sleep(15)

if __name__ == "__main__":
    run()

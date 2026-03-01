import requests
import time
import json
import os
from google import genai

# =================================================================
# הגדרות מערכת - מצב HTML ליציבות מקסימלית
# =================================================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
GEMINI_API_KEY = "AIzaSyDyzsEfh0OAZymDcihDYEW0IjdJJaxQYoY" 
client = genai.Client(api_key=GEMINI_API_KEY)
NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
CACHE_FILE = "nba_bot_cache.json"

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
    if english_name in cache["names"]:
        return cache["names"][english_name]
    
    try:
        time.sleep(4.0) # המתנה של 4 שניות לדיוק מקסימלי ומניעת חסימות
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"Translate NBA player name '{english_name}' to Hebrew. Return ONLY the name."
        )
        translated = response.text.strip().replace("*", "")
        if translated and len(translated) < 40:
            cache["names"][english_name] = translated
            save_cache()
            return translated
    except Exception as e:
        print(f"AI Translation Error: {e}")
            
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

# --- הודעת פתיחה (חמישיות וחיסורים) ---
    if "יצא לדרך" in label and period == 1:
        msg = f"{rtl}⏱️ {b('המשחק יצא לדרך')}\n"
        msg += f"{rtl}🏀 {b(a_name)} 🆚 {b(h_name)} 🏀\n\n"
        
        lineups = get_lineups_and_injuries(box)
        
        # --- בחירת פוסטר של כוכב הקבוצה המארחת ---
        try:
            # הבוט הולך לשחקני קבוצת הבית (Home)
            home_players = home.get('players', [])
            # מסנן רק את אלו שפותחים בחמישייה
            starters = [p for p in home_players if p.get('starter') == "1"]
            
            if starters:
                # לוקח את השחקן הראשון (בדרך כלל הכוכב/רכז)
                star_player = starters[0]
                p_id = star_player['personId']
                # שימוש בקישור לתמונת אקשן גדולה ומרשימה
                photo_url = f"https://www.nba.com/stats/api/v1/playerActionPhoto/{p_id}"
            else:
                photo_url = f"https://cdn.nba.com/logos/leagues/L/nba/matchups/{away['teamId']}-vs-{home['teamId']}.png"
        except:
            photo_url = f"https://cdn.nba.com/logos/leagues/L/nba/matchups/{away['teamId']}-vs-{home['teamId']}.png"

        # המשך בניית הודעת החמישיות...
        for team_key, name in [('away', a_name), ('home', h_name)]:
            msg += f"{rtl}📍 {b(name)}\n"
            msg += f"{rtl}🏀 {b('חמישייה:')} {', '.join(lineups[team_key]['starters']) if lineups[team_key]['starters'] else 'טרם פורסם'}\n"
            if lineups[team_key]['out']:
                msg += f"{rtl}❌ {b('חיסורים:')} {', '.join(lineups[team_key]['out'][:5])}\n"
            msg += "\n"
            
        return msg, photo_url

    # --- הודעות תוצאה (רבע/מחצית/סיום) ---
    msg = f"{rtl}⏱️ {b(label)}\n"
    msg += f"{rtl}🏀 {b(a_name)} 🆚 {b(h_name)} 🏀\n\n"

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
        mvp_name = translate_player_name(f"{mvp['firstName']} {mvp['familyName']}")
        msg += f"{rtl}⭐ {b('ה-MVP: ' + mvp_name)}\n"
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
    print("🚀 הבוט התחיל לעבוד...")
    while True:
        try:
            resp = requests.get(NBA_URL, timeout=10).json()
            games = resp.get('scoreboard', {}).get('games', [])
            for g in games:
                gid, status, period = g['gameId'], g['gameStatus'], g['period']
                txt = g.get('gameStatusText', '').lower()
                
                # תרגום שקט ברקע למניעת חסימות
                if status == 2:
                    t_away = g.get('awayTeam', {}).get('teamName', '')
                    t_home = g.get('homeTeam', {}).get('teamName', '')
                    if t_away not in cache["names"]: translate_player_name(t_away)
                    if t_home not in cache["names"]: translate_player_name(t_home)

                if gid not in cache["games"]: cache["games"][gid] = []
                
                # סיום רבע/מחצית/משחק
                if ("end" in txt or "half" in txt or status == 3) and txt not in cache["games"][gid]:
                    box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']
                    label = "סיום המשחק" if status == 3 else ("מחצית" if "half" in txt else f"סיום רבע {period}")
                    msg, photo = format_msg(box, label, is_final=(status == 3))
                    send_telegram(msg, photo)
                    cache["games"][gid].append(txt)
                    save_cache()

                # תחילת רבע (כולל רבע 1 עם חמישיות)
                if "start" in txt and f"start_{period}" not in cache["games"][gid]:
                    box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']
                    label = "המשחק יצא לדרך" if period == 1 else f"רבע {period} יצא לדרך"
                    msg, photo = format_msg(box, label)
                    send_telegram(msg, photo)
                    cache["games"][gid].append(f"start_{period}")
                    save_cache()

        except Exception as e: print(f"Error: {e}")
        time.sleep(10) # 10 שניות המתנה

if __name__ == "__main__":
    run()





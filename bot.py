import requests
import time
import json
import os
import logging
from datetime import datetime, timedelta, timezone
from deep_translator import GoogleTranslator

# --- הגדרות ותצורה ---
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
STATE_FILE = "nba_state.json"
ISRAELI_PLAYERS = ["Deni Avdija", "Ben Saraf", "Danny Wolf"]

# אובייקטים עזר
translator = GoogleTranslator(source='auto', target='iw')
name_cache = {}
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

TEAM_NAMES_HEB = {
    "Celtics": "בוסטון סלטיקס", "Bucks": "מילווקי באקס", "Hawks": "אטלנטה הוקס",
    "Cavaliers": "קליבלנד קאבלירס", "Magic": "אורלנדו מג'יק", "76ers": "פילדלפיה 76'",
    "Nets": "ברוקלין נטס", "Knicks": "ניו יורק ניקס", "Heat": "מיאמי היט",
    "Hornets": "שארלוט הורנטס", "Bulls": "שיקגו בולס", "Pacers": "אינדיאנה פייסרס",
    "Pistons": "דטרויט פיסטונס", "Raptors": "טורונטו ראפטורס", "Wizards": "וושינגטון וויזארדס",
    "Nuggets": "דנבר נאגטס", "Timberwolves": "מינסוטה טימברוולבס", "Thunder": "אוקלהומה סיטי תאנדר",
    "Trail Blazers": "פורטלנד טרייל בלייזרס", "Jazz": "יוטה ג'אז", "Warriors": "גולדן סטייט ווריורס",
    "Clippers": "ל.א קליפרס", "Lakers": "ל.א לייקרס", "Suns": "פיניקס סאנס",
    "Kings": "סקרמנטו קינגס", "Mavericks": "דאלאס מאבריקס", "Rockets": "יוסטון רוקטס",
    "Grizzlies": "ממפיס גריזליס", "Pelicans": "ניו אורלינס פליקנס", "Spurs": "סן אנטוניו ספרס"
}

# --- ניהול מצב (State) ---
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {"games": {}, "dates": {"schedule": "", "summary": ""}}
    return {"games": {}, "dates": {"schedule": "", "summary": ""}}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4, ensure_ascii=False)

# --- תרגום ועיבוד ---
def translate_player(name):
    if name in name_cache: return name_cache[name]
    try:
        res = translator.translate(name)
        name_cache[name] = res
        return res
    except: return name

def format_minutes(mins_raw):
    minutes = mins_raw.replace("PT", "").replace("M", ":").replace("S", "").split('.')[0]
    if ":" in minutes:
        parts = minutes.split(":")
        if len(parts[1]) == 1: parts[1] = "0" + parts[1]
        return f"{parts[0]}:{parts[1]}"
    return minutes

def send_msg(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})
    except Exception as e:
        logging.error(f"Telegram error: {e}")

# --- פונקציות סטטיסטיקה ---
def calculate_efficiency(p):
    s = p["statistics"]
    try:
        eff = (s['points'] + s['reboundsTotal'] + s['assists'] + s['steals'] + s['blocks']) - \
              ((s['fieldGoalsAttempted'] - s['fieldGoalsMade']) + (s['freeThrowsAttempted'] - s['freeThrowsMade']) + s['turnovers'])
        return eff
    except: return 0

def get_stat_line(p, extended=False):
    s = p['statistics']
    name = f"**{translate_player(p['firstName'] + ' ' + p['familyName'])}**"
    line = f"▫️ {name}: {s['points']} נק', {s['reboundsTotal']} ריב', {s['assists']} אס'"
    if extended:
        extras = []
        if s.get('steals', 0) > 0: extras.append(f"{s['steals']} חט'")
        if s.get('blocks', 0) > 0: extras.append(f"{s['blocks']} חס'")
        if s.get('turnovers', 0) > 0: extras.append(f"{s['turnovers']} איבודי כדור")
        if extras: line += f" ({', '.join(extras)})"
    return line

# --- פורמטים של הודעות ---

def format_start_game(data):
    away_h = TEAM_NAMES_HEB.get(data['awayTeam']['teamName'], data['awayTeam']['teamName'])
    home_h = TEAM_NAMES_HEB.get(data['homeTeam']['teamName'], data['homeTeam']['teamName'])
    msg = f"🏀 *המשחק יצא לדרך!* 🔥\n🏟️ {away_h} 🆚 {home_h}\n\n"
    for team_key in ['awayTeam', 'homeTeam']:
        team = data[team_key]
        t_heb = TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])
        starters = [f"**{translate_player(p['firstName'] + ' ' + p['familyName'])}**" for p in team['players'] if p['starter'] == "1"]
        inactive = [translate_player(p['firstName'] + ' ' + p['familyName']) for p in team['players'] if p.get('status') == 'INACTIVE']
        
        msg += f"📍 *{t_heb}*:\n• 🏀 חמישייה: {', '.join(starters)}\n"
        msg += f"• ❌ חיסורים: {', '.join(inactive) if inactive else 'אין חיסורים ידועים'}\n\n"
    return msg

def format_period_update(game_data, label):
    away, home = game_data['awayTeam'], game_data['homeTeam']
    away_h, home_h = TEAM_NAMES_HEB.get(away['teamName'], away['teamName']), TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])
    
    msg = f"📊 *{label}: {away_h} 🆚 {home_h}* 🏀\n"
    msg += f"📈 תוצאה: {away['score']} - {home['score']}\n\n"

    for team in [away, home]:
        t_heb = TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])
        # מיון שחקנים לפי נקודות
        starters = sorted([p for p in team['players'] if p['starter'] == "1"], key=lambda x: x['statistics']['points'], reverse=True)
        bench = sorted([p for p in team['players'] if p['starter'] == "0" and p['statistics']['minutesCalculated'] != "PT00M00.00S"], key=lambda x: x['statistics']['points'], reverse=True)
        
        msg += f"🔥 *{t_heb}*:\n"
        if len(starters) >= 1: msg += f"• {get_stat_line(starters[0])}\n"
        if len(starters) >= 2: msg += f"• {get_stat_line(starters[1])}\n"
        if bench: msg += f"• ⚡ מהספסל: {get_stat_line(bench[0])}\n"
        msg += "\n"
    return msg

def format_israeli_stats(p, label):
    s = p['statistics']
    name = translate_player(f"{p['firstName']} {p['familyName']}")
    if s['minutesCalculated'] == "PT00M00.00S":
        return f"🇮🇱 **עדכון ישראלים - {name}**\n📍 סטטוס: {label}\n😴 השחקן טרם עלה לפרקט."

    msg = (f"🇮🇱 **עדכון ישראלים - {name}** 🇮🇱\n"
           f"━━━━━━━━━━━━━━\n"
           f"🏀 **סטטיסטיקה מורחבת ({label}):**\n"
           f"⏱️ **דקות:** {format_minutes(s['minutesCalculated'])}\n"
           f"🎯 **נקודות:** {s['points']}\n"
           f"💪 **ריבאונדים:** {s['reboundsTotal']}\n"
           f"🪄 **אסיסטים:** {s['assists']}\n"
           f"🧤 **חטיפות:** {s['steals']}\n"
           f"🚫 **חסימות:** {s['blocks']}\n"
           f"⚠️ **איבודים:** {s['turnovers']}\n"
           f"📊 **מדד +/-:** {s['plusMinusPoints']}\n"
           f"━━━━━━━━━━━━━━")
    return msg

def format_final_summary(data, ot_count):
    away, home = data['awayTeam'], data['homeTeam']
    away_h, home_h = TEAM_NAMES_HEB.get(away['teamName'], away['teamName']), TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])
    ot_txt = f" (לאחר {ot_count} הארכות)" if ot_count > 0 else ""
    
    # MVP
    all_p = away['players'] + home['players']
    mvp = max(all_p, key=calculate_efficiency)

    msg = f"🏁🏀 **סיום המשחק: {away_h} 🆚 {home_h}** 🏁🏀\n\n"
    msg += f"🏆 **תוצאה סופית: {away['score']} - {home['score']}{ot_txt}**\n\n"
    msg += f"⭐ **MVP המשחק:** {translate_player(mvp['firstName'] + ' ' + mvp['familyName'])}\n"
    msg += f"📈 מדד יעילות (EFF): {calculate_efficiency(mvp)}\n"
    msg += "──────────────────\n\n"
    
    for team in [away, home]:
        msg += f"📍 **{TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])}**:\n"
        top_players = sorted(team['players'], key=lambda x: x['statistics']['points'], reverse=True)[:4]
        for p in top_players: msg += f"{get_stat_line(p, True)}\n"
        msg += "\n"
    return msg

# --- לו"ז וסיכום בוקר ---

def get_daily_schedule():
    try:
        data = requests.get("https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json").json()
        games = data['scoreboard']['games']
        if not games: return "🏀 אין משחקים מתוכננים להיום."
        msg = "🗓️ **לוח המשחקים להיום ובלילה:**\n\n"
        for g in games:
            away = TEAM_NAMES_HEB.get(g['awayTeam']['teamName'], g['awayTeam']['teamName'])
            home = TEAM_NAMES_HEB.get(g['homeTeam']['teamName'], g['homeTeam']['teamName'])
            dt = datetime.strptime(g['gameEt'], "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=2)
            msg += f"⏰ {dt.strftime('%H:%M')} | {away} 🆚 {home}\n"
        return msg + "\n*צפייה מהנה!* 🏀"
    except: return "⚠️ שגיאה במשיכת לוח המשחקים."

def get_morning_summary():
    try:
        data = requests.get("https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json").json()
        games = data['scoreboard']['games']
        if not games: return "☕ בוקר טוב! לא היו משחקים הלילה."
        msg = "☕ **בוקר טוב! סיכום תוצאות הלילה:**\n\n"
        for g in games:
            a_name = TEAM_NAMES_HEB.get(g['awayTeam']['teamName'], g['awayTeam']['teamTricode'])
            h_name = TEAM_NAMES_HEB.get(g['homeTeam']['teamName'], g['homeTeam']['teamTricode'])
            msg += f"• {a_name} {g['awayTeam']['score']} 🆚 {g['homeTeam']['score']} {h_name}\n"
        return msg + "\n**המשך יום כדורסל נהדר!** ✨"
    except: return None

# --- לוגיקה ראשית ---
def monitor_nba():
    state = load_state()
    while True:
        try:
            now = datetime.now(timezone.utc) + timedelta(hours=2)
            today = now.strftime("%Y-%m-%d")

            # הודעות מתוזמנות
            if now.hour == 9 and now.minute == 0 and state["dates"]["summary"] != today:
                summary = get_morning_summary()
                if summary: send_msg(summary)
                state["dates"]["summary"] = today
            
            if now.hour == 18 and now.minute == 0 and state["dates"]["schedule"] != today:
                send_msg(get_daily_schedule())
                state["dates"]["schedule"] = today

            # משחקים חיים
            resp = requests.get("https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json", timeout=10).json()
            for g in resp.get('scoreboard', {}).get('games', []):
                gid = g['gameId']
                if g['gameStatus'] > 1:
                    if gid not in state["games"]: state["games"][gid] = {"started": False, "periods": [], "final": False}
                    s = state["games"][gid]
                    box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']

                    if not s["started"] and g['gameStatus'] == 2:
                        send_msg(format_start_game(box))
                        s["started"] = True
                    
                    period_label = f"p_{g['period']}_{g['gameStatusText'].strip()}"
                    if ("End" in g['gameStatusText'] or "Half" in g['gameStatusText']) and period_label not in s["periods"]:
                        label = "מחצית" if "Half" in g['gameStatusText'] else f"סיום רבע {g['period']}"
                        send_msg(format_period_update(box, label))
                        
                        # עדכון ישראלים מורחב
                        for team in ['awayTeam', 'homeTeam']:
                            for p in box[team]['players']:
                                full_name = f"{p['firstName']} {p['familyName']}"
                                if full_name in ISRAELI_PLAYERS:
                                    send_msg(format_israeli_stats(p, label))
                        
                        s["periods"].append(period_label)

                    if g['gameStatus'] == 3 and not s["final"]:
                        ot = g['period'] - 4 if g['period'] > 4 else 0
                        send_msg(format_final_summary(box, ot))
                        for team in ['awayTeam', 'homeTeam']:
                            for p in box[team]['players']:
                                if f"{p['firstName']} {p['familyName']}" in ISRAELI_PLAYERS:
                                    send_msg(format_israeli_stats(p, "סיום משחק"))
                        s["final"] = True

            save_state(state)
        except Exception as e: logging.error(f"Error: {e}")
        time.sleep(30)

if __name__ == "__main__":
    monitor_nba()

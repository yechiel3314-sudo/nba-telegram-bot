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
STATE_FILE = "nba_ultra_safe_v5.json"
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

# --- ניהול מצב (State) והגנה משגיאות ---
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading state: {e}")
    return {"games": {}, "dates": {"schedule": "", "summary": ""}}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Error saving state: {e}")

# --- פונקציות עיבוד ותרגום ---
def translate_player(name):
    if name in name_cache: return name_cache[name]
    try:
        res = translator.translate(name)
        name_cache[name] = res
        return res
    except: return name

def format_minutes(mins_raw):
    if not mins_raw or "PT00M00.00S" in mins_raw: return "0:00"
    minutes = mins_raw.replace("PT", "").replace("M", ":").replace("S", "").split('.')[0]
    if ":" in minutes:
        parts = minutes.split(":")
        if len(parts[1]) == 1: parts[1] = "0" + parts[1]
        return f"{parts[0]}:{parts[1]}"
    return minutes

def send_msg(text):
    if not text: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    for i in range(3):
        try:
            res = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=15)
            if res.status_code == 200: return
        except Exception as e:
            logging.error(f"Telegram retry {i+1}: {e}")
            time.sleep(2)

# --- לוגיקת סטטיסטיקה ---
def calculate_efficiency(p):
    s = p.get("statistics", {})
    try:
        return (s.get('points',0) + s.get('reboundsTotal',0) + s.get('assists',0) + s.get('steals',0) + s.get('blocks',0)) - \
               ((s.get('fieldGoalsAttempted',0) - s.get('fieldGoalsMade',0)) + (s.get('freeThrowsAttempted',0) - s.get('freeThrowsMade',0)) + s.get('turnovers',0))
    except: return 0

def get_stat_line(p, extended=False):
    s = p.get('statistics', {})
    name = f"**{translate_player(p['firstName'] + ' ' + p['familyName'])}**"
    line = f"▫️ {name}: {s.get('points',0)} נק', {s.get('reboundsTotal',0)} ריב', {s.get('assists',0)} אס'"
    if extended:
        extras = []
        if s.get('steals', 0) > 0: extras.append(f"{s['steals']} חט'")
        if s.get('blocks', 0) > 0: extras.append(f"{s['blocks']} חס'")
        if extras: line += f" ({', '.join(extras)})"
    return line

# --- בוני הודעות ---

def format_start_game(data):
    away, home = data['awayTeam'], data['homeTeam']
    away_h, home_h = TEAM_NAMES_HEB.get(away['teamName'], away['teamName']), TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])
    msg = f"🏀 *המשחק יצא לדרך!* 🔥\n🏟️ {away_h} 🆚 {home_h}\n\n"
    for team in [away, home]:
        t_heb = TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])
        starters = [f"**{translate_player(p['firstName'] + ' ' + p['familyName'])}**" for p in team['players'] if p.get('starter') == "1"]
        inactive = [translate_player(p['firstName'] + ' ' + p['familyName']) for p in team['players'] if p.get('status') == 'INACTIVE']
        msg += f"📍 *{t_heb}*:\n• 🏀 חמישייה: {', '.join(starters)}\n• ❌ חיסורים: {', '.join(inactive) if inactive else 'אין חיסורים דווחו'}\n\n"
    return msg

def format_period_update(game_data, label):
    away, home = game_data['awayTeam'], game_data['homeTeam']
    away_h, home_h = TEAM_NAMES_HEB.get(away['teamName'], away['teamName']), TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])
    
    if away['score'] > home['score']:
        score_info = f"{away['score']} - {home['score']} ל{away_h}"
    elif home['score'] > away['score']:
        score_info = f"{away['score']} - {home['score']} ל{home_h}"
    else:
        score_info = f"{away['score']} - {home['score']} (שוויון)"

    msg = f"📊 {label}: {away_h} 🆚 {home_h} 🏀\n"
    msg += f"📈 תוצאה: {score_info}\n\n"

    for team in [away, home]:
        t_heb = TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])
        p_list = team.get('players', [])
        starters = sorted([p for p in p_list if p.get('starter') == "1"], key=lambda x: x['statistics']['points'], reverse=True)
        bench = sorted([p for p in p_list if p.get('starter') == "0" and p['statistics']['minutesCalculated'] != "PT00M00.00S"], key=lambda x: x['statistics']['points'], reverse=True)
        
        msg += f"🔥 *{t_heb}*:\n"
        if len(starters) >= 1: msg += f"🥇 קלע 1: {get_stat_line(starters[0])}\n"
        if len(starters) >= 2: msg += f"🥈 קלע 2: {get_stat_line(starters[1])}\n"
        if bench:
            s_b = bench[0]['statistics']
            msg += f"⚡ מהספסל: **{translate_player(bench[0]['firstName']+' '+bench[0]['familyName'])}**: {s_b['points']} נק', {s_b['reboundsTotal']} ריב', {s_b['assists']} אס'\n"
        msg += "\n"
    return msg

def format_israeli_stats(p, label):
    s = p.get('statistics', {})
    if s.get('minutesCalculated') == "PT00M00.00S": return None
    name = translate_player(f"{p['firstName']} {p['familyName']}")
    msg = (f"🇮🇱 **גאווה ישראלית: {name}** 🇮🇱\n━━━━━━━━━━━━━━\n"
           f"🏀 **סטטיסטיקה מלאה ({label}):**\n\n"
           f"⏱️ **דקות:** {format_minutes(s['minutesCalculated'])}\n"
           f"🎯 **נקודות:** {s['points']}\n"
           f"💪 **ריבאונדים:** {s['reboundsTotal']}\n"
           f"🪄 **אסיסטים:** {s['assists']}\n"
           f"🧤 **חטיפות:** {s['steals']}\n"
           f"🚫 **חסימות:** {s['blocks']}\n"
           f"📊 **מדד פלוס/מינוס:** {s['plusMinusPoints']}\n"
           f"━━━━━━━━━━━━━━")
    return msg

def format_final_summary(data, ot_count):
    away, home = data['awayTeam'], data['homeTeam']
    away_h, home_h = TEAM_NAMES_HEB.get(away['teamName'], away['teamName']), TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])
    ot_txt = f" (לאחר {ot_count} הארכות)" if ot_count > 0 else ""
    winner = away_h if away['score'] > home['score'] else home_h
    
    all_p = away['players'] + home['players']
    mvp = max(all_p, key=calculate_efficiency)

    msg = f"🏁🏀 **סיום המשחק: {away_h} 🆚 {home_h}** 🏁🏀\n\n"
    msg += f"🏆 **תוצאה סופית: {away['score']} - {home['score']} ל{winner}{ot_txt}**\n\n"
    msg += f"⭐ **MVP המשחק:** {translate_player(mvp['firstName'] + ' ' + mvp['familyName'])}\n"
    msg += "──────────────────\n\n"
    
    for team in [away, home]:
        msg += f"📍 **{TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])}**:\n🏀 *חמישייה פותחת:*\n"
        for p in [p for p in team['players'] if p.get('starter') == "1"]:
            msg += f"{get_stat_line(p, True)}\n"
        msg += "\n⚡ *בולטים מהספסל:*\n"
        bench = sorted([p for p in team['players'] if p.get('starter') == "0" and p['statistics']['minutesCalculated'] != "PT00M00.00S"], key=lambda x: x['statistics']['points'], reverse=True)[:3]
        for p in bench:
            msg += f"{get_stat_line(p, True)}\n"
        msg += "\n"
    return msg

# --- לוגיקת ניטור ולו"ז ---

def monitor_nba():
    state = load_state()
    logging.info("NBA Monitor is live and protecting...")
    
    while True:
        try:
            now = datetime.now(timezone.utc) + timedelta(hours=2)
            today = now.strftime("%Y-%m-%d")

            # קבלת ה-Scoreboard הראשי
            try:
                sb_url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
                resp = requests.get(sb_url, timeout=15).json()
                games = resp.get('scoreboard', {}).get('games', [])
            except Exception as api_err:
                logging.error(f"Scoreboard API Error: {api_err}")
                time.sleep(60); continue

            # 1. שליחת לו"ז (18:00)
            if now.hour == 18 and now.minute == 0 and state["dates"]["schedule"] != today:
                if games:
                    sched_msg = "🗓️ **לוח המשחקים להיום ובלילה:**\n\n"
                    for g in games:
                        a = TEAM_NAMES_HEB.get(g['awayTeam']['teamName'], g['awayTeam']['teamName'])
                        h = TEAM_NAMES_HEB.get(g['homeTeam']['teamName'], g['homeTeam']['teamName'])
                        dt = datetime.strptime(g['gameEt'], "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=2)
                        sched_msg += f"⏰ {dt.strftime('%H:%M')} | {a} 🆚 {h}\n"
                    send_msg(sched_msg + "\n*צפייה מהנה!* 🏀")
                state["dates"]["schedule"] = today; save_state(state)

            # 2. סיכום בוקר מתורגם (09:00)
            if now.hour == 9 and now.minute == 0 and state["dates"]["summary"] != today:
                if games:
                    sum_msg = "☕ **בוקר טוב! סיכום תוצאות משחקי הלילה:**\n\n"
                    for g in games:
                        a = TEAM_NAMES_HEB.get(g['awayTeam']['teamName'], g['awayTeam']['teamName'])
                        h = TEAM_NAMES_HEB.get(g['homeTeam']['teamName'], g['homeTeam']['teamName'])
                        winner = a if g['awayTeam']['score'] > g['homeTeam']['score'] else h
                        sum_msg += f"• {a} **{g['awayTeam']['score']}** 🆚 **{g['homeTeam']['score']}** {h} (ל{winner})\n"
                    send_msg(sum_msg + "\n**המשך יום נהדר!** ✨")
                state["dates"]["summary"] = today; save_state(state)

            # 3. ניטור משחקים חיים
            for g in games:
                gid = g['gameId']
                status = g['gameStatus']
                status_text = g['gameStatusText'].strip()

                if status > 1: # התחיל או נגמר
                    if gid not in state["games"]:
                        state["games"][gid] = {"started": False, "periods": [], "final": False}
                    gs = state["games"][gid]

                    try:
                        box_url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
                        box_data = requests.get(box_url, timeout=15).json()['game']
                    except: continue

                    # הודעת פתיחה
                    if not gs["started"] and status == 2:
                        send_msg(format_start_game(box_data))
                        gs["started"] = True; save_state(state)

                    # הודעת רבע/מחצית
                    p_key = f"p_{g['period']}_{status_text}"
                    if ("End" in status_text or "Half" in status_text) and p_key not in gs["periods"]:
                        label = "מחצית" if "Half" in status_text else f"סיום רבע {g['period']}"
                        send_msg(format_period_update(box_data, label))
                        
                        # בדיקת ישראלים
                        for team_key in ['awayTeam', 'homeTeam']:
                            for p in box_data[team_key]['players']:
                                if f"{p['firstName']} {p['familyName']}" in ISRAELI_PLAYERS:
                                    isr_msg = format_israeli_stats(p, label)
                                    if isr_msg: send_msg(isr_msg)
                        
                        gs["periods"].append(p_key); save_state(state)

                    # הודעת סיום משחק
                    if status == 3 and not gs["final"]:
                        ot = g['period'] - 4 if g['period'] > 4 else 0
                        send_msg(format_final_summary(box_data, ot))
                        
                        # סטטיסטיקה סופית לישראלים
                        for team_key in ['awayTeam', 'homeTeam']:
                            for p in box_data[team_key]['players']:
                                if f"{p['firstName']} {p['familyName']}" in ISRAELI_PLAYERS:
                                    isr_msg = format_israeli_stats(p, "סיום משחק")
                                    if isr_msg: send_msg(isr_msg)
                                    
                        gs["final"] = True; save_state(state)

        except Exception as e:
            logging.error(f"Global Error: {e}")
        
        time.sleep(30)

if __name__ == "__main__":
    monitor_nba()

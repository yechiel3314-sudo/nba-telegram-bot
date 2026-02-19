import requests
import time
import json
import os
import logging
from datetime import datetime, timedelta, timezone
from deep_translator import GoogleTranslator

# ==========================================
# הגדרות מערכת ותצורה
# ==========================================
TOKEN = "8514837332:AAFZmyXXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
STATE_FILE = "nba_master_v11.json"
ISRAELI_PLAYERS = ["Deni Avdija", "Ben Saraf", "Danny Wolf"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
translator = GoogleTranslator(source='auto', target='iw')
name_cache = {}

TEAM_NAMES_HEB = {
    "Celtics": "בוסטון סלטיקס", "Bucks": "מילווקי באקס", "Hawks": "אטלנטה הוקס",
    "Cavaliers": "קליבלנד קאבלירס", "Magic": "אורלנדו מג'יק", "76ers": "פילדלפיה 76'",
    "Nets": "ברוקלין נטס", "Knicks": "ניו יורק ניקס", "Heat": "מיאמי היט",
    "Hornets": "שארלוט הורנטס", "Bulls": "שיקגו בולס", "Pacers": "אינדיאנה פייסרס",
    "Pistons": "דטרויט פיסטונס", "Raptors": "טורונטו ראפפורס", "Wizards": "וושינגטון וויזארדס",
    "Nuggets": "דנבר נאגטס", "Timberwolves": "מינסוטה טימברוולבס", "Thunder": "אוקלהומה סיטי תאנדר",
    "Trail Blazers": "פורטלנד טרייל בלייזרס", "Jazz": "יוטה ג'אז", "Warriors": "גולדן סטייט ווריורס",
    "Clippers": "ל.א קליפרס", "Lakers": "ל.א לייקרס", "Suns": "פיניקס סאנס",
    "Kings": "סקרמנטו קינגס", "Mavericks": "דאלאס מאבריקס", "Rockets": "יוסטון רוקטס",
    "Grizzlies": "ממפיס גריזליס", "Pelicans": "ניו אורלינס פליקנס", "Spurs": "סן אנטוניו ספרס"
}

# ==========================================
# פונקציות עזר
# ==========================================

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {"games": {}, "dates": {"schedule": "", "summary": ""}}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4, ensure_ascii=False)

def translate(name):
    if name in name_cache: return name_cache[name]
    try:
        res = translator.translate(name)
        name_cache[name] = res
        return res
    except: return name

def send_msg(text):
    if not text: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def get_stat_line(p, ext=False):
    s = p.get('statistics', {})
    name = f"**{translate(p['firstName'] + ' ' + p['familyName'])}**"
    line = f"▫️ {name}: {s.get('points', 0)} נק', {s.get('reboundsTotal', 0)} ריב', {s.get('assists', 0)} אס'"
    extras = []
    if s.get('steals', 0) > 0: extras.append(f"{s['steals']} חט'")
    if s.get('blocks', 0) > 0: extras.append(f"{s['blocks']} חס'")
    if extras: line += f" ({', '.join(extras)})"
    return line

# ==========================================
# בוני הודעות
# ==========================================

def format_start_game(box):
    away, home = box['awayTeam'], box['homeTeam']
    msg = f"🔥 **המשחק יצא לדרך!** 🔥\n🏀 **{TEAM_NAMES_HEB.get(away['teamName'], away['teamName'])} 🆚 {TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])}**\n\n"
    
    for team in [away, home]:
        t_name = TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])
        starters = [translate(p['firstName'] + " " + p['familyName']) for p in team['players'] if p.get('starter') == "1"]
        msg += f"🏙️ **{t_name}:**\n📍 **חמישייה:** {', '.join(starters)}\n❌ **חיסורים:** (לפי הדיווח האחרון)\n\n"
    
    return msg + "צפייה מהנה! 📺"

def format_period_update(box, label):
    away, home = box['awayTeam'], box['homeTeam']
    a_heb = TEAM_NAMES_HEB.get(away['teamName'], away['teamName'])
    h_heb = TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])
    
    score = f"{home['score']} - **{away['score']} {a_heb}**" if away['score'] > home['score'] else f"{away['score']} - **{home['score']} {h_heb}**"
    msg = f"🔥 **{label}: {a_heb} 🆚 {h_heb}** 🔥\n📈 תוצאה: {score}\n\n"

    for team in [away, home]:
        msg += f"📍 **{TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])}**:\n"
        players = sorted(team['players'], key=lambda x: x['statistics']['points'], reverse=True)
        starters = [p for p in players if p.get('starter') == "1"][:2]
        bench = [p for p in players if p.get('starter') == "0"][:1]
        for p in starters: msg += f"🥇 {get_stat_line(p)}\n"
        for p in bench: msg += f"⚡ **מהספסל:** {get_stat_line(p)}\n"
        msg += "\n"
    return msg

def format_final_summary(box, ot):
    away, home = box['awayTeam'], box['homeTeam']
    a_heb = TEAM_NAMES_HEB.get(away['teamName'], away['teamName'])
    h_heb = TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])
    score = f"{home['score']} - **{away['score']} {a_heb}**" if away['score'] > home['score'] else f"{away['score']} - **{home['score']} {h_heb}**"
    
    all_p = away['players'] + home['players']
    mvp = max(all_p, key=lambda x: x['statistics']['points'])
    
    msg = f"🏁🏀 **סיום המשחק: {a_heb} 🆚 {h_heb}** 🏁🏀\n🏆 **תוצאה סופית: {score}**\n⭐ **MVP:** {translate(mvp['firstName'] + ' ' + mvp['familyName'])}\n──────────────────\n"
    
    for team in [away, home]:
        msg += f"📍 **{TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])}**:\n🏀 *חמישייה פותחת:*\n"
        starters = sorted([p for p in team['players'] if p.get('starter') == "1"], key=lambda x: x['statistics']['points'], reverse=True)
        bench = sorted([p for p in team['players'] if p.get('starter') == "0"], key=lambda x: x['statistics']['points'], reverse=True)[:3]
        for p in starters: msg += f"{get_stat_line(p)}\n"
        msg += "⚡ *3 בולטים מהספסל:*\n"
        for p in bench: msg += f"{get_stat_line(p)}\n"
        msg += "\n"
    return msg

# ==========================================
# לולאה ראשית
# ==========================================

def run_bot():
    state = load_state()
    while True:
        try:
            now = datetime.now(timezone.utc) + timedelta(hours=2)
            today = now.strftime("%Y-%m-%d")
            
            sb = requests.get("https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json", timeout=15).json()
            games = sb.get('scoreboard', {}).get('games', [])

            # לו"ז 19:30
            if now.hour == 19 and now.minute == 30 and state["dates"]["schedule"] != today:
                msg = "🗓️ **לוח המשחקים המלא להיום ובלילה:**\n\n"
                for g in games:
                    a = TEAM_NAMES_HEB.get(g['awayTeam']['teamName'], g['awayTeam']['teamName'])
                    h = TEAM_NAMES_HEB.get(g['homeTeam']['teamName'], g['homeTeam']['teamName'])
                    msg += f"⏰ {g['gameStatusText'].split(' ')[0]} | {a} 🆚 {h}\n"
                send_msg(msg + "\n*צפייה מהנה!* 🏀")
                state["dates"]["schedule"] = today
                save_state(state)

            # סיכום בוקר 09:00
            if now.hour == 9 and now.minute == 0 and state["dates"]["summary"] != today:
                msg = "☕ **בוקר טוב! סיכום תוצאות הלילה ב-NBA:**\n━━━━━━━━━━━━━━━━━━━━\n\n"
                for g in games:
                    a, h = TEAM_NAMES_HEB.get(g['awayTeam']['teamName'], g['awayTeam']['teamName']), TEAM_NAMES_HEB.get(g['homeTeam']['teamName'], g['homeTeam']['teamName'])
                    ascore, hscore = g['awayTeam']['score'], g['homeTeam']['score']
                    msg += f"🏀 {h} {hscore} - **{ascore} {a}**\n" if ascore > hscore else f"🏀 {a} {ascore} - **{hscore} {h}**\n"
                send_msg(msg + "\n━━━━━━━━━━━━━━━━━━━━\n**המשך יום נפלא!** ✨")
                state["dates"]["summary"] = today
                save_state(state)

            # ניטור משחקים
            for g in games:
                gid = g['gameId']
                if g['gameStatus'] > 1:
                    if gid not in state["games"]: state["games"][gid] = {"p": [], "f": False, "s": False}
                    gs = state["games"][gid]
                    box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']
                    
                    # הודעת פתיחה
                    if g['gameStatus'] == 2 and not gs.get("s"):
                        send_msg(format_start_game(box))
                        gs["s"] = True
                    
                    # רבעים
                    txt = g['gameStatusText'].strip()
                    if ("End" in txt or "Half" in txt) and txt not in gs["p"]:
                        send_msg(format_period_update(box, "סיום רבע" if "End" in txt else "מחצית"))
                        gs["p"].append(txt)
                    
                    # סיום
                    if g['gameStatus'] == 3 and not gs["f"]:
                        send_msg(format_final_summary(box, 0))
                        gs["f"] = True
                    save_state(state)

        except Exception as e: logging.error(e)
        time.sleep(30)

if __name__ == "__main__": run_bot()

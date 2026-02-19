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
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
STATE_FILE = "nba_ultimate_bot.json"
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
# פונקציות תשתית
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

def format_minutes(mins_raw):
    if not mins_raw or "PT" not in mins_raw: return "0:00"
    try:
        time_str = mins_raw.replace("PT", "").replace("M", ":").replace("S", "")
        if "." in time_str: time_str = time_str.split(".")[0]
        parts = time_str.split(":")
        return f"{parts[0]}:{parts[1].zfill(2)}" if len(parts) == 2 else time_str
    except: return "0:00"

def send_msg(text):
    if not text: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=15)
    except: pass

# ==========================================
# עיצוב הודעת ישראלי (הבקשה הספציפית שלך)
# ==========================================

def format_israeli_card(p, label):
    s = p.get('statistics', {})
    full_name = f"{p['firstName']} {p['familyName']}"
    name_heb = translate(full_name)
    
    fg = f"{s.get('fieldGoalsMade', 0)}/{s.get('fieldGoalsAttempted', 0)}"
    tp = f"{s.get('threePointersMade', 0)}/{s.get('threePointersAttempted', 0)}"
    ft = f"{s.get('freeThrowsMade', 0)}/{s.get('freeThrowsAttempted', 0)}"

    msg = (f"🇮🇱 **גאווה ישראלית: {name_heb}** 🇮🇱\n"
           f"━━━━━━━━━━━━━━\n"
           f"🏀 **סטטיסטיקה ({label}):**\n\n"
           f"🎯 **נקודות:** {s.get('points', 0)}\n"
           f"🏀 **מהשדה:** {fg} | **לשלוש:** {tp} | **עונשין:** {ft}\n"
           f"💪 **ריבאונדים:** {s.get('reboundsTotal', 0)}\n"
           f"🪄 **אסיסטים:** {s.get('assists', 0)}\n"
           f"🧤 **חטיפות:** {s.get('steals', 0)}\n"
           f"🚫 **חסימות:** {s.get('blocks', 0)}\n"
           f"⚠️ **איבודים:** {s.get('turnovers', 0)}\n"
           f"📊 **מדד פלוס/מינוס:** {s.get('plusMinusPoints', 0)}\n"
           f"⏱️ **דקות:** {format_minutes(s.get('minutesCalculated', ''))}\n"
           f"━━━━━━━━━━━━━━")
    return msg

# ==========================================
# בוני הודעות משחק
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
        for p in [p for p in players if p.get('starter') == "1"][:2]:
            msg += f"🥇 **{translate(p['firstName']+' '+p['familyName'])}**: {p['statistics']['points']} נק'\n"
        msg += "\n"
    return msg

# ==========================================
# לולאה ראשית
# ==========================================

def run_bot():
    state = load_state()
    logging.info("הבוט עלה לאוויר עם עדכוני ישראלים נפרדים...")
    while True:
        try:
            sb = requests.get("https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json", timeout=15).json()
            games = sb.get('scoreboard', {}).get('games', [])

            for g in games:
                gid = g['gameId']
                if g['gameStatus'] > 1:
                    if gid not in state["games"]: state["games"][gid] = {"p": [], "s": False}
                    gs = state["games"][gid]
                    box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']
                    
                    # הודעת פתיחה
                    if g['gameStatus'] == 2 and not gs["s"]:
                        send_msg(format_start_game(box))
                        gs["s"] = True

                    # עדכוני רבעים + הודעות ישראלים נפרדות
                    txt = g['gameStatusText'].strip()
                    if ("End" in txt or "Half" in txt) and txt not in gs["p"]:
                        label = "מחצית" if "Half" in txt else f"סיום רבע {g['period']}"
                        
                        # 1. שלח הודעת רבע כללית
                        send_msg(format_period_update(box, label))
                        
                        # 2. שלח הודעה נפרדת לכל ישראלי ששיחק
                        for side in ['awayTeam', 'homeTeam']:
                            for p in box[side]['players']:
                                if f"{p['firstName']} {p['familyName']}" in ISRAELI_PLAYERS:
                                    if p['statistics']['minutesCalculated'] != "PT00M00.00S":
                                        send_msg(format_israeli_card(p, label))
                        
                        gs["p"].append(txt)
                        save_state(state)

        except Exception as e: logging.error(f"שגיאה: {e}")
        time.sleep(30)

if __name__ == "__main__":
    run_bot()

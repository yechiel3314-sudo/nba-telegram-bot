import requests
import time
import json
import os
import logging
from datetime import datetime, timedelta, timezone
from deep_translator import GoogleTranslator

# ==========================================
# הגדרות מערכת - וודא שהפרטים נכונים
# ==========================================
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
STATE_FILE = "nba_ultimate_master.json"
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

def get_stat_line(p):
    s = p.get('statistics', {})
    name = f"**{translate(p['firstName'] + ' ' + p['familyName'])}**"
    return f"▫️ {name}: {s.get('points', 0)} נק', {s.get('reboundsTotal', 0)} ריב', {s.get('assists', 0)} אס'"

# ==========================================
# בוני הודעות מעוצבות
# ==========================================

def format_israeli_card(p, label, is_mvp=False):
    s = p.get('statistics', {})
    name = translate(f"{p['firstName']} {p['familyName']}")
    mvp_tag = "\n⭐ **MVP של המשחק!** ⭐" if is_mvp else ""
    
    msg = (f"🇮🇱 **גאווה ישראלית: {name}** 🇮🇱{mvp_tag}\n"
           f"━━━━━━━━━━━━━━\n"
           f"🏀 **סטטיסטיקה ({label}):**\n\n"
           f"🎯 **נקודות:** {s.get('points', 0)}\n"
           f"🏀 **מהשדה:** {s.get('fieldGoalsMade',0)}/{s.get('fieldGoalsAttempted',0)}\n"
           f"🏹 **לשלוש:** {s.get('threePointersMade',0)}/{s.get('threePointersAttempted',0)}\n"
           f"✨ **עונשין:** {s.get('freeThrowsMade',0)}/{s.get('freeThrowsAttempted',0)}\n"
           f"💪 **ריבאונדים:** {s.get('reboundsTotal', 0)}\n"
           f"🪄 **אסיסטים:** {s.get('assists', 0)}\n"
           f"🧤 **חטיפות:** {s.get('steals', 0)}\n"
           f"🚫 **חסימות:** {s.get('blocks', 0)}\n"
           f"⚠️ **איבודים:** {s.get('turnovers', 0)}\n"
           f"📊 **פלוס/מינוס:** {s.get('plusMinusPoints', 0)}\n"
           f"⏱️ **דקות:** {format_minutes(s.get('minutesCalculated', ''))}\n"
           f"━━━━━━━━━━━━━━")
    return msg

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
    a_heb, h_heb = TEAM_NAMES_HEB.get(away['teamName'], away['teamName']), TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])
    score = f"{home['score']} - **{away['score']} {a_heb}**" if away['score'] > home['score'] else f"{away['score']} - **{home['score']} {h_heb}**"
    msg = f"🔥 **{label}: {a_heb} 🆚 {h_heb}** 🔥\n📈 תוצאה: {score}\n\n"
    for team in [away, home]:
        msg += f"📍 **{TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])}**:\n"
        players = sorted(team['players'], key=lambda x: x['statistics']['points'], reverse=True)
        for p in [p for p in players if p.get('starter') == "1"][:2]:
            msg += f"🥇 {get_stat_line(p)} (חמישייה)\n"
        bench = [p for p in players if p.get('starter') == "0"][:1]
        if bench:
            msg += f"⚡ **מהספסל:** {get_stat_line(bench[0])}\n"
        msg += "\n"
    return msg

def format_final_summary(box, ot_label=""):
    away, home = box['awayTeam'], box['homeTeam']
    a_heb, h_heb = TEAM_NAMES_HEB.get(away['teamName'], away['teamName']), TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])
    score = f"{home['score']} - **{away['score']} {a_heb}**" if away['score'] > home['score'] else f"{away['score']} - **{home['score']} {h_heb}**"
    mvp = max(away['players'] + home['players'], key=lambda x: x['statistics']['points'])
    
    msg = f"🏁🏀 **סיום המשחק {ot_label}: {a_heb} 🆚 {h_heb}** 🏁🏀\n🏆 **תוצאה סופית: {score}**\n⭐ **MVP:** {translate(mvp['firstName'] + ' ' + mvp['familyName'])} ({mvp['statistics']['points']} נק')\n──────────────────\n\n"
    for team in [away, home]:
        msg += f"📍 **{TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])}**:\n🏀 **חמישייה פותחת:**\n"
        for p in [p for p in team['players'] if p.get('starter') == "1"]:
            msg += f"{get_stat_line(p)}\n"
        msg += "⚡ **3 בולטים מהספסל:**\n"
        bench = sorted([p for p in team['players'] if p.get('starter') == "0"], key=lambda x: x['statistics']['points'], reverse=True)[:3]
        for p in bench:
            msg += f"{get_stat_line(p)}\n"
        msg += "\n"
    return msg, mvp

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

            # לו"ז מעוצב - דגל ישראל לפני ה-🆚 וזמן שליחה 20:20
            if now.hour == 20 and now.minute == 10 and state["dates"]["schedule"] != today:
                msg = "**🏀 ══ לוח המשחקים להיום בלילה ══ 🏀**\n\n"
                
                # רשימת הקבוצות של הישראלים
                israeli_teams = ["Trail Blazers", "Wizards"]
                
                for g in games:
                    try:
                        time_str = g['startTimeUTC'].split('T')[1][:5]
                        utc_dt = datetime.strptime(time_str, "%H:%M")
                        il_dt = utc_dt + timedelta(hours=2)
                        time_display = il_dt.strftime("%H:%M")
                    except:
                        time_display = g.get('gameStatusText', '00:00')

                    away_name = g['awayTeam']['teamName']
                    home_name = g['homeTeam']['teamName']
                    
                    away_heb = TEAM_NAMES_HEB.get(away_name, away_name)
                    home_heb = TEAM_NAMES_HEB.get(home_name, home_name)
                    
                    # בדיקה אם אחד מהצדדים הוא ישראלי כדי להוסיף את הדגל לפני ה-VS
                    isr_flag = " 🇮🇱" if (away_name in israeli_teams or home_name in israeli_teams) else ""
                    
                    msg += f"⏰ **{time_display}**\n"
                    msg += f"🏀 **{away_heb}**{isr_flag} 🆚 **{home_heb}**\n\n"
                
                send_msg(msg + "*צפייה מהנה!* 📺")
                state["dates"]["schedule"] = today
                save_state(state)
                
            # ניטור משחקים
            for g in games:
                gid, status = g['gameId'], g['gameStatus']
                if status > 1:
                    if gid not in state["games"]: state["games"][gid] = {"p": [], "f": False, "s": False, "ot": 0}
                    gs = state["games"][gid]
                    
                    try:
                        box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']
                    except: continue

                    # פתיחת משחק
                    if status == 2 and not gs["s"]:
                        send_msg(format_start_game(box))
                        gs["s"] = True

                    # עדכוני רבעים + הארכות
                    txt = g['gameStatusText'].strip()
                    if "OT" in txt and g['period'] > gs["ot"]:
                        send_msg(f"⚠️ **דרמה ב-NBA! שוויון {g['homeTeam']['score']}-{g['awayTeam']['score']}. נכנסים להארכה (OT{g['period']-4})!**")
                        gs["ot"] = g['period']

                    if ("End" in txt or "Half" in txt) and txt not in gs["p"]:
                        label = "מחצית" if "Half" in txt else f"סיום רבע {g['period']}"
                        send_msg(format_period_update(box, label))
                        
                        # הודעה נפרדת לישראלים
                        for team in [box['awayTeam'], box['homeTeam']]:
                            for p in team['players']:
                                if f"{p['firstName']} {p['familyName']}" in ISRAELI_PLAYERS and p['statistics']['minutesCalculated'] != "PT00M00.00S":
                                    send_msg(format_israeli_card(p, label))
                        gs["p"].append(txt)

                    # סיום משחק
                    if status == 3 and not gs["f"]:
                        ot_label = f"(לאחר {g['period']-4} הארכות)" if g['period'] > 4 else ""
                        msg_f, mvp_p = format_final_summary(box, ot_label)
                        send_msg(msg_f)
                        
                        # כרטיס ישראלי סופי עם בדיקת MVP
                        for team in [box['awayTeam'], box['homeTeam']]:
                            for p in team['players']:
                                if f"{p['firstName']} {p['familyName']}" in ISRAELI_PLAYERS and p['statistics']['minutesCalculated'] != "PT00M00.00S":
                                    send_msg(format_israeli_card(p, "סופי", p['personId'] == mvp_p['personId']))
                        gs["f"] = True
                    save_state(state)

        except Exception as e:
            logging.error(f"Error: {e}")
        time.sleep(30)

if __name__ == "__main__":
    run_bot()








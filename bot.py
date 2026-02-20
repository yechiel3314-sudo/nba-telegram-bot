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
    "Pistons": "דטרויט פיסטונס", "Raptors": "טורונטו ראפטורס", "Wizards": "וושינגטון וויזארדס",
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
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown" # השורה הזו היא הקסם שיוצר את ההדגשה
    }
    try: 
        requests.post(url, json=payload, timeout=15)
    except: 
        pass

# ==========================================
# בוני הודעות מעוצבות - גרסה סופית ומלאה
# ==========================================

def get_clean_stat_line(p):
    """בונה שורת סטטיסטיקה: נק/רב/אס תמיד, חט/חס רק אם יש"""
    s = p.get('statistics', {})
    # נתוני ליבה שתמיד יופיעו
    line = f"{s.get('points', 0)} נק', {s.get('reboundsTotal', 0)} רב', {s.get('assists', 0)} אס'"
    
    # נתוני הגנה רק אם גדול מ-0
    extra = []
    if s.get('steals', 0) > 0: extra.append(f"{s.get('steals', 0)} חט'")
    if s.get('blocks', 0) > 0: extra.append(f"{s.get('blocks', 0)} חס'")
    
    if extra:
        line += f" ({', '.join(extra)})"
    return line

def format_israeli_card(p, label, is_mvp=False):
    """כרטיס שחקן ישראלי - כולל עונשין ויישור לימין"""
    s = p.get('statistics', {})
    name = translate(f"{p['firstName']} {p['familyName']}")
    mvp_tag = f"\n\u200f⭐ **MVP של המשחק!** ⭐" if is_mvp else ""
    
    msg = f"\u200f" + f"🇮🇱 **גאווה ישראלית: {name}** 🇮🇱{mvp_tag}\n"
    msg += f"\u200f" + f"🏀 סטטיסטיקה ({label}):\n\n"
    msg += f"\u200f" + f"🎯 נקודות: **{s.get('points', 0)}**\n"
    msg += f"\u200f" + f"🏀 מהשדה: {s.get('fieldGoalsMade',0)}/{s.get('fieldGoalsAttempted',0)}\n"
    msg += f"\u200f" + f"🏹 לשלוש: {s.get('threePointersMade',0)}/{s.get('threePointersAttempted',0)}\n"
    msg += f"\u200f" + f"✨ עונשין: {s.get('freeThrowsMade',0)}/{s.get('freeThrowsAttempted',0)}\n"
    msg += f"\u200f" + f"💪 ריבאונדים: {s.get('reboundsTotal', 0)}\n"
    msg += f"\u200f" + f"🪄 אסיסטים: {s.get('assists', 0)}\n"
    msg += f"\u200f" + f"🧤 חטיפות: {s.get('steals', 0)}\n"
    msg += f"\u200f" + f"🚫 חסימות: {s.get('blocks', 0)}\n"
    msg += f"\u200f" + f"⏱️ דקות: {format_minutes(s.get('minutesCalculated', ''))}\n"
    return msg

def format_start_game(box):
    """הודעת פתיחת משחק עם זיהוי אוטומטי של חמישייה וחיסורים"""
    away, home = box['awayTeam'], box['homeTeam']
    a_full = TEAM_NAMES_HEB.get(away['teamName'], away['teamName'])
    h_full = TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])
    
    msg = f"\u200f" + f"🔥 **המשחק יצא לדרך!** 🔥\n"
    msg += f"\u200f" + f"🏀 **{a_full} 🆚 {h_full}** 🏀\n\n"
    
    for team in [away, home]:
        t_name = TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])
        
        # שליפת חמישייה
        starters = [translate(f"{p['firstName']} {p['familyName']}") for p in team['players'] if p.get('starter') == "1"]
        
        # שליפת חיסורים
        missing = []
        for p in team['players']:
            reason = p.get('notPlayingReason')
            if reason:
                p_name = translate(f"{p['firstName']} {p['familyName']}")
                missing.append(p_name)
        
        if missing:
            missing_txt = ", ".join(missing)
        else:
            missing_txt = "אין חיסורים מדווחים"

        msg += f"\u200f" + f"📍 **{t_name}**\n"
        msg += f"\u200f" + f"▫️ **חמישייה:** {', '.join(starters)}\n"
        msg += f"\u200f" + f"❌ **חיסורים:** {missing_txt}\n\n"
        
    return msg
    
def format_period_update(box, label):
    """עדכון רבע/מחצית שוטף"""
    away, home = box['awayTeam'], box['homeTeam']
    a_f, h_f = TEAM_NAMES_HEB.get(away['teamName'], away['teamName']), TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])
    
    winner = a_f if away['score'] > home['score'] else h_f
    score_txt = f"{winner} מובילה {max(away['score'], home['score'])} - {min(away['score'], home['score'])}" if away['score'] != home['score'] else f"שוויון {away['score']} - {home['score']}"
    
    msg = f"\u200f" + f"🏀 **{label} | {a_f} 🆚 {h_f}**\n"
    msg += f"\u200f" + f"📊 {score_txt}\n\n"
    
    for team in [away, home]:
        msg += f"\u200f" + f"📍 **{TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])}**\n"
        players = sorted(team['players'], key=lambda x: x['statistics']['points'], reverse=True)
        # קלעי חמישייה מובילים (2)
        for i, p in enumerate([p for p in players if p.get('starter') == "1"][:2]):
            m = "🥇" if i == 0 else "🥈"
            msg += f"\u200f{m} קלע מוביל {i+1}: **{translate(p['firstName']+' '+p['familyName'])}**: {get_clean_stat_line(p)}\n"
        # מצטיין ספסל
        bench = [p for p in players if p.get('starter') == "0"]
        if bench:
            msg += f"\u200f⚡ מהספסל: **{translate(bench[0]['firstName']+' '+bench[0]['familyName'])}**: {get_clean_stat_line(bench[0])}\n"
        msg += "\n"
    return msg

def format_final_summary(box, ot_count=0):
    """סיכום משחק סופי עם מדליות וספסל"""
    away, home = box['awayTeam'], box['homeTeam']
    a_f, h_f = TEAM_NAMES_HEB.get(away['teamName'], away['teamName']), TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])
    winner = a_f if away['score'] > home['score'] else h_f
    
    ot_label = f" (לאחר {ot_count} הארכות)" if ot_count > 1 else (" (לאחר הארכה)" if ot_count == 1 else "")
    
    msg = f"\u200f🏁🏀 **סיום המשחק{ot_label} 🏁🏀**\n"
    msg += f"\u200f🏀 **{a_f} 🆚 {h_f}**\n"
    msg += f"\u200f🏆 **{winner} מנצחת {max(away['score'], home['score'])} - {min(away['score'], home['score'])}**\n"
    
    mvp = max(away['players'] + home['players'], key=lambda x: x['statistics']['points'])
    msg += f"\n\u200f⭐ MVP: **{translate(mvp['firstName'] + ' ' + mvp['familyName'])}** ({mvp['statistics']['points']} נק')\n\n"
    
    for team in [away, home]:
        msg += f"\u200f📍 **{TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])}**\n"
        msg += f"\u200f🏀 חמישייה פותחת:\n"
        
        players = sorted(team['players'], key=lambda x: x['statistics']['points'], reverse=True)
        starters = [p for p in players if p.get('starter') == "1"]
        
        for i, p in enumerate(starters):
            m = "🥇" if i == 0 else ("🥈" if i == 1 else ("🥉" if i == 2 else "▫️"))
            msg += f"\u200f{m} **{translate(p['firstName']+' '+p['familyName'])}**: {get_clean_stat_line(p)}\n"
        
        msg += f"\n\u200f⚡ **3 בולטים מהספסל:**\n"
        bench = [p for p in players if p.get('starter') == "0"][:3]
        for p in bench:
            msg += f"\u200f▫️ **{translate(p['firstName']+' '+p['familyName'])}**: {get_clean_stat_line(p)}\n"
        msg += "\n"
    return msg, mvp

# ==========================================
# לוגיקה ללולאת הרצה (run_bot)
# ==========================================
# (יש לשלב קטע זה בתוך לולאת זיהוי הסטטוסים שלך)

def handle_game_logic(g, box, gs):
    txt = g['gameStatusText']
    home, away = box['homeTeam'], box['awayTeam']
    
    # 1. פתיחת משחק
    if g['period'] == 1 and g['gameStatus'] == 2 and "start" not in gs:
        send_msg(format_start_game(box))
        gs["start"] = True

    # 2. הארכות וסיומי רבעים
    if ("End" in txt or "Half" in txt) and txt not in gs["p"]:
        label = "מחצית" if "Half" in txt else f"סיום רבע {g['period']}"
        send_msg(format_period_update(box, label))
        
        # עדכוני גאווה ישראלית (דני אבדיה, בן שרף, דני וולף)
        for team in [away, home]:
            for p in team['players']:
                p_full = f"{p['firstName']} {p['familyName']}"
                if p_full in ISRAELI_PLAYERS:
                    send_msg(format_israeli_card(p, label))

        # בדיקת שוויון והודעת הארכה
        if g['period'] >= 4 and home['score'] == away['score']:
            ot_num = g['period'] - 3
            a_name = TEAM_NAMES_HEB.get(away['teamName'], away['teamName'])
            h_name = TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])
            
            if ot_num == 1:
                # הארכה ראשונה
                drama = f"\u200f⚠️ **דרמה ב-NBA: הולכים להארכה!** ⚠️\n"
                drama += f"\u200f🏟️ **{a_name}** 🆚 **{h_name}**\n"
                drama += f"\u200f📊 תוצאה בסיום 4 רבעים: **{home['score']}-{away['score']}**"
            else:
                # הארכה שנייה ומעלה
                drama = f"\u200f😱 **לא נגמר! הארכה {ot_num} (OT{ot_num}) יוצאת לדרך!** 😱\n"
                drama += f"\u200f🏟️ **{a_name}** 🆚 **{h_name}**\n"
                drama += f"\u200f🔥 **הקרב נמשך...**"
            
            send_msg(drama)
            gs["ot_count"] = ot_num
        
        gs["p"].append(txt)

    # 3. סיום משחק סופי
    if g['gameStatus'] == 3 and "final" not in gs:
        ot_count = gs.get("ot_count", 0)
        final_msg, mvp = format_final_summary(box, ot_count)
        send_msg(final_msg)
        
        # גאווה ישראלית לסיום
        for team in [away, home]:
            for p in team['players']:
                p_full = f"{p['firstName']} {p['familyName']}"
                if p_full in ISRAELI_PLAYERS:
                    send_msg(format_israeli_card(p, "סיכום משחק", is_mvp=(p==mvp)))
        
        gs["final"] = True

def send_all_games_summary():
    """שולח הודעת סיכום בוקר: המנצחת והמפסידה באותה שורה"""
    try:
        resp = requests.get("https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json", timeout=15).json()
        games = resp.get('scoreboard', {}).get('games', [])
        
        if not games:
            return

        msg = f"\u200f" + f"🏀 **תוצאות משחקי הלילה ב-NBA** 🏀\n\n"
        found_finished = False

        for g in games:
            if g['gameStatus'] == 3:  # משחק שהסתיים
                away_n = g['awayTeam']['teamName']
                home_n = g['homeTeam']['teamName']
                away_heb = TEAM_NAMES_HEB.get(away_n, away_n)
                home_heb = TEAM_NAMES_HEB.get(home_n, home_n)
                
                a_score = g['awayTeam']['score']
                h_score = g['homeTeam']['score']
                
                # המנצחת תמיד ראשונה
                if a_score > h_score:
                    winner_name, winner_score = away_heb, a_score
                    loser_name, loser_score = home_heb, h_score
                else:
                    winner_name, winner_score = home_heb, h_score
                    loser_name, loser_score = away_heb, a_score
                
                # בניית השורה המעוצבת
                msg += f"\u200f" + f"🏆 **{winner_name}** 🆚 {loser_name}\n"
                msg += f"\u200f" + f"🏁 תוצאה: **{winner_score}** - {loser_score}\n"
                msg += f"\u200f" + f"‏‏‎ ‎\n" # רווח קטן
                
                found_finished = True

        if found_finished:
            msg += f"\u200f" + f"☀️ **יום טוב לכולם**"
            send_msg(msg)
            
    except Exception as e:
        logging.error(f"Error in morning summary: {e}")

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

            # לו"ז מעוצב - פתרון מושלם ומדויק
            if now.hour == 18 and now.minute == 0 and state["dates"].get("schedule") != today:
                # שימוש בתו \u200f כדי להצמיד הכל לימין (RTL) בטלגרם
                msg = "\u200f" + "🏀 **══ לוח המשחקים להיום בלילה ══** 🏀\n\n"
                
                israeli_teams = ["Nets", "Trail Blazers"]
                
                for g in games:
                    try:
                        # שליפה חכמה של הזמן - בודק את כל המפתחות האפשריים ב-API
                        raw_time = g.get('startTimeUTC') or g.get('gameTimeUTC')
                        
                        if raw_time:
                            # הפיכה לאובייקט זמן (מתמודד עם פורמט Z של ה-NBA)
                            utc_dt = datetime.strptime(raw_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                            # המרה לשעון ישראל (UTC+2)
                            il_dt = utc_dt.astimezone(timezone(timedelta(hours=2)))
                            time_display = il_dt.strftime("%H:%M")
                        else:
                            time_display = "--:--"
                    except Exception as e:
                        logging.error(f"Time error for game {g.get('gameId')}: {e}")
                        time_display = "--:--"

                    away_n = g['awayTeam']['teamName']
                    home_n = g['homeTeam']['teamName']
                    away_heb = TEAM_NAMES_HEB.get(away_n, away_n)
                    home_heb = TEAM_NAMES_HEB.get(home_n, home_n)
                    
                    # דגל רק לברוקלין ופורטלנד
                    a_flag = " 🇮🇱" if away_n in israeli_teams else ""
                    h_flag = " 🇮🇱" if home_n in israeli_teams else ""
                    
                    # הרכבת השורה: תו RTL + שעה מודגשת + קבוצות
                    msg += f"\u200f⏰ **{time_display}**\n"
                    msg += f"\u200f🏀 {away_heb}{a_flag} 🆚 {home_heb}{h_flag}\n\n"
                
                msg += "\u200f**צפייה מהנה! 📺**"
                
                send_msg(msg)
                # עדכון הסטייט כדי שלא ישלח שוב עד מחר
                state["dates"]["schedule"] = today
                save_state(state)

            if now.hour == 7 and now.minute == 0 and state["dates"].get("summary") != today:
                send_all_games_summary()
                state["dates"]["summary"] = today
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




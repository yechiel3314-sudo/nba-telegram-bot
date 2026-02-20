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
NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
STATE_FILE = "nba_fire_design_v1.json"
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
    
    # המרת הכוכביות (**) לתגיות HTML (<b>) כדי שזה יעבוד בטוח
    formatted_text = text.replace("**", "<b>").replace("**", "</b>") # החלפה ראשונה פותחת, שניה סוגרת
    
    # בגלל שהחלפה פשוטה בסטרינג יכולה להתבלבל, עדיף להשתמש בשיטה הזו:
    import re
    formatted_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)

    payload = {
        "chat_id": CHAT_ID,
        "text": formatted_text,
        "parse_mode": "HTML" 
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
    """עדכון רבע/מחצית עם עיצוב כדורסל, אש וסטטיסטיקה מורחבת"""
    away, home = box['awayTeam'], box['homeTeam']
    a_f = TEAM_NAMES_HEB.get(away['teamName'], away['teamName'])
    h_f = TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])
    
    # 1. כותרת עליונה - כדורסל משני הצדדים
    header = f"🏀 {label}: {a_f} 🆚 {h_f} 🏀"
    
    # 2. חישוב תוצאה ומובילה - אש משני הצדדים
    if away['score'] > home['score']:
        score_txt = f"🔥 **{a_f}** מובילה **{away['score']} - {home['score']}** 🔥"
    elif home['score'] > away['score']:
        score_txt = f"🔥 **{h_f}** מובילה **{home['score']} - {away['score']}** 🔥"
    else:
        score_txt = f"🔥 **שוויון {away['score']} - {home['score']}** 🔥"
    
    msg = f"\u200f{header}\n"
    msg += f"\u200f{score_txt}\n\n"
    
    for team in [away, home]:
        t_name = TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])
        msg += f"\u200f📍 **{t_name}**\n"
        
        # מיון כל השחקנים לפי נקודות
        players = sorted(team['players'], key=lambda x: x['statistics']['points'], reverse=True)
        
        # פונקציית עזר פנימית לבניית שורת סטטיסטיקה מפורטת (נק', רב', אס' + חט', חס')
        def get_clean_stat_line(p):
            s = p['statistics']
            line = f"{s['points']} נק', {s['reboundsTotal']} רב', {s['assists']} אס'"
            extra = []
            if s.get('steals', 0) > 0: extra.append(f"{s['steals']} חט'")
            if s.get('blocks', 0) > 0: extra.append(f"{s['blocks']} חס'")
            if extra:
                line += f" ({', '.join(extra)})"
            return line

        # 2 קלעי חמישייה מובילים (starter == "1") עם תרגום שמות
        starters = [p for p in players if p.get('starter') == "1"][:2]
        for i, p in enumerate(starters):
            m = "🥇" if i == 0 else "🥈"
            # תרגום השם המלא לעברית
            p_name_heb = translate(f"{p['firstName']} {p['familyName']}")
            msg += f"\u200f{m} **{p_name_heb}**: {get_clean_stat_line(p)}\n"
            
        # מצטיין ספסל (starter == "0") עם תרגום שמות
        bench = [p for p in players if p.get('starter') == "0"]
        if bench:
            b_p = bench[0]
            b_name_heb = translate(f"{b_p['firstName']} {b_p['familyName']}")
            msg += f"\u200f⚡ **ספסל: {b_name_heb}**: {get_clean_stat_line(b_p)}\n"
            
        msg += "\n"
        
    return msg
    
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
    # שליפת נתונים וניקוי טקסט
    txt = g.get('gameStatusText', '').strip()
    home, away = box['homeTeam'], box['awayTeam']
    period = g.get('period', 0)
    status = g.get('gameStatus', 0)
    
    if "p" not in gs: gs["p"] = []
    txt_low = txt.lower()
    
    # זיהוי האם מדובר בסיום תקופה (רבע/מחצית)
    is_period_over = any(word in txt_low for word in ["end", "half", "qtr"]) and ":" not in txt
    
    # 1. פתיחת משחק
    if period == 1 and status == 2 and not gs.get("start"):
        send_msg(format_start_game(box))
        gs["start"] = True

    # 2. עדכוני רבעים ומחצית - עם חסימה לרבע 4 ומעלה
    if is_period_over and txt not in gs["p"]:
        # תיקון: אם זה רבע 4 או הארכה, אנחנו לא שולחים הודעת "סיום רבע".
        # אנחנו מחכים אך ורק להודעת ה-Final (סטטוס 3) למטה.
        if status == 3 or period >= 4:
            pass 
        else:
            if "half" in txt_low: label = "מחצית"
            else: label = f"סיום רבע {period}"
            send_msg(format_period_update(box, label))
            gs["p"].append(txt)

    # 3. סיום משחק סופי - תמיד יישלח כשהסטטוס הופך ל-3
    if status == 3 and not gs.get("final"):
        send_msg(format_rich_final_summary(box))
        gs["final"] = True

def format_period_update(box, label):
    away, home = box['awayTeam'], box['homeTeam']
    a_f = TEAM_NAMES_HEB.get(away['teamName'], away['teamName'])
    h_f = TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])
    
    # כותרת מקורית עם כדורסל
    msg = f"\u200f" + f"🏀 {label}: {a_f} 🆚 {h_f} 🏀\n"
    
    if away['score'] > home['score']:
        score_txt = f"🔥 **{a_f} מובילה {away['score']} - {home['score']}** 🔥"
    elif home['score'] > away['score']:
        score_txt = f"🔥 **{h_f} מובילה {home['score']} - {away['score']}** 🔥"
    else:
        score_txt = f"🔥 **שוויון {away['score']} - {home['score']}** 🔥"
    
    msg += f"\u200f{score_txt}\n\n"
    
    for team in [away, home]:
        t_name = TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])
        msg += f"\u200f📍 **{t_name}**\n"
        players = sorted(team['players'], key=lambda x: x['statistics']['points'], reverse=True)
        
        def get_stat_line(p):
            s = p['statistics']
            line = f"{s['points']} נק', {s['reboundsTotal']} רב', {s['assists']} אס'"
            extra = []
            if s.get('steals', 0) > 0: extra.append(f"{s['steals']} חט'")
            if s.get('blocks', 0) > 0: extra.append(f"{s['blocks']} חס'")
            return f"{line} ({', '.join(extra)})" if extra else line

        # 2 מובילים מחמישייה ואחד מהספסל
        starters = [p for p in players if p.get('starter') == "1"][:2]
        for i, p in enumerate(starters):
            icon = "🥇" if i == 0 else "🥈"
            p_name = translate(f"{p['firstName']} {p['familyName']}")
            msg += f"\u200f{icon} **{p_name}**: {get_stat_line(p)}\n"
            
        bench = [p for p in players if p.get('starter') == "0"]
        if bench:
            b_name = translate(f"{bench[0]['firstName']} {bench[0]['familyName']}")
            msg += f"\u200f⚡ **ספסל: {b_name}**: {get_stat_line(bench[0])}\n"
        msg += "\n"
    return msg

def format_rich_final_summary(box):
    away, home = box['awayTeam'], box['homeTeam']
    a_f = TEAM_NAMES_HEB.get(away['teamName'], away['teamName'])
    h_f = TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])
    
    msg = f"\u200f" + f"🏀 🏁 **סיום משחק: {a_f} 🆚 {h_f}** 🏁 🏀\n"
    if away.get('score', 0) > home.get('score', 0):
        msg += f"\u200f🏆 **{a_f} מנצחת {away['score']} - {home['score']}** 🏆\n\n"
    else:
        msg += f"\u200f🏆 **{h_f} מנצחת {home['score']} - {away['score']}** 🏆\n\n"

    def get_stat_line_with_extras(p):
        s = p.get('statistics', {})
        line = f"{s.get('points', 0)} נק', {s.get('reboundsTotal', 0)} רב', {s.get('assists', 0)} אס'"
        extra = []
        if s.get('steals', 0) > 0: extra.append(f"{s.get('steals', 0)} חט'")
        if s.get('blocks', 0) > 0: extra.append(f"{s.get('blocks', 0)} חס'")
        return f"{line} ({', '.join(extra)})" if extra else line

    all_players = away.get('players', []) + home.get('players', [])
    if not all_players: return msg
    
    mvp = max(all_players, key=lambda x: x['statistics'].get('points', 0))
    mvp_name = translate(f"{mvp['firstName']} {mvp['familyName']}")
    
    tri = mvp.get('teamTricode', '')
    tri_str = f" ({tri})" if tri else ""
        
    msg += f"\u200f🌟 **ה-MVP:** **{mvp_name}**{tri_str}\n"
    msg += f"\u200f📊 {get_stat_line_with_extras(mvp)}\n\n"
    msg += f"\u200f" + "─" * 15 + "\n\n"

    for team in [away, home]:
        t_name = TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])
        msg += f"\u200f📍 **סטטיסטיקת {t_name}:**\n"
        players = sorted(team['players'], key=lambda x: x['statistics'].get('points', 0), reverse=True)
        
        msg += f"\u200f🏀 **חמישייה:**\n"
        for p in [p for p in players if p.get('starter') == "1"]:
            p_name = translate(f"{p['firstName']} {p['familyName']}")
            msg += f"\u200f▫️ **{p_name}**: {get_stat_line_with_extras(p)}\n"
            
        msg += "\n"
        
        msg += f"\u200f⚡ **ספסל מוביל:**\n"
        bench = [p for p in players if p.get('starter') == "0"][:3]
        for p in bench:
            p_name = translate(f"{p['firstName']} {p['familyName']}")
            msg += f"\u200f▪️ **{p_name}**: {get_stat_line_with_extras(p)}\n"
        msg += "\n"
    return msg
            
# ==========================================
# לולאה ראשית
# ==========================================

def run_bot():
    state = load_state()
    print("🚀 הבוט התחיל לרוץ...")
    
    while True:
        try:
            # משיכת רשימת המשחקים
            response = requests.get(NBA_URL, timeout=10)
            games = response.json()['scoreboard']['games']
            
            for g in games:
                gid, status = g['gameId'], g['gameStatus']
                
                # בדיקה אם המשחק פעיל או הסתיים (סטטוס 2 או 3)
                if status > 1:
                    # יצירת ה-State למשחק אם לא קיים - שימוש בשמות מפתחות תקינים
                    if gid not in state["games"]: 
                        state["games"][gid] = {"p": [], "final": False, "start": False, "ot_count": 0}
                    
                    gs = state["games"][gid]
                    
                    try:
                        # משיכת נתונים מפורטים (Boxscore)
                        box_url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
                        box_res = requests.get(box_url, timeout=10)
                        box = box_res.json()['game']
                        
                        # הפעלה של הלוגיקה המרכזית - היא המוח היחיד שמחליט על שליחה
                        handle_game_logic(g, box, gs)
                        
                        # שמירה לאחר כל עדכון
                        save_state(state)
                        
                    except Exception as e:
                        logging.error(f"Error in game {gid}: {e}")
                        continue

        except Exception as e:
            logging.error(f"General Loop Error: {e}")
        
        # המתנה של 20 שניות בין סריקות
        time.sleep(20)

if __name__ == "__main__":
    run_bot()
    



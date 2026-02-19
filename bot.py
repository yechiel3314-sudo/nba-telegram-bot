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
STATE_FILE = "nba_complete_master_v10.json"
ISRAELI_PLAYERS = ["Deni Avdija", "Ben Saraf", "Danny Wolf"]

# הגדרת לוגים לאיתור תקלות בזמן אמת
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("nba_bot.log"), logging.StreamHandler()]
)

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
# פונקציות תשתית וניהול שגיאות
# ==========================================

def load_state():
    """טוען את מצב הבוט מקובץ כדי למנוע כפילויות אחרי קריסה/אתחול"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "games" not in data: data["games"] = {}
                if "dates" not in data: data["dates"] = {"schedule": "", "summary": ""}
                return data
        except Exception as e:
            logging.error(f"שגיאה בטעינת קובץ המצב: {e}")
    return {"games": {}, "dates": {"schedule": "", "summary": ""}}

def save_state(state):
    """שומר את מצב הבוט הנוכחי"""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"שגיאה בשמירת קובץ המצב: {e}")

def translate_player(name):
    """מתרגם שמות שחקנים עם זיכרון מטמון"""
    if name in name_cache:
        return name_cache[name]
    try:
        translated = translator.translate(name)
        name_cache[name] = translated
        return translated
    except Exception:
        return name

def format_minutes(mins_raw):
    """הופך פורמט NBA לפורמט קריא (12:30)"""
    if not mins_raw or "PT" not in mins_raw:
        return "0:00"
    try:
        time_str = mins_raw.replace("PT", "").replace("M", ":").replace("S", "")
        if "." in time_str:
            time_str = time_str.split(".")[0]
        parts = time_str.split(":")
        if len(parts) == 2:
            return f"{parts[0]}:{parts[1].zfill(2)}"
        return time_str
    except:
        return "0:00"

def send_msg(text):
    """שולח הודעה לטלגרם"""
    if not text: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    
    for attempt in range(3):
        try:
            response = requests.post(url, json=payload, timeout=15)
            if response.status_code == 200:
                return True
            logging.warning(f"ניסיון שליחה {attempt+1} נכשל: {response.text}")
        except Exception as e:
            logging.error(f"שגיאת תקשורת בשליחת הודעה: {e}")
        time.sleep(5)
    return False

# ==========================================
# פונקציות עיבוד נתונים וסטטיסטיקה
# ==========================================

def calculate_efficiency(p):
    """חישוב מדד יעילות (EFF) לזיהוי MVP"""
    s = p.get("statistics", {})
    try:
        pts = s.get('points', 0)
        reb = s.get('reboundsTotal', 0)
        ast = s.get('assists', 0)
        stl = s.get('steals', 0)
        blk = s.get('blocks', 0)
        miss_fg = s.get('fieldGoalsAttempted', 0) - s.get('fieldGoalsMade', 0)
        miss_ft = s.get('freeThrowsAttempted', 0) - s.get('freeThrowsMade', 0)
        tov = s.get('turnovers', 0)
        return (pts + reb + ast + stl + blk) - (miss_fg + miss_ft + tov)
    except:
        return 0

def get_stat_line(p, extended=False):
    """שורת סטטיסטיקה לשחקן בודד"""
    s = p.get('statistics', {})
    full_name = f"{p['firstName']} {p['familyName']}"
    name_heb = f"**{translate_player(full_name)}**"
    
    line = f"▫️ {name_heb}: {s.get('points', 0)} נק', {s.get('reboundsTotal', 0)} ריב', {s.get('assists', 0)} אס'"
    
    if extended:
        extras = []
        if s.get('steals', 0) > 0: extras.append(f"{s['steals']} חט'")
        if s.get('blocks', 0) > 0: extras.append(f"{s['blocks']} חס'")
        if s.get('turnovers', 0) > 0: extras.append(f"{s['turnovers']} איב'")
        if extras:
            line += f" ({', '.join(extras)})"
    return line

# ==========================================
# בוני הודעות מעוצבות
# ==========================================

def format_period_update(game_data, label):
    """הודעת סיכום רבע או מחצית"""
    away = game_data['awayTeam']
    home = game_data['homeTeam']
    away_heb = TEAM_NAMES_HEB.get(away['teamName'], away['teamName'])
    home_heb = TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])
    
    if away['score'] > home['score']:
        score_desc = f"{away['score']} - {home['score']} ל{away_heb}"
    elif home['score'] > away['score']:
        score_desc = f"{away['score']} - {home['score']} ל{home_heb}"
    else:
        score_desc = f"{away['score']} - {home['score']} (שוויון)"

    msg = f"📊 {label}: {away_heb} 🆚 {home_heb} 🏀\n"
    msg += f"📈 תוצאה: {score_desc}\n\n"

    for team in [away, home]:
        t_name = TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])
        p_list = team.get('players', [])
        starters = sorted([p for p in p_list if p.get('starter') == "1"], 
                          key=lambda x: x['statistics']['points'], reverse=True)
        bench = sorted([p for p in p_list if p.get('starter') == "0" and p['statistics']['minutesCalculated'] != "PT00M00.00S"], 
                       key=lambda x: x['statistics']['points'], reverse=True)
        
        msg += f"🔥 *{t_name}*:\n"
        if len(starters) >= 1: msg += f"🥇 קלע 1: {get_stat_line(starters[0])}\n"
        if len(starters) >= 2: msg += f"🥈 קלע 2: {get_stat_line(starters[1])}\n"
        if bench:
            msg += f"⚡ מהספסל: {get_stat_line(bench[0])}\n"
        msg += "\n"
    return msg

def format_israeli_stats(p, label):
    """סטטיסטיקה מורחבת לישראלים עם שורות נפרדות ודקות בסוף"""
    s = p.get('statistics', {})
    if s.get('minutesCalculated') == "PT00M00.00S": return None
    
    name_heb = translate_player(f"{p['firstName']} {p['familyName']}")
    
    fg = f"{s['fieldGoalsMade']}/{s['fieldGoalsAttempted']}"
    tp = f"{s['threePointersMade']}/{s['threePointersAttempted']}"
    ft = f"{s['freeThrowsMade']}/{s['freeThrowsAttempted']}"

    msg = (f"🇮🇱 **גאווה ישראלית: {name_heb}** 🇮🇱\n"
           f"━━━━━━━━━━━━━━\n"
           f"🏀 **סטטיסטיקה מלאה ({label}):**\n\n"
           f"🎯 **נקודות:** {s['points']}\n"
           f"🏀 **מהשדה:** {fg} | **לשלוש:** {tp} | **עונשין:** {ft}\n"
           f"💪 **ריבאונדים:** {s['reboundsTotal']}\n"
           f"🪄 **אסיסטים:** {s['assists']}\n"
           f"🧤 **חטיפות:** {s['steals']}\n"
           f"🚫 **חסימות:** {s['blocks']}\n"
           f"⚠️ **איבודים:** {s['turnovers']}\n"
           f"📊 **מדד פלוס/מינוס:** {s['plusMinusPoints']}\n"
           f"⏱️ **דקות:** {format_minutes(s['minutesCalculated'])}\n"
           f"━━━━━━━━━━━━━━")
    return msg

def format_final_summary(data, ot_count):
    """סיכום סיום משחק עם כל החמישייה ו-3 מהספסל"""
    away = data['awayTeam']
    home = data['homeTeam']
    away_heb = TEAM_NAMES_HEB.get(away['teamName'], away['teamName'])
    home_heb = TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])
    
    ot_suffix = f" (לאחר {ot_count} הארכות)" if ot_count > 0 else ""
    winner_heb = away_heb if away['score'] > home['score'] else home_heb
    
    all_players = away['players'] + home['players']
    mvp_p = max(all_players, key=calculate_efficiency)
    mvp_name = translate_player(f"{mvp_p['firstName']} {mvp_p['familyName']}")

    msg = f"🏁🏀 **סיום המשחק: {away_heb} 🆚 {home_heb}** 🏁🏀\n\n"
    msg += f"🏆 **תוצאה סופית: {away['score']} - {home['score']} ל{winner_heb}{ot_suffix}**\n\n"
    msg += f"⭐ **MVP המשחק:** {mvp_name}\n"
    msg += "──────────────────\n\n"
    
    for team in [away, home]:
        t_name = TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])
        msg += f"📍 **{t_name}**:\n🏀 *חמישייה פותחת:*\n"
        
        starters = sorted([p for p in team['players'] if p.get('starter') == "1"], 
                          key=lambda x: x['statistics']['points'], reverse=True)
        for p in starters:
            msg += f"{get_stat_line(p, True)}\n"
            
        msg += "\n⚡ *3 בולטים מהספסל:*\n"
        bench = sorted([p for p in team['players'] if p.get('starter') == "0" and p['statistics']['minutesCalculated'] != "PT00M00.00S"], 
                       key=lambda x: x['statistics']['points'], reverse=True)[:3]
        for p in bench:
            msg += f"{get_stat_line(p, True)}\n"
        msg += "\n"
    return msg

# ==========================================
# לולאת הניטור הראשית
# ==========================================

def run_bot():
    state = load_state()
    logging.info("הבוט התחיל לעבוד במתכונת מלאה v10...")
    
    while True:
        try:
            now_il = datetime.now(timezone.utc) + timedelta(hours=2)
            date_key = now_il.strftime("%Y-%m-%d")

            try:
                sb_url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
                response = requests.get(sb_url, timeout=20)
                if response.status_code != 200:
                    logging.error(f"שרת ה-NBA החזיר שגיאה {response.status_code}")
                    time.sleep(60)
                    continue
                
                sb_data = response.json()
                games = sb_data.get('scoreboard', {}).get('games', [])
            except Exception as e:
                logging.error(f"שגיאה במשיכת נתונים: {e}")
                time.sleep(60)
                continue

            # שליחת לו"ז ב-18:00
            if now_il.hour == 18 and now_il.minute == 0 and state["dates"]["schedule"] != date_key:
                if games:
                    sched_msg = "🗓️ **לוח המשחקים להיום ובלילה:**\n\n"
                    for g in games:
                        a_n = TEAM_NAMES_HEB.get(g['awayTeam']['teamName'], g['awayTeam']['teamName'])
                        h_n = TEAM_NAMES_HEB.get(g['homeTeam']['teamName'], g['homeTeam']['teamName'])
                        sched_msg += f"⏰ NBA | {a_n} 🆚 {h_n}\n"
                    send_msg(sched_msg + "\n*צפייה מהנה!* 🏀")
                state["dates"]["schedule"] = date_key
                save_state(state)

            # סיכום בוקר ב-09:00 (מנצחת תמיד בימין ומודגשת)
            if now_il.hour == 9 and now_il.minute == 0 and state["dates"]["summary"] != date_key:
                if games:
                    morning_msg = "☕ **בוקר טוב! סיכום תוצאות הלילה ב-NBA:**\n"
                    morning_msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
                    for g in games:
                        a_n = TEAM_NAMES_HEB.get(g['awayTeam']['teamName'], g['awayTeam']['teamName'])
                        h_n = TEAM_NAMES_HEB.get(g['homeTeam']['teamName'], g['homeTeam']['teamName'])
                        a_s, h_s = g['awayTeam']['score'], g['homeTeam']['score']
                        
                        if a_s > h_s:
                            morning_msg += f"🏀 {h_n} {h_s} - **{a_s} {a_n}**\n"
                        else:
                            morning_msg += f"🏀 {a_n} {a_s} - **{h_s} {h_n}**\n"
                    send_msg(morning_msg + "\n━━━━━━━━━━━━━━━━━━━━\n**המשך יום נפלא!** ✨")
                state["dates"]["summary"] = date_key
                save_state(state)

            # ניטור משחקים חיים
            for g in games:
                gid = g['gameId']
                status = g['gameStatus']
                
                if status > 1:
                    if gid not in state["games"]:
                        state["games"][gid] = {"periods_sent": [], "final": False}
                    
                    g_state = state["games"][gid]
                    
                    try:
                        box_url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
                        box_data = requests.get(box_url, timeout=20).json()['game']
                    except: continue

                    status_text = g['gameStatusText'].strip()
                    p_key = f"per_{g['period']}_{status_text}"
                    
                    if ("End" in status_text or "Half" in status_text) and p_key not in g_state["periods_sent"]:
                        label = "מחצית" if "Half" in status_text else f"סיום רבע {g['period']}"
                        send_msg(format_period_update(box_data, label))
                        
                        for side in ['awayTeam', 'homeTeam']:
                            for player in box_data[side]['players']:
                                p_name = f"{player['firstName']} {player['familyName']}"
                                if p_name in ISRAELI_PLAYERS:
                                    isr_msg = format_israeli_stats(player, label)
                                    if isr_msg: send_msg(isr_msg)
                                    
                        g_state["periods_sent"].append(p_key)
                        save_state(state)

                    if status == 3 and not g_state["final"]:
                        ot = g['period'] - 4 if g['period'] > 4 else 0
                        send_msg(format_final_summary(box_data, ot))
                        
                        for side in ['awayTeam', 'homeTeam']:
                            for player in box_data[side]['players']:
                                p_name = f"{player['firstName']} {player['familyName']}"
                                if p_name in ISRAELI_PLAYERS:
                                    isr_final = format_israeli_stats(player, "סיום משחק")
                                    if isr_final: send_msg(isr_final)
                        
                        g_state["final"] = True
                        save_state(state)

        except Exception as e:
            logging.error(f"שגיאה כללית: {e}")
        
        time.sleep(30)

if __name__ == "__main__":
    run_bot()

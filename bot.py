from datetime import datetime, timedelta, timezone
import requests
import time
from deep_translator import GoogleTranslator

# --- הגדרות טכניות ---
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
MY_CHAT_ID = "6967694845"
translator = GoogleTranslator(source='auto', target='iw')
cache = {}

# מילון תרגום מלא לכל 30 קבוצות ה-NBA
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

ISRAELI_PLAYERS = ["Deni Avdija", "Ben Saraf", "Danny Wolf"]

def format_minutes(mins_raw):
    # הופך פורמט NBA (PT08M30S) לפורמט קריא (08:30)
    minutes = mins_raw.replace("PT", "").replace("M", ":").replace("S", "").split('.')[0]
    if ":" in minutes:
        parts = minutes.split(":")
        if len(parts[1]) == 1: parts[1] = "0" + parts[1]
        return f"{parts[0]}:{parts[1]}"
    return minutes

# --- פונקציות תרגום ועיבוד ---

def translate_player(name):
    if name in cache: return cache[name]
    try:
        res = translator.translate(name)
        cache[name] = res
        return res
    except: return name

def get_stat_line(p):
    s = p['statistics']
    # שם שחקן בדגש
    name = f"**{translate_player(p['firstName'] + ' ' + p['familyName'])}**"
    line = f"▫️ {name}: {s['points']} נק', {s['reboundsTotal']} ריב', {s['assists']} אס'"
    extras = []
    if s.get('steals', 0) > 0: extras.append(f"{s['steals']} חט'")
    if s.get('blocks', 0) > 0: extras.append(f"{s['blocks']} חס'")
    if extras: line += f" ({', '.join(extras)})"
    return line

def send_msg(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": MY_CHAT_ID, "text": text, "parse_mode": "Markdown"})

# --- יצירת הודעת סטטיסטיקה לישראלים ---

def get_israeli_stats_message(player_data, label):
    s = player_data['statistics']
    full_name = f"{player_data['firstName']} {player_data['familyName']}"
    
    if s['minutesCalculated'] == "PT00M00.00S":
        return f"🇮🇱 **{translate_player(full_name)}** טרם שותף ({label})."

    msg = (
        f"🇮🇱 **סיכום ישראלי - {translate_player(full_name)}**:\n"
        f"📌 סטטוס: {label}\n"
        f"⏱️ דקות: {format_minutes(s['minutesCalculated'])}\n"
        f"🏀 נקודות: {s['points']}\n"
        f"💪 ריבאונדים: {s['reboundsTotal']}\n"
        f"🎯 אסיסטים: {s['assists']}\n"
        f"🧤 חטיפות: {s['steals']}\n"
        f"🚫 חסימות: {s['blocks']}\n"
        f"⚠️ איבודים: {s['turnovers']}\n"
        f"📊 מדד פלוס/מינוס: {s['plusMinusPoints']}"
    )
    return msg

# --- פונקציית לוח משחקים ב-8 בבוקר ---

def get_daily_schedule():
    url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
    try:
        response = requests.get(url).json()
        games = response.get('scoreboard', {}).get('games', [])
        if not games:
            return "🏀 אין משחקים מתוכננים להיום."
        
        msg = "🗓️ *בוקר טוב! לוח המשחקים להיום ובלילה הקרוב:*\n\n"
        for game in games:
            home = game['homeTeam']['teamName']
            away = game['awayTeam']['teamName']
            home_h = TEAM_NAMES_HEB.get(home, home)
            away_h = TEAM_NAMES_HEB.get(away, away)
            
            # עיבוד זמן לישראל (מוסיפים 2 שעות ל-UTC)
            dt_utc = datetime.strptime(game['gameEt'], "%Y-%m-%dT%H:%M:%SZ")
            dt_israel = dt_utc + timedelta(hours=2)
            time_str = dt_israel.strftime("%H:%M")
            
            msg += f"⏰ {time_str} | {away_h} 🆚 {home_h}\n"
        
        msg += "\n*צפייה מהנה!* 🏀"
        return msg
    except:
        return "⚠️ תקלה במשיכת לוח המשחקים."
        
# --- פונקציות פורמט הודעות ---

def format_start_game(data):
    away = data['awayTeam']
    home = data['homeTeam']
    away_h = TEAM_NAMES_HEB.get(away['teamName'], away['teamName'])
    home_h = TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])
    
    msg = f"🔥 *המשחק יצא לדרך!* 🔥\n🏟️ {away_h} 🆚 {home_h}\n\n"
    
    for team_key in ['awayTeam', 'homeTeam']:
        team = data[team_key]
        t_heb = TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])
        # שמות חמישייה בדגש
        starters = [f"**{translate_player(p['firstName'] + ' ' + p['familyName'])}**" for p in team['players'] if p['starter'] == "1"]
        msg += f"📍 *{t_heb}*:\n• 🏀 חמישייה: {', '.join(starters)}\n"
        msg += "• ❌ חיסורים: לא דווחו פציעות חדשות\n\n"
    return msg

def format_period_update(data, label):
    away = data['awayTeam']
    home = data['homeTeam']
    away_h = TEAM_NAMES_HEB.get(away['teamName'], away['teamName'])
    home_h = TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])
    
    diff = away['score'] - home['score']
    if diff > 0: leader = f"{away_h} מובילה {away['score']}-{home['score']}"
    elif diff < 0: leader = f"{home_h} מובילה {home['score']}-{away['score']}"
    else: leader = f"שוויון {away['score']}-{home['score']}"

    msg = f"🏀 *{label}: {away_h} 🆚 {home_h}* 🏀\n\n🔹 *{leader}*\n\n"
    
    for team in [away, home]:
        t_heb = TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])
        players = sorted(team['players'], key=lambda x: x['statistics']['points'], reverse=True)
        starters = [p for p in players if p['starter'] == "1"]
        bench = [p for p in players if p['starter'] == "0" and p['statistics']['minutesCalculated'] != "PT00M00.00S"]
        
        msg += f"🔥 *{t_heb}*:\n"
        if len(starters) >= 1: msg += f"• 🔝 קלע מוביל: {get_stat_line(starters[0])}\n"
        if len(starters) >= 2: msg += f"• 🏀 סקורר שני: {get_stat_line(starters[1])}\n"
        if bench: msg += f"• ⚡️ מהספסל: {get_stat_line(bench[0])}\n"
        msg += "\n"
    return msg

def format_overtime_alert(data, ot_count):
    away_h = TEAM_NAMES_HEB.get(data['awayTeam']['teamName'], data['awayTeam']['teamName'])
    home_h = TEAM_NAMES_HEB.get(data['homeTeam']['teamName'], data['homeTeam']['teamName'])
    
    if ot_count == 1:
        # שליפת קלעים מובילים להודעת הדרמה
        p_away = max(data['awayTeam']['players'], key=lambda x: x['statistics']['points'])
        p_home = max(data['homeTeam']['players'], key=lambda x: x['statistics']['points'])
        
        msg = f"⚠️ *דרמה ב-NBA: הולכים להארכה!* ⚠️\n🏟️ {away_h} 🆚 {home_h}\n"
        msg += f"📊 תוצאה בסיום 4 רבעים: {data['awayTeam']['score']}-{data['homeTeam']['score']}\n\n"
        msg += f"📍 מצבת קלעים לקראת המאני טיים:\n"
        msg += f"▫️ **{translate_player(p_away['firstName'] + ' ' + p_away['familyName'])}**: {p_away['statistics']['points']} נק' ({away_h})\n"
        msg += f"▫️ **{translate_player(p_home['firstName'] + ' ' + p_home['familyName'])}**: {p_home['statistics']['points']} נק' ({home_h})\n\n"
        msg += "🔥 *מי ייקח את זה?*"
    else:
        msg = f"😱 *לא נגמר! הארכה {ot_count} (OT{ot_count}) יוצאת לדרך!* 😱\n🔥 הקרב נמשך..."
    return msg

def format_final_summary(data, ot_count):
    away = data['awayTeam']
    home = data['homeTeam']
    away_h = TEAM_NAMES_HEB.get(away['teamName'], away['teamName'])
    home_h = TEAM_NAMES_HEB.get(home['teamName'], home['teamName'])
    ot_suffix = f" (לאחר {ot_count} הארכות)" if ot_count > 0 else ""
    
    msg = f"🏁🏀 *סיום המשחק: {away_h} 🆚 {home_h}* 🏁🏀\n\n"
    msg += f"📊 תוצאה סופית: {away['score']} - {home['score']} {ot_suffix}\n"
    msg += "──────────────────\n\n"
    
    for team in [away, home]:
        t_heb = TEAM_NAMES_HEB.get(team['teamName'], team['teamName'])
        msg += f"📍 *{t_heb} - סטטיסטיקה:*\nחמישייה:\n"
        players = team['players']
        starters = [p for p in players if p['starter'] == "1"]
        bench = sorted([p for p in players if p['starter'] == "0" and p['statistics']['minutesCalculated'] != "PT00M00.00S"], 
                       key=lambda x: x['statistics']['points'], reverse=True)
        
        for p in starters: msg += f"{get_stat_line(p)}\n"
        msg += "\n3 מהספסל:\n"
        for p in bench[:3]: msg += f"{get_stat_line(p)}\n"
        msg += "\n"
    return msg

# --- לוגיקת ניהול המשחקים ---

def monitor_nba():
    sent_states = {} 

    last_schedule_sent_date = ""
    
    while True:
        try:
            now = datetime.now(timezone.utc) + timedelta(hours=2)
            today_date = now.strftime("%Y-%m-%d")
            
            if now.hour == 18 and now.minute == 0 and last_schedule_sent_date != today_date:
                send_msg(get_daily_schedule())
                last_schedule_sent_date = today_date
                
            scoreboard = requests.get("https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json").json()
            games = scoreboard['scoreboard']['games']
            
            for game in games:
                gid = game['gameId']
                status = game['gameStatusText']
                period = game['period']
                
                data_url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
                game_data = requests.get(data_url).json()['game']
                
                state_key = f"{gid}_{status}_{period}"
                
                if state_key not in sent_states:
                    # 1. פתיחת משחק
                    if period == 1 and game['gameStatus'] == 2 and gid not in sent_states:
                        send_msg(format_start_game(game_data))
                        sent_states[gid] = "STARTED"
                    
                    # 2. סיום רבעים רגילים (רבע 1, 2, 3, 4)
                    elif "End" in status or "Half" in status:
                        if period <= 4:
                            label = "מחצית" if "Half" in status else f"סיום רבע {period}"
                            send_msg(format_period_update(game_data, label))
                            
                            # --- תוספת: עדכון ישראלים בכל רבע ---
                            for team_key in ['awayTeam', 'homeTeam']:
                                for p in game_data[team_key]['players']:
                                    if f"{p['firstName']} {p['familyName']}" in ISRAELI_PLAYERS:
                                        send_msg(get_israeli_stats_message(p, label))
                            
                            sent_states[state_key] = True
                            
                            if period == 4 and game_data['awayTeam']['score'] == game_data['homeTeam']['score']:
                                send_msg(format_overtime_alert(game_data, 1))

                    # 3. הארכות (OT)
                    elif period > 4 and "End" in status:
                        ot_num = period - 4
                        label = f"סיום הארכה {ot_num}"
                        send_msg(format_period_update(game_data, label))
                        
                        # --- תוספת: עדכון ישראלים בהארכה ---
                        for team_key in ['awayTeam', 'homeTeam']:
                            for p in game_data[team_key]['players']:
                                if f"{p['firstName']} {p['familyName']}" in ISRAELI_PLAYERS:
                                    send_msg(get_israeli_stats_message(p, label))
                                    
                        sent_states[state_key] = True
                        if game_data['awayTeam']['score'] == game_data['homeTeam']['score']:
                            send_msg(format_overtime_alert(game_data, ot_num + 1))

                    # 4. סיום משחק סופי
                    elif game['gameStatus'] == 3:
                        ot_count = period - 4 if period > 4 else 0
                        send_msg(format_final_summary(game_data, ot_count))
                        
                        label = "סיום משחק"
                        for team_key in ['awayTeam', 'homeTeam']:
                            for p in game_data[team_key]['players']:
                                if f"{p['firstName']} {p['familyName']}" in ISRAELI_PLAYERS:
                                    send_msg(get_israeli_stats_message(p, label))
                        
                        sent_states[state_key] = True
                        
        except Exception as e:
            print(f"Error: {e}")
        
        time.sleep(60)
        print(f"Check completed at {datetime.now()}. Waiting for games...")

if __name__ == "__main__":
    monitor_nba()



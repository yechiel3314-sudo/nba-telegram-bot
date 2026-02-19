import requests
import time
from datetime import datetime, timedelta, timezone
from deep_translator import GoogleTranslator

# --- הגדרות טכניות ---
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event="

translator = GoogleTranslator(source='en', target='iw')
translation_cache = {}
games_state = {}

def tr(text):
    """תרגום עם זיכרון מטמון למניעת עומס"""
    if not text: return ""
    if text in translation_cache: return translation_cache[text]
    try:
        t = translator.translate(text)
        translation_cache[text] = t
        return t
    except: return text

# --- מנוע חילוץ נתונים ---

def get_stat(stat_list, label, labels_map):
    try:
        idx = labels_map.index(label)
        return stat_list[idx]
    except: return "0"

def extract_players_data(team_box):
    athletes = team_box.get("statistics", [{}])[0].get("athletes", [])
    labels = team_box.get("statistics", [{}])[0].get("labels", [])
    parsed = []
    for a in athletes:
        s = a.get("stats", [])
        if not s or len(s) < 5: continue
        parsed.append({
            "name": a["athlete"]["displayName"],
            "starter": a.get("starter", False),
            "pts": int(get_stat(s, "PTS", labels)),
            "reb": int(get_stat(s, "REB", labels)),
            "ast": int(get_stat(s, "AST", labels)),
            "stl": int(get_stat(s, "STL", labels)),
            "blk": int(get_stat(s, "BLK", labels))
        })
    return parsed

def format_p_line(p):
    """עיצוב שורת שחקן נקי"""
    line = f"• *{tr(p['name'])}* ({p['pts']} נק', {p['reb']} ריב', {p['ast']} אס')"
    extras = []
    if p['stl'] > 0: extras.append(f"{p['stl']} חט'")
    if p['blk'] > 0: extras.append(f"{p['blk']} חס'")
    if extras: line += " [" + " ".join(extras) + "]"
    return line

# --- פונקציות הודעות ---

def build_game_msg(title, ev, summary, is_final=False):
    comp = ev["competitions"][0]
    home = next(c for c in comp["competitors"] if c["homeAway"] == "home")
    away = next(c for c in comp["competitors"] if c["homeAway"] == "away")
    
    h_name, a_name = tr(home['team']['displayName']), tr(away['team']['displayName'])
    h_score, a_score = int(home.get("score", 0)), int(away.get("score", 0))

    if h_score > a_score:
        score_status = f"⏺ *{h_name}* {h_score} - {a_score} {a_name}"
        if is_final: score_status = f"🏁 *{h_name}* ניצחה {h_score}-{a_score}"
    elif a_score > h_score:
        score_status = f"⏺ *{a_name}* {a_score} - {h_score} {h_name}"
        if is_final: score_status = f"🏁 *{a_name}* ניצחה {a_score}-{h_score}"
    else:
        score_status = f"⚖ *שוויון* {h_score} - {a_score}"

    clock = ev["status"].get("displayClock", "20:00")
    period = ev["status"].get("period", 1)
    period_text = "חצי 1" if period == 1 else "חצי 2" if period == 2 else f"OT{period-2}"

    msg = f"🏀 *{title}*\n{score_status}\n⏱ `{clock}` ({period_text})\n"
    msg += "─" * 15 + "\n"

    for team_box in summary.get("boxscore", {}).get("players", []):
        t_name = tr(team_box["team"]["displayName"])
        players = extract_players_data(team_box)
        msg += f"▫️ *{t_name}*:\n"
        
        if "פתיחה" in title or "יצא לדרך" in title:
            starters = [p for p in players if p["starter"]]
            msg += "📋 " + ", ".join([tr(p['name']) for p in starters]) if starters else "📋 חמישייה טרם עודכנה"
        elif is_final:
            top_5 = sorted(players, key=lambda x: x["pts"], reverse=True)[:5]
            for p in top_5: msg += f"{format_p_line(p)}\n"
        else:
            starters = sorted([p for p in players if p["starter"]], key=lambda x: x["pts"], reverse=True)[:2]
            bench = sorted([p for p in players if not p["starter"]], key=lambda x: x["pts"], reverse=True)
            for p in starters: msg += f"{format_p_line(p)}\n"
            if bench: msg += f"{format_p_line(bench[0])} (ס)\n"
        msg += "\n"
    return msg

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})

# --- פונקציות תזמון ---

def get_morning_summary():
    try:
        resp = requests.get(SCOREBOARD_URL, timeout=10).json()
        events = resp.get("events", [])
        if not events: return "☕ *בוקר טוב!* לא התקיימו משחקים הלילה."
        msg = "☕ *סיכום תוצאות הלילה (NCAA):*\n\n"
        for ev in events:
            if ev["status"]["type"]["state"] == "post":
                comp = ev["competitions"][0]
                home = comp["competitors"][0]
                away = comp["competitors"][1]
                msg += f"• {tr(away['team']['shortDisplayName'])} {away['score']} - {home['score']} {tr(home['team']['shortDisplayName'])}\n"
        return msg
    except: return None

def get_daily_schedule():
    try:
        resp = requests.get(SCOREBOARD_URL, timeout=10).json()
        events = resp.get("events", [])
        if not events: return "🏀 אין משחקים מתוכננים להיום."
        msg = "🗓️ *לו"ז משחקי המכללות להערב/לילה:*\n\n"
        for ev in events:
            start_time = ev["date"] # פורמט UTC
            dt_utc = datetime.strptime(start_time, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
            dt_israel = dt_utc + timedelta(hours=2)
            time_str = dt_israel.strftime("%H:%M")
            msg += f"⏰ {time_str} | {tr(ev['name'])}\n"
        return msg
    except: return "⚠️ תקלה במשיכת לו"ז."

# --- לוגיקה מרכזית ---

def run_ncaa_monitor():
    last_morning_date = ""
    last_evening_date = ""

    while True:
        try:
            now = datetime.now(timezone.utc) + timedelta(hours=2)
            today = now.strftime("%Y-%m-%d")

            # 1. סיכום בוקר (09:00)
            if now.hour == 9 and now.minute == 0 and last_morning_date != today:
                summary = get_morning_summary()
                if summary: send_telegram(summary)
                last_morning_date = today

            # 2. לו"ז ערב (18:00)
            if now.hour == 18 and now.minute == 0 and last_evening_date != today:
                schedule = get_daily_schedule()
                send_telegram(schedule)
                last_evening_date = today

            # 3. בדיקת משחקים חיים
            resp = requests.get(SCOREBOARD_URL, timeout=15).json()
            for ev in resp.get("events", []):
                gid = ev["id"]
                state = ev["status"]["type"]["state"]
                clock = ev["status"].get("displayClock", "20:00")
                period = ev["status"].get("period", 1)
                
                try: minute = int(clock.split(":")[0])
                except: minute = 20

                if gid not in games_state:
                    games_state[gid] = {"stages": []}
                
                g = games_state[gid]

                # משחק פעיל
                if state == "in":
                    summary = requests.get(SUMMARY_URL + gid, timeout=15).json()
                    
                    # א. פתיחה
                    if "start" not in g["stages"]:
                        title = "המשחק יצא לדרך! 🔥" if period == 1 and minute >= 19 else "עדכון משחק פעיל 🏀"
                        send_telegram(build_game_msg(title, ev, summary))
                        g["stages"].append("start")
                    
                    # ב. תחנות עדכון (10 דק' לסיום חצי 1, מחצית, 10 דק' לסיום חצי 2)
                    if period == 1 and minute <= 10 and "10_p1" not in g["stages"]:
                        send_telegram(build_game_msg("10 דק' לסיום החצי הראשון ⏳", ev, summary))
                        g["stages"].append("10_p1")
                    elif period == 2 and minute >= 19 and "half" not in g["stages"]:
                        send_telegram(build_game_msg("מחצית ☕", ev, summary))
                        g["stages"].append("half")
                    elif period == 2 and minute <= 10 and "10_p2" not in g["stages"]:
                        send_telegram(build_game_msg("🚨 10 דקות לסיום המשחק!", ev, summary))
                        g["stages"].append("10_p2")

                # ג. סיום משחק (חסין לפספוסים)
                elif state == "post" and "final" not in g["stages"]:
                    summary = requests.get(SUMMARY_URL + gid, timeout=15).json()
                    send_telegram(build_game_msg("סיום המשחק - סטטיסטיקה", ev, summary, is_final=True))
                    g["stages"].append("final")

        except Exception as e:
            print(f"Error: {e}")
        
        time.sleep(60)

if __name__ == "__main__":
    print("🚀 NCAA Pro-Monitor is running...")
    run_ncaa_monitor()

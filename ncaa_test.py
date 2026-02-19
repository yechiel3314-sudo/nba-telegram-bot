import requests
import time
from deep_translator import GoogleTranslator

# --- הגדרות ---
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event="

translator = GoogleTranslator(source='en', target='iw')
translation_cache = {}
games_state = {}

def tr(text):
    if not text: return ""
    if text in translation_cache: return translation_cache[text]
    try:
        t = translator.translate(text)
        translation_cache[text] = t
        return t
    except: return text

# --- מנוע חילוץ נתונים חכם ---
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
    """עיצוב שורת שחקן: שם מודגש, נתונים בסיסיים, הגנה בסוגריים"""
    line = f"*{tr(p['name'])}*: {p['pts']} נק' {p['reb']} ריב' {p['ast']} אס'"
    extras = []
    if p['stl'] > 0: extras.append(f"{p['stl']} חט'")
    if p['blk'] > 0: extras.append(f"{p['blk']} חס'")
    if extras:
        line += " (" + " ".join(extras) + ")"
    return line

# --- בניית הודעה ---
def build_game_msg(title, ev, summary, is_final=False):
    comp = ev["competitions"][0]
    home = next(c for c in comp["competitors"] if c["homeAway"] == "home")
    away = next(c for c in comp["competitors"] if c["homeAway"] == "away")
    
    h_name = tr(home['team']['displayName'])
    a_name = tr(away['team']['displayName'])
    h_score = int(home.get("score", 0))
    a_score = int(away.get("score", 0))

    # שורת מובילה
    if h_score > a_score:
        leader_text = f"🔹 *{h_name} מובילה {h_score} - {a_score}*"
        if is_final: leader_text = f"🏁 *{h_name} ניצחה {h_score} - {a_score}*"
    elif a_score > h_score:
        leader_text = f"🔹 *{a_name} מובילה {a_score} - {h_score}*"
        if is_final: leader_text = f"🏁 *{a_name} ניצחה {a_score} - {h_score}*"
    else:
        leader_text = f"🔹 *שוויון {h_score} - {a_score}*"

    clock = ev["status"].get("displayClock", "20:00")
    period = ev["status"].get("period", 1)
    period_text = "חצי 1" if period == 1 else "חצי 2" if period == 2 else f"הארכה {period-2}"

    msg = f"🏀 *{title}*\n"
    msg += f"*{a_name}* 🆚 *{h_name}*\n\n"
    msg += f"{leader_text}\n"
    msg += f"⏱️ זמן: {clock} ({period_text})\n"
    msg += "───────────────────\n"

    for team_box in summary.get("boxscore", {}).get("players", []):
        t_name = tr(team_box["team"]["displayName"])
        players = extract_players_data(team_box)
        msg += f"🔥 *{t_name}*:\n"
        
        if "יצא לדרך" in title:
            starters = [p for p in players if p["starter"]]
            if starters:
                msg += "📋 *חמישייה:* " + ", ".join([tr(p['name']) for p in starters]) + "\n"
            else:
                msg += "📋 *חמישייה:* אין כרגע עדכון לגבי החמישייה\n"
        elif is_final:
            top_5 = sorted(players, key=lambda x: x["pts"], reverse=True)[:5]
            for p in top_5: msg += f"• {format_p_line(p)}\n"
        else:
            starters = sorted([p for p in players if p["starter"]], key=lambda x: x["pts"], reverse=True)[:2]
            bench = sorted([p for p in players if not p["starter"]], key=lambda x: x["pts"], reverse=True)
            for p in starters: msg += f"• 🔝 {format_p_line(p)}\n"
            if bench: msg += f"• ⚡ ספסל: {format_p_line(bench[0])}\n"
        msg += "\n"
    return msg

# --- לוגיקה ---
def run_bot():
    try:
        resp = requests.get(SCOREBOARD_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15).json()
        for ev in resp.get("events", []):
            gid = ev["id"]
            state = ev["status"]["type"]["state"]
            clock = ev["status"].get("displayClock", "20:00")
            period = ev["status"].get("period", 1)
            try: minute = int(clock.split(":")[0])
            except: minute = 20

            if gid not in games_state:
                already_in = (state == "in" and (period > 1 or minute < 19))
                games_state[gid] = {"mid": None, "stages": [], "start_handled": already_in}

            g = games_state[gid]

            if state == "in":
                summary = requests.get(SUMMARY_URL + gid, timeout=15).json()
                
                # 1. יצא לדרך
                if not g["start_handled"] and period == 1 and minute >= 19:
                    msg = build_game_msg("המשחק יצא לדרך! 🔥", ev, summary)
                    res = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                                        json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}).json()
                    if res.get("ok"): g["mid"] = res["result"]["message_id"]
                    g["start_handled"] = True

                # 2. 10 דקות חצי 1
                if period == 1 and minute <= 10 and "10_p1" not in g["stages"] and g["mid"]:
                    msg = build_game_msg("10 דקות לסיום החצי הראשון ⏳", ev, summary)
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/editMessageText", 
                                  json={"chat_id": CHAT_ID, "message_id": g["mid"], "text": msg, "parse_mode": "Markdown"})
                    g["stages"].append("10_p1")

                # 3. מחצית
                if period == 2 and minute >= 19 and "half" not in g["stages"] and g["mid"]:
                    msg = build_game_msg("מחצית ☕", ev, summary)
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/editMessageText", 
                                  json={"chat_id": CHAT_ID, "message_id": g["mid"], "text": msg, "parse_mode": "Markdown"})
                    g["stages"].append("half")

                # 4. 10 דקות לסיום
                if period == 2 and minute <= 10 and "10_p2" not in g["stages"] and g["mid"]:
                    msg = build_game_msg("🚨 10 דקות לסיום המשחק!", ev, summary)
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/editMessageText", 
                                  json={"chat_id": CHAT_ID, "message_id": g["mid"], "text": msg, "parse_mode": "Markdown"})
                    g["stages"].append("10_p2")

            elif state == "post" and "final" not in g["stages"] and g["mid"]:
                summary = requests.get(SUMMARY_URL + gid, timeout=15).json()
                msg = build_game_msg("🏁 סיום המשחק - סטטיסטיקה סופית", ev, summary, is_final=True)
                requests.post(f"https://api.telegram.org/bot{TOKEN}/editMessageText", 
                              json={"chat_id": CHAT_ID, "message_id": g["mid"], "text": msg, "parse_mode": "Markdown"})
                g["stages"].append("final")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    while True:
        run_bot()
        time.sleep(25)

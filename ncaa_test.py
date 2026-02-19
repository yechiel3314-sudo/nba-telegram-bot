import requests
import time
from deep_translator import GoogleTranslator

# --- CONFIG ---
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event="

translator = GoogleTranslator(source='en', target='iw')
games_state = {}

def tr(text):
    if not text: return ""
    try: return translator.translate(text)
    except: return text

# --- מנוע חילוץ נתונים מדויק ---
def get_stat(stat_list, label, labels_map):
    """מוצא נתון לפי השם שלו כדי להבטיח 100% דיוק"""
    try:
        idx = labels_map.index(label)
        return stat_list[idx]
    except:
        return "0"

def extract_players_data(team_box):
    """מחלץ שחקנים עם זיהוי דינמי של עמודות הסטטיסטיקה"""
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

# --- בניית הודעות ---
def build_game_msg(title, ev, summary):
    comp = ev["competitions"][0]
    home = next(c for c in comp["competitors"] if c["homeAway"] == "home")
    away = next(c for c in comp["competitors"] if c["homeAway"] == "away")
    
    msg = f"🏀 *{title}:* {tr(away['team']['displayName'])} 🆚 {tr(home['team']['displayName'])} 🏀\n"
    msg += f"💰 תוצאה: *{away['score']} - {home['score']}*\n"
    msg += f"⏱️ זמן: {ev['status']['displayClock']} ({tr(ev['status']['type']['detail'])})\n"
    msg += "───────────────────\n"

    for team_box in summary.get("boxscore", {}).get("players", []):
        t_name = tr(team_box["team"]["displayName"])
        players = extract_players_data(team_box)
        
        starters = [p for p in players if p["starter"]]
        bench = sorted([p for p in players if not p["starter"]], key=lambda x: x["pts"], reverse=True)

        msg += f"🔥 *{t_name}*:\n"
        if "יצא לדרך" in title: # הצגת חמישיות מלאות רק בהתחלה
            msg += "📋 *חמישייה:* " + ", ".join([tr(p['name']) for p in starters]) + "\n"
        else:
            # 2 מובילים מהחמישייה + 1 ספסל
            top_starters = sorted(starters, key=lambda x: x["pts"], reverse=True)[:2]
            for p in top_starters:
                msg += f"• 🔝 {tr(p['name'])}: {p['pts']}נ', {p['reb']}ר', {p['ast']}א' ({p['stl']}ח', {p['blk']}ח)\n"
            if bench:
                p = bench[0]
                msg += f"• ⚡ ספסל: {tr(p['name'])}: {p['pts']}נ', {p['reb']}ר', {p['ast']}א'\n"
        msg += "\n"
    return msg

# --- לוגיקה ראשית ---
def run_bot():
    try:
        resp = requests.get(SCOREBOARD_URL, timeout=10).json()
        for ev in resp.get("events", []):
            gid = ev["id"]
            state = ev["status"]["type"]["state"]
            
            if gid not in games_state:
                games_state[gid] = {"mid": None, "stages": []}

            # משחק בשידור חי
            if state == "in":
                summary_resp = requests.get(SUMMARY_URL + gid, timeout=10).json()
                clock = ev["status"]["displayClock"]
                period = ev["status"]["period"]
                
                # איתור שלב לעדכון (תחילת משחק / 10 דקות / מחצית)
                current_stage = f"{period}_{clock.split(':')[0]}"
                
                if not games_state[gid]["mid"]: # פתיחת משחק
                    msg = build_game_msg("המשחק יצא לדרך! 🔥", ev, summary_resp)
                    res = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                                        json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}).json()
                    if res.get("ok"): games_state[gid]["mid"] = res["result"]["message_id"]

                elif "10" in clock and current_stage not in games_state[gid]["stages"]: # עדכון 10 דקות
                    games_state[gid]["stages"].append(current_stage)
                    msg = build_game_msg("עדכון משחק (10 דקות)", ev, summary_resp)
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/editMessageText", 
                                  json={"chat_id": CHAT_ID, "message_id": games_state[gid]["mid"], "text": msg, "parse_mode": "Markdown"})

            elif state == "post" and "final" not in games_state[gid]["stages"]: # סיום
                summary_resp = requests.get(SUMMARY_URL + gid, timeout=10).json()
                msg = build_game_msg("🏁 סיום המשחק", ev, summary_resp)
                requests.post(f"https://api.telegram.org/bot{TOKEN}/editMessageText", 
                              json={"chat_id": CHAT_ID, "message_id": games_state[gid]["mid"], "text": msg, "parse_mode": "Markdown"})
                games_state[gid]["stages"].append("final")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    while True:
        run_bot()
        time.sleep(30)

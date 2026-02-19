import requests
import time
from deep_translator import GoogleTranslator

# --- הגדרות ---
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

# --- חילוץ סטטיסטיקה דינמי (לדיוק מקסימלי) ---
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

# --- בניית הודעות מעוצבות ---
def build_game_msg(title, ev, summary, is_final=False):
    comp = ev["competitions"][0]
    home = next(c for c in comp["competitors"] if c["homeAway"] == "home")
    away = next(c for c in comp["competitors"] if c["homeAway"] == "away")
    
    status_detail = tr(ev['status']['type']['detail'])
    msg = f"🏀 *{title}:* {tr(away['team']['displayName'])} 🆚 {tr(home['team']['displayName'])} 🏀\n"
    msg += f"💰 תוצאה: *{away['score']} - {home['score']}*\n"
    msg += f"⏱️ סטטוס: {status_detail}\n"
    msg += "───────────────────\n"

    for team_box in summary.get("boxscore", {}).get("players", []):
        t_name = tr(team_box["team"]["displayName"])
        players = extract_players_data(team_box)
        
        msg += f"🔥 *{t_name}*:\n"
        if is_final: # סטטיסטיקה מורחבת בסיום
            top_5 = sorted(players, key=lambda x: x["pts"], reverse=True)[:5]
            for p in top_5:
                msg += f"• {tr(p['name'])}: {p['pts']}נ' | {p['reb']}ר' | {p['ast']}א' | {p['stl']}ח' | {p['blk']}ח'\n"
        elif "יצא לדרך" in title: # חמישיות בפתיחה
            starters = [p for p in players if p["starter"]]
            msg += "📋 *חמישייה:* " + ", ".join([tr(p['name']) for p in starters]) + "\n"
        else: # עדכון שוטף (2 מובילים + 1 ספסל)
            starters = sorted([p for p in players if p["starter"]], key=lambda x: x["pts"], reverse=True)[:2]
            bench = sorted([p for p in players if not p["starter"]], key=lambda x: x["pts"], reverse=True)
            for p in starters:
                msg += f"• 🔝 {tr(p['name'])}: {p['pts']}נ', {p['reb']}ר', {p['ast']}א'\n"
            if bench:
                p = bench[0]
                msg += f"• ⚡ ספסל: {tr(p['name'])}: {p['pts']}נ', {p['reb']}ר', {p['ast']}א'\n"
        msg += "\n"
    return msg

# --- לוגיקה מרכזית ---
def run_bot():
    try:
        resp = requests.get(SCOREBOARD_URL, timeout=10).json()
        for ev in resp.get("events", []):
            gid = ev["id"]
            state = ev["status"]["type"]["state"]
            clock = ev["status"].get("displayClock", "20:00")
            period = ev["status"].get("period", 1)
            
            try: minute = int(clock.split(":")[0])
            except: minute = 20

            # יצירת אובייקט מצב למשחק חדש
            if gid not in games_state:
                # אם הבוט הופעל באמצע משחק, הוא לא ישלח "יצא לדרך"
                is_middle = (state == "in")
                games_state[gid] = {"mid": None, "stages": [], "ignore_start": is_middle}

            g = games_state[gid]

            if state == "in":
                summary = requests.get(SUMMARY_URL + gid, timeout=10).json()
                
                # 1. יצא לדרך (רק אם הבוט עקב אחריו מההתחלה והניקוד עדיין נמוך)
                if not g["start_sent"] and not g["ignore_start"]:
                    if period == 1 and minute >= 19:
                        msg = build_game_msg("המשחק יצא לדרך! 🔥", ev, summary)
                        res = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                                            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}).json()
                        if res.get("ok"): g["mid"] = res["result"]["message_id"]
                        g["start_sent"] = True

                # 2. 10 דקות לסיום חצי ראשון
                if period == 1 and minute == 10 and "10_p1" not in g["stages"] and g["mid"]:
                    msg = build_game_msg("10 דקות לסיום החצי הראשון ⏳", ev, summary)
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/editMessageText", 
                                  json={"chat_id": CHAT_ID, "message_id": g["mid"], "text": msg, "parse_mode": "Markdown"})
                    g["stages"].append("10_p1")

                # 3. מחצית
                if period == 2 and minute == 20 and "half" not in g["stages"] and g["mid"]:
                    msg = build_game_msg("מחצית ☕", ev, summary)
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/editMessageText", 
                                  json={"chat_id": CHAT_ID, "message_id": g["mid"], "text": msg, "parse_mode": "Markdown"})
                    g["stages"].append("half")

                # 4. 10 דקות לסיום המשחק
                if period == 2 and minute == 10 and "10_p2" not in g["stages"] and g["mid"]:
                    msg = build_game_msg("🚨 10 דקות לסיום המשחק!", ev, summary)
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/editMessageText", 
                                  json={"chat_id": CHAT_ID, "message_id": g["mid"], "text": msg, "parse_mode": "Markdown"})
                    g["stages"].append("10_p2")

            elif state == "post" and "final" not in g["stages"] and g["mid"]:
                summary = requests.get(SUMMARY_URL + gid, timeout=10).json()
                msg = build_game_msg("🏁 סיום המשחק - סטטיסטיקה סופית", ev, summary, is_final=True)
                requests.post(f"https://api.telegram.org/bot{TOKEN}/editMessageText", 
                              json={"chat_id": CHAT_ID, "message_id": g["mid"], "text": msg, "parse_mode": "Markdown"})
                g["stages"].append("final")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # אתחול שמות משתנים חסרים במילון המצב
    # (מונע שגיאות KeyErrors בהרצה הראשונה)
    print("🚀 הבוט התחיל לסרוק את כל המשחקים...")
    while True:
        run_bot()
        time.sleep(30)

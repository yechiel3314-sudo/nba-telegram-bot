import requests
import time
from deep_translator import GoogleTranslator

# =====================================
# CONFIG
# =====================================
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event="

translator = GoogleTranslator(source='en', target='iw')
translation_cache = {}
games_state = {}

def tr(text):
    if not text or text == "TBD": return text
    if text in translation_cache: return translation_cache[text]
    try:
        t = translator.translate(text)
        translation_cache[text] = t
        return t
    except: return text

# =====================================
# STATS ENGINE (2 Starters + 1 Bench)
# =====================================
def get_team_stats(team_box):
    players = team_box.get("statistics", [{}])[0].get("athletes", [])
    all_players = []
    
    for p in players:
        s = p.get("stats", [])
        if len(s) >= 13:
            all_players.append({
                "name": p["athlete"]["displayName"],
                "pts": int(s[12]),
                "reb": int(s[6]),
                "ast": int(s[7]),
                "stl": int(s[8]) if len(s) > 8 else 0,
                "blk": int(s[9]) if len(s) > 9 else 0,
                "starter": p.get("starter", False)
            })
    
    # מיון לפי נקודות
    starters = sorted([p for p in all_players if p["starter"]], key=lambda x: x["pts"], reverse=True)
    bench = sorted([p for p in all_players if not p["starter"]], key=lambda x: x["pts"], reverse=True)
    
    return {
        "top_starters": starters[:2],
        "top_bench": bench[0] if bench else None
    }

def format_p(p):
    if not p: return "אין נתונים"
    line = f"{tr(p['name'])}: {p['pts']} נק', {p['reb']} ריב', {p['ast']} אס'"
    extras = []
    if p['stl'] > 0: extras.append(f"{p['stl']} חט'")
    if p['blk'] > 0: extras.append(f"{p['blk']} חס'")
    if extras: line += " (" + " | ".join(extras) + ")"
    return line

# =====================================
# MESSAGE BUILDER
# =====================================
def build_msg(title, ev, summary):
    comp = ev["competitions"][0]
    home = next(c for c in comp["competitors"] if c["homeAway"] == "home")
    away = next(c for c in comp["competitors"] if c["homeAway"] == "away")
    
    clock = ev["status"].get("displayClock", "20:00")
    period = ev["status"].get("period", 1)
    period_text = "חצי 1" if period == 1 else "חצי 2" if period == 2 else f"הארכה {period-2}"
    
    msg = f"🏀 *{title}:* {tr(away['team']['displayName'])} 🆚 {tr(home['team']['displayName'])} 🏀\n"
    msg += f"🔹 תוצאה: *{away['score']} - {home['score']}*\n"
    msg += f"⏱️ זמן: {clock} ({period_text})\n\n"

    for team_box in summary.get("boxscore", {}).get("players", []):
        t_name = tr(team_box["team"]["displayName"])
        stats = get_team_stats(team_box)

        msg += f"🔥 *{t_name}:*\n"
        if stats["top_starters"]:
            msg += f"• 🔝 קלע מוביל: ▫️ {format_p(stats['top_starters'][0])}\n"
            if len(stats["top_starters"]) > 1:
                msg += f"• 🏀 סקורר שני: ▫️ {format_p(stats['top_starters'][1])}\n"
        if stats["top_bench"]:
            msg += f"• ⚡ מהספסל: ▫️ {format_p(stats['top_bench'])}\n"
        msg += "\n"
    
    return msg

# =====================================
# MAIN SCANNER
# =====================================
def check_all_games():
    try:
        data = requests.get(SCOREBOARD_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10).json()
    except: return

    for ev in data.get("events", []):
        gid = ev["id"]
        state = ev["status"]["type"]["state"]
        
        if gid not in games_state:
            games_state[gid] = {"mid": None, "start": False, "m10": False, "half": False, "m30": False, "final": False}
        
        g = games_state[gid]
        clock = ev["status"].get("displayClock", "20:00")
        period = ev["status"].get("period", 1)
        try: minute = int(clock.split(":")[0])
        except: minute = 20

        # משחקים במצב LIVE
        if state == "in":
            try:
                summary = requests.get(SUMMARY_URL + gid, timeout=10).json()
            except: continue
            
            # פתיחה (הודעה חדשה)
            if not g["start"]:
                msg = build_msg("המשחק יצא לדרך", ev, summary)
                res = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                                    json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}).json()
                if res.get("ok"): 
                    g["mid"] = res["result"]["message_id"]
                    g["start"] = True

            # עדכוני עריכה (הודעה אחת שמתעדכנת)
            update_needed = False
            title = ""

            if period == 1 and minute <= 10 and not g["m10"]:
                title = "עברו 10 דקות משחק"; g["m10"] = True; update_needed = True
            elif period == 2 and minute == 20 and not g["half"]:
                title = "מחצית"; g["half"] = True; update_needed = True
            elif period == 2 and minute <= 10 and not g["m30"]:
                title = "10 דקות לסיום"; g["m30"] = True; update_needed = True

            if update_needed and g["mid"]:
                new_text = build_msg(title, ev, summary)
                requests.post(f"https://api.telegram.org/bot{TOKEN}/editMessageText", 
                              json={"chat_id": CHAT_ID, "message_id": g["mid"], "text": new_text, "parse_mode": "Markdown"})

        # סיום משחק
        elif state == "post" and not g["final"] and g.get("mid"):
            try:
                summary = requests.get(SUMMARY_URL + gid, timeout=10).json()
                final_msg = build_msg("סיום המשחק", ev, summary)
                requests.post(f"https://api.telegram.org/bot{TOKEN}/editMessageText", 
                              json={"chat_id": CHAT_ID, "message_id": g["mid"], "text": final_msg, "parse_mode": "Markdown"})
                g["final"] = True
            except: pass

if __name__ == "__main__":
    print("🚀 NCAA LIVE BOT - MULTI GAME EDITION")
    while True:
        check_all_games()
        time.sleep(20)

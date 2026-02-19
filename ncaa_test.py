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
    if not text: return ""
    if text in translation_cache: return translation_cache[text]
    try:
        t = translator.translate(text)
        translation_cache[text] = t
        return t
    except: return text

def send_telegram(method, data):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/{method}"
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"❌ Telegram Error ({method}): {e}")

# =====================================
# STATS ENGINE
# =====================================
def extract_stats(team):
    players = team.get("statistics", [{}])[0].get("athletes", [])
    result = []
    for p in players:
        s = p.get("stats", [])
        if len(s) >= 13:
            try:
                # פורמט מכללות: 12=PTS, 6=REB, 7=AST, 8=STL, 9=BLK
                p_stats = {
                    "name": p["athlete"]["displayName"],
                    "pts": int(s[12]),
                    "reb": int(s[6]),
                    "ast": int(s[7]),
                    "stl": int(s[8]) if len(s) > 8 else 0,
                    "blk": int(s[9]) if len(s) > 9 else 0,
                    "starter": p.get("starter", False)
                }
                result.append(p_stats)
            except: continue
    result.sort(key=lambda x: x["pts"], reverse=True)
    return result

def format_p_line(p):
    """בונה שורת סטטיסטיקה מעוצבת לשחקן"""
    line = f"{tr(p['name'])}: {p['pts']} נק', {p['reb']} ריב', {p['ast']} אס'"
    extras = []
    if p['stl'] > 0: extras.append(f"{p['stl']} חט'")
    if p['blk'] > 0: extras.append(f"{p['blk']} חס'")
    if extras:
        line += " (" + " | ".join(extras) + ")"
    return line

# =====================================
# MESSAGE BUILDER
# =====================================
def build_msg(title, ev, summary):
    comp = ev["competitions"][0]
    home = next(c for c in comp["competitors"] if c["homeAway"] == "home")
    away = next(c for c in comp["competitors"] if c["homeAway"] == "away")
    
    clock = ev["status"].get("displayClock", "0:00")
    period = ev["status"].get("period", 1)
    # תרגום חצי/רבע
    period_text = "חצי 1" if period == 1 else "חצי 2" if period == 2 else f"הארכה {period-2}"
    
    msg = f"🏀 *{title}*\n"
    msg += f"🏟️ {tr(away['team']['displayName'])} *{away['score']} - {home['score']}* {tr(home['team']['displayName'])}\n"
    msg += f"⏱️ זמן: {clock} ({period_text})\n"
    msg += "───────────────────\n"

    for team_box in summary.get("boxscore", {}).get("players", []):
        t_name = tr(team_box["team"]["displayName"])
        players = extract_stats(team_box)
        if not players: continue
        
        top = players[0]
        bench = next((p for p in players if not p["starter"]), None)

        msg += f"🔥 *{t_name}:*\n"
        msg += f"• 🔝 מוביל: {format_p_line(top)}\n"
        if bench:
            msg += f"• ⚡ מהספסל: {format_p_line(bench)}\n"
        msg += "\n"
    
    return msg

# =====================================
# MAIN SCANNER
# =====================================
def check_all_games():
    data = requests.get(SCOREBOARD_URL, headers={'User-Agent': 'Mozilla/5.0'}).json()
    events = data.get("events", [])
    print(f"🔄 סורק {len(events)} משחקים...")

    for ev in events:
        gid = ev["id"]
        state = ev["status"]["type"]["state"]
        
        if gid not in games_state:
            games_state[gid] = {"mid": None, "start": False, "m10": False, "half": False, "m30": False, "final": False}
        
        g = games_state[gid]
        clock = ev["status"].get("displayClock", "20:00")
        period = ev["status"].get("period", 1)
        try: minute = int(clock.split(":")[0])
        except: minute = 20

        # משחק פעיל (LIVE)
        if state == "in":
            summary = requests.get(SUMMARY_URL + gid).json()
            
            # 1. יצא לדרך
            if not g["start"]:
                msg = build_msg("המשחק יצא לדרך! 🔥", ev, summary)
                url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
                r = requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}).json()
                if r.get("ok"): 
                    g["mid"] = r["result"]["message_id"]
                    g["start"] = True

            # 2. עדכון 10 דקות (חצי ראשון)
            if period == 1 and minute <= 10 and not g["m10"]:
                edit_data = {"chat_id": CHAT_ID, "message_id": g["mid"], "text": build_msg("עדכון: 10 דקות לסיום החצי הראשון ⏳", ev, summary), "parse_mode": "Markdown"}
                send_telegram("editMessageText", edit_data)
                g["m10"] = True

            # 3. מחצית
            if period == 2 and minute == 20 and not g["half"]:
                edit_data = {"chat_id": CHAT_ID, "message_id": g["mid"], "text": build_msg("מחצית ☕", ev, summary), "parse_mode": "Markdown"}
                send_telegram("editMessageText", edit_data)
                g["half"] = True

            # 4. עדכון 10 דקות לסיום המשחק (חצי שני)
            if period == 2 and minute <= 10 and not g["m30"]:
                edit_data = {"chat_id": CHAT_ID, "message_id": g["mid"], "text": build_msg("מאני טיים: 10 דקות לסיום! 🚨", ev, summary), "parse_mode": "Markdown"}
                send_telegram("editMessageText", edit_data)
                g["m30"] = True

        # סיום משחק
        elif state == "post" and not g["final"]:
            summary = requests.get(SUMMARY_URL + gid).json()
            edit_data = {"chat_id": CHAT_ID, "message_id": g["mid"], "text": build_msg("🏁 סיום המשחק", ev, summary), "parse_mode": "Markdown"}
            send_telegram("editMessageText", edit_data)
            g["final"] = True

if __name__ == "__main__":
    while True:
        try:
            check_all_games()
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(30)

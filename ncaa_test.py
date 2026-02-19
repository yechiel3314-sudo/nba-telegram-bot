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
    """פונקציית תרגום עם שמירה בזיכרון למניעת עומס"""
    if not text: 
        return ""
    if text in translation_cache: 
        return translation_cache[text]
    try:
        t = translator.translate(text)
        translation_cache[text] = t
        return t
    except: 
        return text

# --- מנוע חילוץ נתונים חכם ---
def get_stat(stat_list, label, labels_map):
    """חילוץ נתון ספציפי לפי תווית מה-API של ESPN"""
    try:
        idx = labels_map.index(label)
        return stat_list[idx]
    except: 
        return "0"

def extract_players_data(team_box):
    """עיבוד נתוני שחקנים מהבוקס-סקור"""
    athletes = team_box.get("statistics", [{}])[0].get("athletes", [])
    labels = team_box.get("statistics", [{}])[0].get("labels", [])
    parsed = []
    
    for a in athletes:
        s = a.get("stats", [])
        if not s or len(s) < 5: 
            continue
            
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
    if p['stl'] > 0: 
        extras.append(f"{p['stl']} חט'")
    if p['blk'] > 0: 
        extras.append(f"{p['blk']} חס'")
    if extras:
        line += " (" + " ".join(extras) + ")"
    return line

# --- בניית הודעה ---
def build_game_msg(title, ev, summary, is_final=False):
    """יצירת גוף ההודעה המעוצב לטלגרם"""
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
        if is_final: 
            leader_text = f"🏁 *{h_name} ניצחה {h_score} - {a_score}*"
    elif a_score > h_score:
        leader_text = f"🔹 *{a_name} מובילה {a_score} - {h_score}*"
        if is_final: 
            leader_text = f"🏁 *{a_name} ניצחה {a_score} - {h_score}*"
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
        
        if "יצא לדרך" in title or "עדכון משחק" in title:
            starters = [p for p in players if p["starter"]]
            if starters:
                msg += "📋 *חמישייה:* " + ", ".join([tr(p['name']) for p in starters]) + "\n"
            else:
                msg += "📋 *חמישייה:* אין כרגע עדכון לגבי החמישייה\n"
        elif is_final:
            top_5 = sorted(players, key=lambda x: x["pts"], reverse=True)[:5]
            for p in top_5: 
                msg += f"• {format_p_line(p)}\n"
        else:
            starters = sorted([p for p in players if p["starter"]], key=lambda x: x["pts"], reverse=True)[:2]
            bench = sorted([p for p in players if not p["starter"]], key=lambda x: x["pts"], reverse=True)
            for p in starters: 
                msg += f"• 🔝 {format_p_line(p)}\n"
            if bench: 
                msg += f"• ⚡ ספסל: {format_p_line(bench[0])}\n"
        msg += "\n"
    return msg

# --- לוגיקה מרכזית ---
def run_bot():
    """הפונקציה שסורקת את המשחקים ומבצעת את השליחה/עריכה"""
    try:
        # שליחת בקשה ל-Scoreboard לקבלת כל המשחקים
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(SCOREBOARD_URL, headers=headers, timeout=15).json()
        events = resp.get("events", [])
        
        for ev in events:
            gid = ev["id"]
            state = ev["status"]["type"]["state"]
            clock = ev["status"].get("displayClock", "20:00")
            period = ev["status"].get("period", 1)
            
            # חילוץ דקות מהשעון
            try:
                minute = int(clock.split(":")[0])
            except:
                minute = 20

            # יצירת מצב למשחק חדש בזיכרון
            if gid not in games_state:
                games_state[gid] = {"mid": None, "stages": []}

            g = games_state[gid]

            # טיפול במשחקים פעילים (Live)
            if state == "in":
                summary_resp = requests.get(SUMMARY_URL + gid, headers=headers, timeout=15).json()
                
                # א. שליחת הודעה ראשונית (אם עוד לא נשלחה)
                if not g["mid"]:
                    title = "המשחק יצא לדרך! 🔥" if period == 1 and minute >= 19 else "עדכון משחק פעיל 🏀"
                    msg_text = build_game_msg(title, summary_resp.get("event", ev), summary_resp)
                    
                    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
                    payload = {"chat_id": CHAT_ID, "text": msg_text, "parse_mode": "Markdown"}
                    res = requests.post(url, json=payload).json()
                    
                    if res.get("ok"):
                        g["mid"] = res["result"]["message_id"]

                # ב. עדכון: 10 דקות לסיום חצי 1
                if period == 1 and minute <= 10 and "10_p1" not in g["stages"] and g["mid"]:
                    msg_text = build_game_msg("10 דקות לסיום החצי הראשון ⏳", summary_resp.get("event", ev), summary_resp)
                    url = f"https://api.telegram.org/bot{TOKEN}/editMessageText"
                    payload = {"chat_id": CHAT_ID, "message_id": g["mid"], "text": msg_text, "parse_mode": "Markdown"}
                    requests.post(url, json=payload)
                    g["stages"].append("10_p1")

                # ג. עדכון: מחצית
                if period == 2 and minute >= 19 and "half" not in g["stages"] and g["mid"]:
                    msg_text = build_game_msg("מחצית ☕", summary_resp.get("event", ev), summary_resp)
                    url = f"https://api.telegram.org/bot{TOKEN}/editMessageText"
                    payload = {"chat_id": CHAT_ID, "message_id": g["mid"], "text": msg_text, "parse_mode": "Markdown"}
                    requests.post(url, json=payload)
                    g["stages"].append("half")

                # ד. עדכון: 10 דקות לסיום המשחק
                if period == 2 and minute <= 10 and "10_p2" not in g["stages"] and g["mid"]:
                    msg_text = build_game_msg("🚨 10 דקות לסיום המשחק!", summary_resp.get("event", ev), summary_resp)
                    url = f"https://api.telegram.org/bot{TOKEN}/editMessageText"
                    payload = {"chat_id": CHAT_ID, "message_id": g["mid"], "text": msg_text, "parse_mode": "Markdown"}
                    requests.post(url, json=payload)
                    g["stages"].append("10_p2")

            # טיפול בסיום משחק (Final)
            elif state == "post" and "final" not in g["stages"] and g.get("mid"):
                final_summary = requests.get(SUMMARY_URL + gid, headers=headers, timeout=15).json()
                msg_text = build_game_msg("🏁 סיום המשחק - סטטיסטיקה סופית", final_summary.get("event", ev), final_summary, is_final=True)
                
                url = f"https://api.telegram.org/bot{TOKEN}/editMessageText"
                payload = {"chat_id": CHAT_ID, "message_id": g["mid"], "text": msg_text, "parse_mode": "Markdown"}
                requests.post(url, json=payload)
                g["stages"].append("final")

    except Exception as e:
        print(f"Error in run_bot: {e}")

# --- נקודת כניסה ---
if __name__ == "__main__":
    print("🚀 NCAA Live Bot is starting...")
    # הודעת בדיקה ראשונית לוודא שהבוט מחובר
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                      json={"chat_id": CHAT_ID, "text": "✅ הבוט הופעל בהצלחה ומתחיל בסריקה..."})
    except:
        print("Could not send startup message.")

    while True:
        run_bot()
        time.sleep(30) # המתנה של 30 שניות בין סריקות

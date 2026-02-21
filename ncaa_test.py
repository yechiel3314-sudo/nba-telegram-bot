import requests
import time
from datetime import datetime, timedelta
import pytz
from deep_translator import GoogleTranslator

# ==========================================
# --- הגדרות טכניות ---
# ==========================================
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

NBA_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
NCAA_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
GLEAGUE_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba-ght/scoreboard"

translator = GoogleTranslator(source='en', target='iw')
RTL_MARK = "\u200f"
injury_watch_list = {}

PLAYERS = {
    "NBA": {
        "Deni Avdija": ["דני אבדיה", "Trail Blazers", "פורטלנד"],
        "Danny Wolf": ["דני וולף", "Michigan", "מישיגן"],
        "Ben Saraf": ["בן שרף", "Nets", "ברוקלין"]
    },
    "GLEAGUE": {
        "Ben Saraf": ["בן שרף", "Long Island", "לונג איילנד"]
    },
    "NCAA": {
        "Danny Wolf": ["דני וולף", "Michigan", "מישיגן"],
        "Emanuel Sharp": ["עמנואל שארפ", "Houston", "יוסטון"],
        "Yoav Berman": ["יואב ברמן", "Queens", "קווינס"],
        "Ofri Naveh": ["עופרי נווה", "Oral Roberts", "אורל רוברטס"],
        "Eytan Burg": ["איתן בורג", "Tennessee", "טנסי"],
        "Omer Mayer": ["עומר מאייר", "Purdue", "פורדו"],
        "Noam Dovrat": ["נועם דוברת", "Miami", "מיאמי"],
        "Or Ashkenazi": ["אור אשכנזי", "Lipscomb", "ליפסקומב"],
        "Alon Michaeli": ["אלון מיכאלי", "Colorado", "קולורדו"],
        "Yonatan Levi": ["יונתן לוי", "Pepperdine", "פפרדיין"],
        "Yuval Levin": ["יובל לוין", "Fort Wayne", "פרדו פורט וויין"],
        "Omer Hamama": ["עומר חממה", "Kent State", "קנט סטייט"],
        "Or Paran": ["אור פארן", "Mercyhurst", "מרסיהרסט"],
        "Daniel Gueta": ["דניאל גואטה", "Oklahoma State", "אוקלהומה סטייט"],
        "Erez Foren": ["ארז פורן", "Northern Arizona", "צפון אריזונה"],
        "Shon Abaev": ["שון אבייב", "Cincinnati", "סינסינטי"]
    }
}

def tr(text):
    try:
        t = translator.translate(text)
        corrections = {"שבילים בלייזרים": "פורטלנד", "רשתות": "ברוקלין", "לוחמים": "גולדן סטייט", "בוכנות": "דטרויט", "חום": "מיאמי"}
        for eng, heb in corrections.items(): t = t.replace(eng, heb)
        return t
    except: return text

def send_telegram(text):
    if not text or len(text) < 5: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def get_injury_status(ev, p_en):
    try:
        for comp in ev.get("competitions", []):
            for team in comp.get("competitors", []):
                for injury in team.get("injuries", []):
                    if p_en.lower() in injury.get("displayName", "").lower():
                        return injury.get("status", "").upper()
    except: pass
    return "ACTIVE"

# --- הודעה 1 | 18:34 | לו"ז NBA כללי ---
def msg_1_nba_full_schedule():
    now_isr = datetime.now(pytz.timezone('Asia/Jerusalem'))
    games = []
    try:
        data = requests.get(NBA_API).json()
        for ev in data.get("events", []):
            tm = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
            if now_isr <= tm <= now_isr + timedelta(hours=22):
                t = ev["competitions"][0]["competitors"]
                a, h = tr(t[1]["team"]["displayName"]), tr(t[0]["team"]["displayName"])
                games.append(f"{RTL_MARK}⏰ ** {tm.strftime('%H:%M')} **\n{RTL_MARK}🏀 {a} 🆚 {h}")
        if games:
            send_telegram(f"{RTL_MARK}🏀 ══ ** לוח המשחקים להיום בלילה ** ══ 🏀\n\n" + "\n\n".join(games))
    except: pass

# --- הודעה 2 | 18:35 | לו"ז לגיונרים (לפי סדר: NBA, G-League, מכללות) ---
def msg_2_israeli_schedule():
    now_isr = datetime.now(pytz.timezone('Asia/Jerusalem'))
    saraf_in_gleague = False
    try:
        g_data = requests.get(GLEAGUE_API).json()
        saraf_in_gleague = any("Long Island" in t["team"]["displayName"] for ev in g_data.get("events", []) for t in ev["competitions"][0]["competitors"])
    except: pass

    leagues = [("NBA", "NBA", NBA_API), ("GLEAGUE", "G-LEAGUE", GLEAGUE_API), ("NCAA", "מכללות", NCAA_API)]
    
    for key, title, api_url in leagues:
        section = ""
        try:
            data = requests.get(api_url).json()
            for ev in data.get("events", []):
                tm = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
                if now_isr <= tm <= now_isr + timedelta(hours=22):
                    teams = ev["competitions"][0]["competitors"]
                    for p_en, info in PLAYERS[key].items():
                        if p_en == "Ben Saraf" and key == "NBA" and saraf_in_gleague: continue
                        if any(info[1].lower() in t["team"]["displayName"].lower() for t in teams):
                            status = get_injury_status(ev, p_en)
                            note = ""
                            if "QUESTIONABLE" in status or "GTD" in status:
                                note = f" {RTL_MARK}⚠️ (בסימן שאלה)"
                                injury_watch_list[f"{p_en}_{ev['id']}"] = {"name": info[0], "api": api_url}
                            
                            opp = [t["team"]["displayName"] for t in teams if info[1].lower() not in t["team"]["displayName"].lower()][0]
                            section += f"{RTL_MARK}🏀 ** {info[0]} **{note}\n{RTL_MARK}🆚 נגד: ** {tr(opp)} **\n{RTL_MARK}⏰ שעה: ** {tm.strftime('%H:%M')} **\n\n"
            if section:
                flag = "🇮🇱"
                header = f"{RTL_MARK}{flag} ** משחקי לגיונרים הלילה - {title} ** {flag}"
                send_telegram(f"{header}\n\n{section}")
        except: continue

# --- הודעה 3 | 18:36 | סיכום ביצועי לגיונרים מהבוקר ---
def msg_3_israeli_summary():
    date_str = (datetime.now() - timedelta(hours=15)).strftime("%Y%m%d")
    leagues = [("NBA", NBA_API, "nba"), ("GLEAGUE", GLEAGUE_API, "nba-ght"), ("NCAA", NCAA_API, "mens-college-basketball")]
    for key, api_url, path in leagues:
        section = ""
        try:
            data = requests.get(f"{api_url}?dates={date_str}").json()
            for ev in data.get("events", []):
                if ev["status"]["type"]["state"] == "post":
                    summary = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/{path}/summary?event={ev['id']}").json()
                    for p_en, info in PLAYERS[key].items():
                        for t_box in summary.get("players", []):
                            for athlete in t_box.get("athletes", []):
                                if p_en.lower() in athlete["athlete"]["displayName"].lower():
                                    s = athlete["stats"]
                                    pts, reb, ast = (s[0], s[1], s[2]) if key == "NCAA" else (s[14], s[13], s[15])
                                    teams = ev["competitions"][0]["competitors"]
                                    my_t = [t for t in teams if t["team"]["id"] == t_box["team"]["id"]][0]
                                    opp_t = [t for t in teams if t["team"]["id"] != t_box["team"]["id"]][0]
                                    res = "✅" if int(my_t["score"]) > int(opp_t["score"]) else "❌"
                                    section += f"{RTL_MARK}🏀 ** {info[0]} **\n{RTL_MARK}{res} {my_t['score']} - {opp_t['score']} נגד {tr(opp_t['team']['displayName'])}\n{RTL_MARK}📊 ** {pts} נק', {reb} ריב', {ast} אס' **\n\n"
            if section:
                send_telegram(f"{RTL_MARK}🇮🇱 ** סיכום לגיונרים - {key} ** 🇮🇱\n\n{section}")
        except: continue

# --- הודעה 4 | 18:37 | סיכום תוצאות NBA כללי ---
def msg_4_nba_results_summary():
    results = []
    try:
        date_str = (datetime.now() - timedelta(hours=15)).strftime("%Y%m%d")
        data = requests.get(f"{NBA_API}?dates={date_str}").json()
        for ev in data.get("events", []):
            if ev["status"]["type"]["state"] == "post":
                t = ev["competitions"][0]["competitors"]
                h_n, a_n = tr(t[0]["team"]["displayName"]), tr(t[1]["team"]["displayName"])
                h_s, a_s = int(t[0]["score"]), int(t[1]["score"])
                win = f"🏆 ** {h_n} {h_s} **" if h_s > a_s else f"🏆 ** {a_n} {a_s} **"
                lose = f"🏀 {a_n} {a_s}" if h_s > a_s else f"🏀 {h_n} {h_s}"
                results.append(f"{RTL_MARK}{win}\n{RTL_MARK}{lose}")
        if results:
            send_telegram(f"{RTL_MARK}🏁 ** סיכום תוצאות הלילה - NBA ** 🏁\n\n" + "\n\n".join(results))
    except: pass

# --- מנגנון בדיקת פציעות בזמן אמת ---
def check_live_injury_updates():
    global injury_watch_list
    to_remove = []
    for key, data in injury_watch_list.items():
        try:
            p_en = key.split('_')[0]
            resp = requests.get(data["api"]).json()
            for ev in resp.get("events", []):
                if ev["id"] in key:
                    status = get_injury_status(ev, p_en)
                    if "ACTIVE" in status or "PROBABLE" in status:
                        send_telegram(f"{RTL_MARK}🇮🇱 ** עדכון סופי: {data['name']} משחק! ** ✅")
                        to_remove.append(key)
                    elif "OUT" in status:
                        send_telegram(f"{RTL_MARK}🇮🇱 ** עדכון סופי: {data['name']} בחוץ הלילה ** ❌")
                        to_remove.append(key)
        except: pass
    for k in to_remove: injury_watch_list.pop(k, None)

# ==========================================
# --- לולאה ראשית ---
# ==========================================
if __name__ == "__main__":
    print("הבוט רץ ומנטר משחקים ופציעות...")
    while True:
        now = datetime.now(pytz.timezone('Asia/Jerusalem'))
        curr = now.strftime("%H:%M")

        if curr == "19:16":
            msg_1_nba_full_schedule()
            time.sleep(61)
        elif curr == "19:16":
            msg_2_israeli_schedule()
            time.sleep(61)
        elif curr == "19:16":
            msg_3_israeli_summary()
            time.sleep(61)
        elif curr == "19:16":
            msg_4_nba_results_summary()
            time.sleep(61)

        # בדיקת פציעות כל דקה בין 18:40 ל-09:00 בבוקר
        if (now.hour >= 18 and now.minute >= 40) or (now.hour < 9):
            check_live_injury_updates()

        time.sleep(30)

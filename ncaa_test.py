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
last_sent_min = "" 

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
        fixes = {"שבילים בלייזרים": "פורטלנד", "רשתות": "ברוקלין", "לוחמים": "גולדן סטייט", "בוכנות": "דטרויט", "חום": "מיאמי"}
        for k, v in fixes.items(): t = t.replace(k, v)
        return t
    except: return text

def send(text):
    if not text: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def get_inj(ev, p_en):
    try:
        for comp in ev.get("competitions", []):
            for team in comp.get("competitors", []):
                for inj in team.get("injuries", []):
                    if p_en.lower() in inj.get("displayName", "").lower():
                        return inj.get("status", "").upper()
    except: pass
    return "ACTIVE"

# --- 19:18: לו"ז NBA ---
def do_msg_1():
    try:
        data = requests.get(NBA_API).json()
        games = []
        for ev in data.get("events", []):
            tm = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
            t = ev["competitions"][0]["competitors"]
            games.append(f"{RTL_MARK}⏰ **{tm.strftime('%H:%M')}**\n{RTL_MARK}🏀 {tr(t[1]['team']['displayName'])} 🆚 {tr(t[0]['team']['displayName'])}")
        if games: send(f"{RTL_MARK}🏀 ══ **לוח המשחקים להיום בלילה** ══ 🏀\n\n" + "\n\n".join(games))
    except: pass

# --- 19:19: לו"ז לגיונרים ---
def do_msg_2():
    try:
        g_data = requests.get(GLEAGUE_API).json()
        saraf_gleague = any("Long Island" in t["team"]["displayName"] for ev in g_data.get("events", []) for t in ev["competitions"][0]["competitors"])
        
        for key, title in [("NBA", "NBA"), ("GLEAGUE", "G-LEAGUE"), ("NCAA", "מכללות")]:
            api = NBA_API if key == "NBA" else (GLEAGUE_API if key == "GLEAGUE" else NCAA_API)
            data = requests.get(api).json()
            sec = ""
            for ev in data.get("events", []):
                tm = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
                teams = ev["competitions"][0]["competitors"]
                for p_en, info in PLAYERS[key].items():
                    if p_en == "Ben Saraf" and key == "NBA" and saraf_gleague: continue
                    if any(info[1].lower() in t["team"]["displayName"].lower() for t in teams):
                        status = get_inj(ev, p_en)
                        note = " ⚠️ **(בסימן שאלה)**" if "QUEST" in status or "GTD" in status else ""
                        opp = [t["team"]["displayName"] for t in teams if info[1].lower() not in t["team"]["displayName"].lower()][0]
                        sec += f"{RTL_MARK}🏀 **{info[0]}**{note}\n{RTL_MARK}🆚 נגד: **{tr(opp)}**\n{RTL_MARK}⏰ שעה: **{tm.strftime('%H:%M')}**\n\n"
            if sec:
                flag = "🇮🇱"
                send(f"{RTL_MARK}{flag} **משחקי לגיונרים הלילה - {title}** {flag}\n\n{sec}")
    except: pass

# --- 19:20: סיכום ביצועים ---
def do_msg_3():
    try:
        date_str = (datetime.now() - timedelta(hours=15)).strftime("%Y%m%d")
        for key, api, path in [("NBA", NBA_API, "nba"), ("GLEAGUE", GLEAGUE_API, "nba-ght"), ("NCAA", NCAA_API, "mens-college-basketball")]:
            data = requests.get(f"{api}?dates={date_str}").json()
            sec = ""
            for ev in data.get("events", []):
                if ev["status"]["type"]["state"] == "post":
                    summary = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/{path}/summary?event={ev['id']}").json()
                    for p_en, info in PLAYERS[key].items():
                        for t_box in summary.get("players", []):
                            for ath in t_box.get("athletes", []):
                                if p_en.lower() in ath["athlete"]["displayName"].lower():
                                    s = ath["stats"]
                                    pts, reb, ast = (s[0], s[1], s[2]) if key == "NCAA" else (s[14], s[13], s[15])
                                    teams = ev["competitions"][0]["competitors"]
                                    my_t = [t for t in teams if t["team"]["id"] == t_box["team"]["id"]][0]
                                    opp_t = [t for t in teams if t["team"]["id"] != t_box["team"]["id"]][0]
                                    res = "✅" if int(my_t["score"]) > int(opp_t["score"]) else "❌"
                                    sec += f"{RTL_MARK}🏀 **{info[0]}**\n{RTL_MARK}{res} {my_t['score']} - {opp_t['score']} נגד {tr(opp_t['team']['displayName'])}\n{RTL_MARK}📊 **{pts} נק', {reb} ריב', {ast} אס'**\n\n"
            if sec: send(f"{RTL_MARK}🇮🇱 **סיכום לגיונרים - {key}** 🇮🇱\n\n{sec}")
    except: pass

# --- 19:21: סיכום תוצאות NBA ---
def do_msg_4():
    try:
        date_str = (datetime.now() - timedelta(hours=15)).strftime("%Y%m%d")
        data = requests.get(f"{NBA_API}?dates={date_str}").json()
        res = []
        for ev in data.get("events", []):
            if ev["status"]["type"]["state"] == "post":
                t = ev["competitions"][0]["competitors"]
                if int(t[0]["score"]) > int(t[1]["score"]):
                    res.append(f"{RTL_MARK}🏆 **{tr(t[0]['team']['displayName'])} {t[0]['score']}**\n{RTL_MARK}🏀 {tr(t[1]['team']['displayName'])} {t[1]['score']}")
                else:
                    res.append(f"{RTL_MARK}🏆 **{tr(t[1]['team']['displayName'])} {t[1]['score']}**\n{RTL_MARK}🏀 {tr(t[0]['team']['displayName'])} {t[0]['score']}")
        if res: send(f"{RTL_MARK}🏁 **סיכום תוצאות הלילה - NBA** 🏁\n\n" + "\n\n".join(res))
    except: pass

if __name__ == "__main__":
    print("הבוט פעיל. סבב ההודעות יתחיל ב-19:18...")
    while True:
        now = datetime.now(pytz.timezone('Asia/Jerusalem'))
        curr = now.strftime("%H:%M")
        if curr != last_sent_min:
            if curr == "19:23": do_msg_1()
            elif curr == "19:23": do_msg_2()
            elif curr == "19:23": do_msg_3()
            elif curr == "19:23": do_msg_4()
            last_sent_min = curr
        time.sleep(10)

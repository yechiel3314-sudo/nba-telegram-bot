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
injury_watch_list = {} # רשימת מעקב לפציעות
cycle_done_today = ""

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
        fixes = {"שבילים בלייזרים": "פורטלנד", "רשתות": "ברוקלין", "לוחמים": "גולדן סטייט", "בוכנות": "דטרויט", "חום": "מיאמי", "זאבי עץ": "מינסוטה"}
        for k, v in fixes.items(): t = t.replace(k, v)
        return t
    except: return text

def get_isr_time(date_str):
    utc_dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
    return utc_dt.astimezone(pytz.timezone('Asia/Jerusalem')).strftime("%H:%M")

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

# --- 1. לו"ז NBA (מ-19:00 והלאה) ---
def do_msg_1():
    try:
        data = requests.get(NBA_API).json()
        games = []
        for ev in data.get("events", []):
            tm = get_isr_time(ev['date'])
            t = ev['competitions'][0]['competitors']
            games.append(f"{RTL_MARK}⏰ **{tm}**\n{RTL_MARK}🏀 {tr(t[1]['team']['displayName'])} 🆚 {tr(t[0]['team']['displayName'])}")
        if games: send(f"{RTL_MARK}🏀 ══ **לוח המשחקים להיום בלילה** ══ 🏀\n\n" + "\n\n".join(games))
    except: pass

# --- 2. לו"ז לגיונרים מעוצב + פציעות ---
def do_msg_2():
    try:
        g_data = requests.get(GLEAGUE_API).json()
        saraf_gleague = any("Long Island" in t["team"]["displayName"] for ev in g_data.get("events", []) for t in ev["competitions"][0]["competitors"])
        
        for key, title in [("NBA", "NBA"), ("GLEAGUE", "G-LEAGUE"), ("NCAA", "מכללות")]:
            api = NBA_API if key == "NBA" else (GLEAGUE_API if key == "GLEAGUE" else NCAA_API)
            data = requests.get(api).json()
            section = ""
            for ev in data.get("events", []):
                teams = ev["competitions"][0]["competitors"]
                for p_en, info in PLAYERS[key].items():
                    if p_en == "Ben Saraf" and key == "NBA" and saraf_gleague: continue
                    if any(info[1].lower() in t["team"]["displayName"].lower() for t in teams):
                        st = get_inj(ev, p_en)
                        note = ""
                        if "QUEST" in st or "GTD" in st:
                            note = " ⚠️ **(בסימן שאלה)**"
                            injury_watch_list[f"{p_en}_{ev['id']}"] = {"name": info[0], "api": api}
                        
                        opp = [t["team"]["displayName"] for t in teams if info[1].lower() not in t["team"]["displayName"].lower()][0]
                        tm = get_isr_time(ev['date'])
                        link = "https://www.365scores.com/he/basketball"
                        section += f"{RTL_MARK}🇮🇱 **{info[0]}** ({tr(info[2])}){note}\n{RTL_MARK}🆚 נגד: **{tr(opp)}**\n{RTL_MARK}⏰ שעה: **{tm}**\n{RTL_MARK}🔗 [לעמוד המשחק ב-365Scores]({link})\n\n"
            if section: send(f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה - {title}** 🇮🇱\n\n{section}")
    except: pass

# --- 3. סיכום לגיונרים (תוצאות הבוקר) ---
def do_msg_3():
    try:
        yesterday = (datetime.now(pytz.timezone('Asia/Jerusalem')) - timedelta(days=1)).strftime("%Y%m%d")
        for key, api, path in [("NBA", NBA_API, "nba"), ("GLEAGUE", GLEAGUE_API, "nba-ght"), ("NCAA", NCAA_API, "mens-college-basketball")]:
            data = requests.get(f"{api}?dates={yesterday}").json()
            section = ""
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
                                    section += f"{RTL_MARK}🏀 **{info[0]}**\n{RTL_MARK}{res} {my_t['score']} - {opp_t['score']} נגד {tr(opp_t['team']['displayName'])}\n{RTL_MARK}📊 **{pts} נק', {reb} ריב', {ast} אס'**\n\n"
            if section: send(f"{RTL_MARK}🇮🇱 **סיכום לגיונרים מהבוקר - {key}** 🇮🇱\n\n{section}")
    except: pass

# --- 4. תוצאות NBA סופיות (העיצוב המקורי) ---
def do_msg_4():
    try:
        yesterday = (datetime.now(pytz.timezone('Asia/Jerusalem')) - timedelta(days=1)).strftime("%Y%m%d")
        data = requests.get(f"{NBA_API}?dates={yesterday}").json()
        res = []
        for ev in data.get("events", []):
            if ev["status"]["type"]["state"] == "post":
                t = ev["competitions"][0]["competitors"]
                w, l = (t[0], t[1]) if int(t[0]["score"]) > int(t[1]["score"]) else (t[1], t[0])
                res.append(f"{RTL_MARK}🏆 **{tr(w['team']['displayName'])} {w['score']}**\n{RTL_MARK}🏀 {tr(l['team']['displayName'])} {l['score']}")
        if res: send(f"{RTL_MARK}🏁 **סיכום תוצאות הלילה - NBA** 🏁\n\n" + "\n\n".join(res))
    except: pass

# --- ניטור פציעות אקטיבי ---
def check_live_injuries():
    global injury_watch_list
    to_remove = []
    for k, d in injury_watch_list.items():
        try:
            p_en = k.split('_')[0]
            evs = requests.get(d["api"]).json().get("events", [])
            for ev in evs:
                if ev["id"] in k:
                    st = get_inj(ev, p_en)
                    if "ACTIVE" in st or "PROBABLE" in st:
                        send(f"{RTL_MARK}🇮🇱 **עדכון סופי: {d['name']} משחק! ✅**")
                        to_remove.append(k)
                    elif "OUT" in st:
                        send(f"{RTL_MARK}🇮🇱 **עדכון סופי: {d['name']} בחוץ הלילה ❌**")
                        to_remove.append(k)
        except: pass
    for k in to_remove: injury_watch_list.pop(k, None)

if __name__ == "__main__":
    while True:
        now = datetime.now(pytz.timezone('Asia/Jerusalem'))
        curr = now.strftime("%H:%M")
        if curr == "19:41" and cycle_done_today != now.strftime("%Y%m%d"):
            do_msg_1()
            time.sleep(10)
            do_msg_2()
            time.sleep(10)
            do_msg_3()
            time.sleep(10)
            do_msg_4()
            cycle_done_today = now.strftime("%Y%m%d")
        
        if (now.hour >= 19 and now.minute >= 51) or (now.hour < 9):
            check_live_injuries()
        time.sleep(30)

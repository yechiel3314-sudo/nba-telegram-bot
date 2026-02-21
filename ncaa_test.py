import requests
import time
from datetime import datetime, timedelta
import pytz
from deep_translator import GoogleTranslator

# --- הגדרות ---
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

NBA_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
NCAA_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
GLEAGUE_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba-ght/scoreboard"

translator = GoogleTranslator(source='en', target='iw')
RTL_MARK = "\u200f"
injury_watch_list = {}
cycle_done_today = "" # מונע הרצה חוזרת באותו יום

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
    if not text or len(text) < 10: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

# --- פונקציות הודעות ---
def do_msg_1(): # לו"ז NBA
    try:
        data = requests.get(NBA_API).json()
        games = [f"{RTL_MARK}⏰ **{get_isr_time(ev['date'])}**\n{RTL_MARK}🏀 {tr(ev['competitions'][0]['competitors'][1]['team']['displayName'])} 🆚 {tr(ev['competitions'][0]['competitors'][0]['team']['displayName'])}" for ev in data.get("events", [])]
        if games: send(f"{RTL_MARK}🏀 ══ **לוח המשחקים להיום בלילה** ══ 🏀\n\n" + "\n\n".join(games))
    except: pass

def do_msg_2(): # לו"ז לגיונרים
    try:
        g_data = requests.get(GLEAGUE_API).json()
        saraf_gleague = any("Long Island" in t["team"]["displayName"] for ev in g_data.get("events", []) for t in ev["competitions"][0]["competitors"])
        for key, title in [("NBA", "NBA"), ("GLEAGUE", "G-LEAGUE"), ("NCAA", "מכללות")]:
            api = NBA_API if key == "NBA" else (GLEAGUE_API if key == "GLEAGUE" else NCAA_API)
            data = requests.get(api).json()
            sec = ""
            for ev in data.get("events", []):
                teams = ev["competitions"][0]["competitors"]
                for p_en, info in PLAYERS[key].items():
                    if p_en == "Ben Saraf" and key == "NBA" and saraf_gleague: continue
                    if any(info[1].lower() in t["team"]["displayName"].lower() for t in teams):
                        opp = [t["team"]["displayName"] for t in teams if info[1].lower() not in t["team"]["displayName"].lower()][0]
                        sec += f"{RTL_MARK}🏀 **{info[0]}** ({tr(info[2])})\n{RTL_MARK}🆚 נגד: **{tr(opp)}**\n{RTL_MARK}⏰ שעה: **{get_isr_time(ev['date'])}**\n\n"
            if sec: send(f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה - {title}** 🇮🇱\n\n{sec}")
    except: pass

def do_msg_3(): # סיכום לגיונרים (אתמול)
    try:
        yesterday = (datetime.now(pytz.timezone('Asia/Jerusalem')) - timedelta(days=1)).strftime("%Y%m%d")
        for key, api, path in [("NBA", NBA_API, "nba"), ("GLEAGUE", GLEAGUE_API, "nba-ght"), ("NCAA", NCAA_API, "mens-college-basketball")]:
            data = requests.get(f"{api}?dates={yesterday}").json()
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
                                    sec += f"{RTL_MARK}🏀 **{info[0]}**\n{RTL_MARK}📊 **{pts} נק', {reb} ריב', {ast} אס'**\n\n"
            if sec: send(f"{RTL_MARK}🇮🇱 **סיכום לגיונרים מהבוקר - {key}** 🇮🇱\n\n{sec}")
    except: pass

def do_msg_4(): # סיכום תוצאות NBA
    try:
        yesterday = (datetime.now(pytz.timezone('Asia/Jerusalem')) - timedelta(days=1)).strftime("%Y%m%d")
        data = requests.get(f"{NBA_API}?dates={yesterday}").json()
        res = []
        for ev in data.get("events", []):
            if ev["status"]["type"]["state"] == "post":
                t = ev["competitions"][0]["competitors"]
                res.append(f"{RTL_MARK}🏆 **{tr(t[0]['team']['displayName'])} {t[0]['score']}** - {tr(t[1]['team']['displayName'])} {t[1]['score']}")
        if res: send(f"{RTL_MARK}🏁 **תוצאות משחקי הלילה - NBA** 🏁\n\n" + "\n\n".join(res))
    except: pass

# --- לולאה ---
if __name__ == "__main__":
    while True:
        now = datetime.now(pytz.timezone('Asia/Jerusalem'))
        today_str = now.strftime("%Y%m%d")
        curr_hm = now.strftime("%H:%M")

        if curr_hm == "19:30" and cycle_done_today != today_str:
            do_msg_1()
            time.sleep(5) # המתנה קצרה בין הודעות
            do_msg_2()
            time.sleep(5)
            do_msg_3()
            time.sleep(5)
            do_msg_4()
            cycle_done_today = today_str
            print(f"סבב הושלם עבור {today_str}")
            
        time.sleep(30)

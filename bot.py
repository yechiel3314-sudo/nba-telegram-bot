import requests
import time
import json
import os

# =================================================================
# הגדרות מערכת - גרסה סופית ומקיפה (NBA Bot 2026)
# =================================================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
CACHE_FILE = "nba_bot_cache.json"

# מילון תרגום ידני מקיף לכל הליגה (מעודכן ל-2026)
PLAYER_TRANSLATIONS = {
    # אטלנטה, בוסטון, ברוקלין, שארלוט, שיקגו
    "Trae Young": "טריי יאנג", "Jalen Johnson": "ג'יילן ג'ונסון", "Clint Capela": "קלינט קפלה", "Bogdan Bogdanovic": "בוגדן בוגדנוביץ'", "Dyson Daniels": "דייסון דניאלס",
    "Jayson Tatum": "ג'ייסון טייטום", "Jaylen Brown": "ג'יילן בראון", "Derrick White": "דריק ווייט", "Jrue Holiday": "ג'רו הולידיי", "Kristaps Porzingis": "קריסטפס פורזינגיס", "Al Horford": "אל הורפורד", "Payton Pritchard": "פייטון פריצ'רד",
    "Cam Thomas": "קאם תומאס", "Nic Claxton": "ניק קלקסטון", "Dennis Schroder": "דניס שרודר", "Cameron Johnson": "קמרון ג'ונסון", "Ben Simmons": "בן סימונס",
    "LaMelo Ball": "לאמלו בול", "Brandon Miller": "ברנדון מילר", "Miles Bridges": "מיילס ברידג'ס", "Mark Williams": "מארק וויליאמס", "Grant Williams": "גראנט וויליאמס",
    "Zach LaVine": "זאק לאבין", "Nikola Vucevic": "ניקולה ווצ'ביץ'", "Coby White": "קובי ווייט", "Josh Giddey": "ג'וש גידי", "Patrick Williams": "פטריק וויליאמס", "Matas Buzelis": "מאטאס בוזליס",
    # קליבלנד, דטרויט, אינדיאנה, מיאמי, מילווקי
    "Donovan Mitchell": "דונובן מיטשל", "Darius Garland": "דריוס גארלנד", "Evan Mobley": "אוון מובלי", "Jarrett Allen": "ג'ארט אלן", "Caris LeVert": "קאריס לוורט", "Isaac Okoro": "אייזק אוקורו",
    "Cade Cunningham": "קייד קנינגהאם", "Jaden Ivey": "ג'יידן אייבי", "Tobias Harris": "טוביאס האריס", "Jalen Duren": "ג'יילן דורן", "Ausar Thompson": "אוסאר תומפסון", "Isaiah Stewart": "אייזק סטיוארט",
    "Tyrese Haliburton": "טייריס הליברטון", "Pascal Siakam": "פסקל סיאקם", "Myles Turner": "מיילס טרנר", "Aaron Nesmith": "אהרון ניסמית'", "Andrew Nembhard": "אנדרו נבהארד", "Bennedict Mathurin": "בנדיקט מאת'ורין",
    "Jimmy Butler": "ג'ימי באטלר", "Bam Adebayo": "באם אדבאיו", "Tyler Herro": "טיילר הירו", "Terry Rozier": "טרי רוזיר", "Duncan Robinson": "דאנקן רובינסון", "Jaime Jaquez Jr.": "היימה האקז ג'וניור",
    "Giannis Antetokounmpo": "יאניס אנדטוקומבו", "Damian Lillard": "דמיאן לילארד", "Khris Middleton": "כריס מידלטון", "Brook Lopez": "ברוק לופז", "Bobby Portis": "בובי פורטיס", "Gary Trent Jr.": "גארי טרנט ג'וניור",
    # ניו יורק, אורלנדו, פילדלפיה, טורונטו, וושינגטון
    "Jalen Brunson": "ג'יילן בראנסון", "Karl-Anthony Towns": "קארל-אנתוני טאונס", "OG Anunoby": "או ג'י אנונובי", "Josh Hart": "ג'וש הארט", "Mikal Bridges": "מיקאל ברידג'ס", "Miles McBride": "מיילס מקברייד",
    "Paolo Banchero": "פאולו באנקרו", "Franz Wagner": "פרנץ ואגנר", "Jalen Suggs": "ג'יילן סאגס", "Wendell Carter Jr.": "ונדל קרטר ג'וניור", "Kentavious Caldwell-Pope": "קנטביוס קולדוול-פופ",
    "Joel Embiid": "ג'ואל אמביד", "Tyrese Maxey": "טייריס מקסי", "Paul George": "פול ג'ורג'", "Kelly Oubre Jr.": "קלי אוברה", "Caleb Martin": "קיילב מרטין", "Andre Drummond": "אנדרה דראמונד", "Kyle Lowry": "קייל לאורי",
    "Scottie Barnes": "סקוטי בארנס", "RJ Barrett": "אר ג'יי בארט", "Immanuel Quickley": "עמנואל קוויקלי", "Jakob Poeltl": "יאקוב פולטל", "Gradey Dick": "גריידי דיק",
    "Jordan Poole": "ג'ורדן פול", "Kyle Kuzma": "קייל קוזמה", "Alex Sarr": "אלכס סאר", "Bilal Coulibaly": "בילאל קוליבאלי", "Malcolm Brogdon": "מלקולם ברוגדון", "Jonas Valanciunas": "יונאס ואלאנצ'יונאס", "Deni Avdija": "דני אבדיה",
    # דאלאס, דנבר, גולדן סטייט, יוסטון, קליפרס
    "Luka Doncic": "לוקה דונצ'יץ'", "Kyrie Irving": "קיירי אירווינג", "Klay Thompson": "קליי תומפסון", "P.J. Washington": "פי ג'יי וושינגטון", "Dereck Lively II": "דרק לייבלי", "Daniel Gafford": "דניאל גאפורד",
    "Nikola Jokic": "ניקולה יוקיץ'", "Jamal Murray": "ג'מאל מארי", "Michael Porter Jr.": "מייקל פורטר ג'וניור", "Aaron Gordon": "אהרון גורדון", "Christian Braun": "כריסטיאן בראון", "Russell Westbrook": "ראסל ווסטברוק",
    "Stephen Curry": "סטפן קרי", "Draymond Green": "דריימונד גרין", "Andrew Wiggins": "אנדרו וויגינס", "Jonathan Kuminga": "ג'ונתן קומינגה", "Buddy Hield": "באדי הילד", "Brandin Podziemski": "ברנדין פודז'מסקי", "Trayce Jackson-Davis": "טרייס ג'קסון-דייוויס",
    "Alperen Sengun": "אלפרן שנגון", "Jalen Green": "ג'יילן גרין", "Fred VanVleet": "פרד ואנווליט", "Jabari Smith Jr.": "ג'בארי סמית'", "Amen Thompson": "אמן תומפסון", "Dillon Brooks": "דילון ברוקס", "Reed Sheppard": "ריד שפרד",
    "James Harden": "ג'יימס הארדן", "Kawhi Leonard": "קוואי לנארד", "Norman Powell": "נורמן פאוול", "Ivica Zubac": "איביצה זובאץ", "Derrick Jones Jr.": "דריק ג'ונס ג'וניור", "Terance Mann": "טרנס מאן",
    # לייקרס, ממפיס, מינסוטה, ניו אורלינס, אוקלהומה סיטי
    "LeBron James": "לברון ג'יימס", "Anthony Davis": "אנתוני דייוויס", "Austin Reaves": "אוסטין ריבס", "D'Angelo Russell": "דיאנג'לו ראסל", "Rui Hachimura": "רוי האצ'ימורה", "Dalton Knecht": "דלטון קנקט", "Bronny James": "ברוני ג'יימס",
    "Ja Morant": "ג'ה מוראנט", "Desmond Bane": "דזמונד ביין", "Jaren Jackson Jr.": "ג'ארן ג'קסון ג'וניור", "Marcus Smart": "מרקוס סמארט", "Zach Edey": "זאק אידי", "Santi Aldama": "סנטי אלדמה",
    "Anthony Edwards": "אנתוני אדוארדס", "Julius Randle": "ג'וליוס רנדל", "Rudy Gobert": "רודי גובר", "Donte DiVincenzo": "דונטה דיווינצ'נזו", "Naz Reid": "נאז ריד", "Jaden McDaniels": "ג'יידן מקדניאלס",
    "Zion Williamson": "זאיון וויליאמסון", "Brandon Ingram": "ברנדון אינגרם", "CJ McCollum": "סי ג'יי מקולום", "Dejounte Murray": "דג'ונטה מארי", "Herbert Jones": "הרברט ג'ונס", "Trey Murphy III": "טריי מרפי",
    "Shai Gilgeous-Alexander": "שיי גילג'ס-אלכסנדר", "Chet Holmgren": "צ'ט הולמגרן", "Jalen Williams": "ג'יילן וויליאמס", "Isaiah Hartenstein": "אייזאה הרטנשטיין", "Alex Caruso": "אלכס קארוסו", "Luguentz Dort": "לוגנץ דורט",
    # פיניקס, פורטלנד, סקרמנטו, סן אנטוניו, יוטה
    "Kevin Durant": "קוין דוראנט", "Devin Booker": "דבין בוקר", "Bradley Beal": "בראדלי ביל", "Jusuf Nurkic": "יוסוף נורקיץ'", "Tyus Jones": "טיוס ג'ונס", "Grayson Allen": "גרייסון אלן",
    "Anfernee Simons": "אנפרני סיימונס", "Jerami Grant": "ג'ראמי גרנט", "Deandre Ayton": "דיאנדרה אייטון", "Scoot Henderson": "סקוט הנדרסון", "Shaedon Sharpe": "שיידון שארפ", "Donovan Clingan": "דונובן קלינגן",
    "De'Aaron Fox": "דיארון פוקס", "Domantas Sabonis": "דומנטאס סאבוניס", "DeMar DeRozan": "דמאר דרוזן", "Keegan Murray": "קיגן מארי", "Malik Monk": "מליק מונק", "Kevin Huerter": "קוין הרטר",
    "Victor Wembanyama": "ויקטור וומבניאמה", "Chris Paul": "כריס פול", "Devin Vassell": "דבין ואסל", "Harrison Barnes": "האריסון בארנס", "Jeremy Sochan": "ג'רמי סוהן", "Stephon Castle": "סטפון קאסל",
    "Lauri Markkanen": "לאורי מארקנן", "Collin Sexton": "קולין סקסטון", "Walker Kessler": "ווקר קסלר", "Jordan Clarkson": "ג'ורדן קלרקסון", "John Collins": "ג'ון קולינס", "Keyonte George": "קיאנטה ג'ורג'"
}

TEAM_TRANSLATIONS = {
    "Hawks": "אטלנטה הוקס", "Celtics": "בוסטון סלטיקס", "Nets": "ברוקלין נטס", 
    "Hornets": "שארלוט הורנטס", "Bulls": "שיקגו בולס", "Cavaliers": "קליבלנד קאבלירס", 
    "Mavericks": "דאלאס מאבריקס", "Nuggets": "דנבר נאגטס", "Pistons": "דטרויט פיסטונס", 
    "Warriors": "גולדן סטייט ווריורס", "Rockets": "יוסטון רוקטס", "Pacers": "אינדיאנה פייסרס", 
    "Clippers": "לוס אנג'לס קליפרס", "Lakers": "לוס אנג'לס לייקרס", "Grizzlies": "ממפיס גריזליס", 
    "Heat": "מיאמי היט", "Bucks": "מילווקי באקס", "Timberwolves": "מינסוטה טימברוולבס", 
    "Pelicans": "ניו אורלינס פליקנס", "Knicks": "ניו יורק ניקס", "Thunder": "אוקלהומה סיטי ת'אנדר", 
    "Magic": "אורלנדו מג'יק", "76ers": "פילדלפיה 76", "Suns": "פיניקס סאנס", 
    "Trail Blazers": "פורטלנד טרייל בלייזרס", "Kings": "סקרמנטו קינגס", "Spurs": "סן אנתוניו ספרס", 
    "Raptors": "טורונטו ראפטורס", "Jazz": "יוטה ג'אז", "Wizards": "וושינגטון ויזארדס"
}

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {"games": {}}

cache = load_cache()

def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=4, ensure_ascii=False)

def translate_name(eng):
    return PLAYER_TRANSLATIONS.get(eng, eng)

def get_detailed_info(box):
    data = {"away": {"starters": [], "out": []}, "home": {"starters": [], "out": []}}
    for side, key in [('awayTeam', 'away'), ('homeTeam', 'home')]:
        players = box.get(side, {}).get('players', [])
        for p in players:
            p_full = f"{p['firstName']} {p['familyName']}"
            name = translate_name(p_full)
            if p.get('starter') == "1": data[key]['starters'].append(name)
            if p.get('status') == "INACTIVE": data[key]['out'].append(name)
    return data

def get_stat_line(p):
    s = p['statistics']
    return f"{s['points']} נק', {s['reboundsTotal']} רב', {s['assists']} אס'"

def format_msg(box, label, is_final=False):
    away, home = box['awayTeam'], box['homeTeam']
    a_name = TEAM_TRANSLATIONS.get(away['teamName'], away['teamName'])
    h_name = TEAM_TRANSLATIONS.get(home['teamName'], home['teamName'])
    period = box.get('period', 0)
    rtl = "\u200f"
    def b(text): return f"<b>{str(text).strip()}</b>"

    # לוגיקה להארכות
    clean_label = label
    if period > 4:
        ot_count = period - 4
        if "סיום" in label: clean_label = f"סיום הארכה {ot_count}"
        elif "דרך" in label: clean_label = f"הארכה {ot_count} יצאה לדרך"

    msg = f"{rtl}⏱️ {b(clean_label)}\n"
    msg += f"{rtl}🏀 {b(a_name)} 🆚 {b(h_name)} 🏀\n\n"

    photo_url = None
    # הודעת פתיחה - חיסורים + פוסטר כוכב הבית
    if "דרך" in label and period == 1:
        info = get_detailed_info(box)
        try:
            h_starters = [p for p in home.get('players', []) if p.get('starter') == "1"]
            # דרישה: פוסטר כוכב הבית
            p_id = h_starters[0]['personId'] if h_starters else home['teamId']
            photo_url = f"https://www.nba.com/stats/api/v1/playerActionPhoto/{p_id}"
        except:
            photo_url = f"https://cdn.nba.com/logos/leagues/L/nba/matchups/{away['teamId']}-vs-{home['teamId']}.png"
        
        for team_key, t_display in [('away', a_name), ('home', h_name)]:
            msg += f"{rtl}📍 {b(t_display)}\n"
            msg += f"{rtl}🏀 {b('חמישייה:')} {', '.join(info[team_key]['starters'])}\n"
            if info[team_key]['out']:
                msg += f"{rtl}❌ {b('חיסורים:')} {', '.join(info[team_key]['out'][:6])}\n"
            msg += "\n"
        return msg, photo_url

    # תוצאה וסטטיסטיקות
    leader = a_name if away['score'] > home['score'] else h_name
    verb = "מנצחת" if is_final else "מובילה"
    msg += f"{rtl}🔥 {b(leader)} {verb} {b(str(max(away['score'], home['score'])) + ' - ' + str(min(away['score'], home['score'])))} 🔥\n\n"

    count = 3 if (period >= 4 or is_final) else 2
    for team, t_display in [(away, a_name), (home, h_name)]:
        msg += f"{rtl}📍 {b(t_display)}\n"
        best = sorted(team.get('players', []), key=lambda x: x['statistics']['points'], reverse=True)[:count]
        for i, p in enumerate(best):
            medal = ["🥇", "🥈", "🥉"][i]
            p_heb = translate_name(f"{p['firstName']} {p['familyName']}")
            msg += f"{rtl}{medal} {b(p_heb)}: {get_stat_line(p)}\n"
        msg += "\n"

    if is_final:
        mvp = max(away.get('players', []) + home.get('players', []), key=lambda x: x['statistics']['points'])
        mvp_name = translate_name(f"{mvp['firstName']} {mvp['familyName']}")
        msg += f"{rtl}⭐ {b('ה-MVP: ' + mvp_name)}\n{rtl}📊 {get_stat_line(mvp)}"
        photo_url = f"https://www.nba.com/stats/api/v1/playerActionPhoto/{mvp['personId']}"

    return msg, photo_url

def send_telegram(text, photo_url=None):
    base = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    try:
        if photo_url: requests.post(f"{base}/sendPhoto", json={"chat_id": CHAT_ID, "photo": photo_url, "caption": text, "parse_mode": "HTML"}, timeout=15)
        else: requests.post(f"{base}/sendMessage", json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
    except: pass

def run():
    print("🧪 בדיקה רטרואקטיבית...")
    try:
        data = requests.get(NBA_URL, timeout=10).json()
        for g in data.get('scoreboard', {}).get('games', []):
            if g['gameStatus'] in [2, 3]:
                box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{g['gameId']}.json").json()['game']
                m, p = format_msg(box, "סיום המשחק" if g['gameStatus'] == 3 else f"סיום רבע {g['period']}", is_final=(g['gameStatus'] == 3))
                send_telegram("⚠️ <b>רטרו</b>\n" + m, p)
                time.sleep(2)
    except: pass

    while True:
        try:
            data = requests.get(NBA_URL, timeout=10).json()
            for g in data.get('scoreboard', {}).get('games', []):
                gid, status, period, txt = g['gameId'], g['gameStatus'], g['period'], g.get('gameStatusText', '').lower()
                if gid not in cache["games"]: cache["games"][gid] = []
                
                if ("end" in txt or "half" in txt or status == 3) and txt not in cache["games"][gid]:
                    box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']
                    m, p = format_msg(box, "סיום המשחק" if status == 3 else f"סיום רבע {period}", is_final=(status == 3))
                    send_telegram(m, p)
                    cache["games"][gid].append(txt)
                    save_cache()

                if "start" in txt and f"s_{period}" not in cache["games"][gid]:
                    box = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json").json()['game']
                    m, p = format_msg(box, f"רבע {period} יצא לדרך")
                    send_telegram(m, p)
                    cache["games"][gid].append(f"s_{period}")
                    save_cache()
        except: pass
        time.sleep(25)

if __name__ == "__main__":
    run()

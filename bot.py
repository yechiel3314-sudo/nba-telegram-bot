import requests
import time
import json
import os
import html
import hashlib
from datetime import datetime
from deep_translator import GoogleTranslator
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==========================================
# הגדרות מערכת וטוקנים
# ==========================================
SENT_EVENTS_DIR = "sent_events"
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
CACHE_FILE = "nba_cache.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
ISRAEL_LAT = 31.778
ISRAEL_LON = 35.235
ISRAEL_TZID = "Asia/Jerusalem"

CURRENT_SHABBAT_OR_YOM_TOV = False

translator = GoogleTranslator(source='en', target='iw')

def build_session():
    s = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


SESSION = build_session()


def get_json(url):
    try:
        r = SESSION.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"❌ שגיאה בבקשת JSON: {url} | {e}")
        return None


def is_shabbat_or_yom_tov():
    """
    מחזיר True אם עכשיו יש איסור מלאכה בפועל.
    מתאים לשבת וליום טוב.
    """
    try:
        url = (
            "https://www.hebcal.com/zmanim"
            f"?cfg=json&im=1&latitude={ISRAEL_LAT}&longitude={ISRAEL_LON}&tzid={ISRAEL_TZID}"
        )
        data = get_json(url)
        if not data:
            return False

        status = data.get("status") or {}
        return bool(status.get("isAssurBemlacha"))
    except Exception as e:
        print(f"❌ שגיאה בבדיקת שבת/חג: {e}")
        return False

NBA_TEAMS_HEBREW = {
    "Atlanta Hawks": "אטלנטה הוקס", "Boston Celtics": "בוסטון סלטיקס",
    "Brooklyn Nets": "ברוקלין נטס", "Charlotte Hornets": "שארלוט הורנטס",
    "Chicago Bulls": "שיקגו בולס", "Cleveland Cavaliers": "קליבלנד קאבלירס",
    "Dallas Mavericks": "דאלאס מאבריקס", "Denver Nuggets": "דנבר נאגטס",
    "Detroit Pistons": "דטרויט פיסטונס", "Golden State Warriors": "גולדן סטייט ווריורס",
    "Houston Rockets": "יוסטון רוקטס", "Indiana Pacers": "אינדיאנה פייסרס",
    "LA Clippers": "לוס אנג'לס קליפרס", "Los Angeles Lakers": "לוס אנג'לס לייקרס",
    "Memphis Grizzlies": "ממפיס גריזליס", "Miami Heat": "מיאמי היט",
    "Milwaukee Bucks": "מילווקי באקס", "Minnesota Timberwolves": "מינסוטה טימברוולבס",
    "New Orleans Pelicans": "ניו אורלינס פליקנס", "New York Knicks": "ניו יורק ניקס",
    "Oklahoma City Thunder": "אוקלהומה סיטי ת'אנדר", "Orlando Magic": "אורלנדו מג'יק",
    "Philadelphia 76ers": "פילדלפיה 76", "Phoenix Suns": "פיניקס סאנס",
    "Portland Trail Blazers": "פורטלנד טרייל בלייזרס", "Sacramento Kings": "סקרמנטו קינגס",
    "San Antonio Spurs": "סן אנטוניו ספרס", "Toronto Raptors": "טורונטו ראפטורס",
    "Utah Jazz": "יוטה ג'אז", "Washington Wizards": "וושינגטון וויזארדס"
}

NBA_PLAYERS_HEB = {
    # --- פורטלנד טרייל בלייזרס ---
    "Deni Avdija": "דני אבדיה", "Jrue Holiday": "ג'רו הולידיי", "Jerami Grant": "ג'רמי גרנט", "Scoot Henderson": "סקוט הנדרסון", "Donovan Clingan": "דונובן קלינגן",
    "Shaedon Sharpe": "שיידון שארפ", "Damian Lillard": "דמיאן לילארד", "Yang Hansen": "יאנג הנסן", "Vit Krejci": "ויט קרייצ'י", "Toumani Camara": "טומאני קמארה",
    "Matisse Thybulle": "מטיס תייבול", "Kris Murray": "קריס מארי", "Blake Wesley": "בלייק וסלי", "Robert Williams III": "רוברט וויליאמס", "Rayan Rupert": "ריאן רופר",
    "Sidy Cissoko": "סידי סיסוקו", "Caleb Love": "קיילב לאב", "Bobi Klintman": "בובי קלינטמן",

    # --- אוקלוהומה סיטי ת'אנדר ---
    "Shai Gilgeous-Alexander": "שיי גילג'ס-אלכסנדר", "Chet Holmgren": "צ'ט הולמגרן", "Jalen Williams": "ג'יילן ויליאמס", "Alex Sarr": "אלכס סאר", "Cason Wallace": "קייסון וואלאס",
    "Luguentz Dort": "לו דורט", "Isaiah Joe": "איזאיה ג'ו", "Jaylin Williams": "ג'יילין ויליאמס", "Aaron Wiggins": "ארון ויגינס", "Ousmane Dieng": "אוסמן דיינג",
    "Kenrich Williams": "קנריץ' ויליאמס", "Dillon Jones": "דילון ג'ונס", "Ajay Mitchell": "אג'יי מיצ'ל", "Nikola Topic": "ניקולה טופיץ'", "Adam Flagler": "אדם פלאגלר",
    "Keyontae Johnson": "קיאון ג'ונסון'", "Malevy Leons": "מאלבי לאונס", "Branden Carlson": "ברנדן קרלסון",

    # --- קליבלנד קאבלירס ---
    "James Harden": "ג'יימס הארדן", "Donovan Mitchell": "דונובן מיטשל", "Evan Mobley": "אוון מובלי", "Jarrett Allen": "ג'ארט אלן", "Caris LeVert": "קאריס לוורט",
    "Dennis Schroder": "דניס שרודר", "Max Strus": "מקס סטרוס", "Isaac Okoro": "אייזק אוקורו", "Georges Niang": "ג'ורג' ניאנג", "Dean Wade": "דין וייד",
    "Sam Merrill": "סאם מריל", "Tyrese Proctor": "טייריס פרוקטור", "Keon Ellis": "קיון אליס", "Craig Porter Jr.": "קרייג פורטר ג'וניור", "Jaylon Tyson": "ג'יילן טייסון",
    "JT Thor": "ג'יי טי ת'ור", "Luke Travers": "לוק טראברס", "Emoni Bates": "אמוני בייטס",

    # --- יוסטון רוקטס ---
    "Kevin Durant": "קווין דוראנט", "Alperen Sengun": "אלפרן שנגון", "Amen Thompson": "אמן תומפסון", "Reed Sheppard": "ריד שפרד", "Jabari Smith Jr.": "ג'בארי סמית' ג'וניור",
    "Tari Eason": "טארי איסון", "Cam Whitmore": "קאם ויטמור", "Dorian Finney-Smith": "דוריאן פיני-סמית'", "Clint Capela": "קלינט קפלה", "Josh Okogie": "ג'וש אוקוגי",
    "Aaron Holiday": "ארון הולידיי", "Jock Landale": "ג'וק לנדייל", "Jae'Sean Tate": "ג'יישון טייט", "Steven Adams": "סטיבן אדאמס", "Jack McVeigh": "ג'ק מקווי",
    "N'Faly Dante": "נפאלי דאנטה", "Jermaine Samuels": "ג'רמיין סמואלס", "Nate Williams": "נייט ויליאמס",

    # --- דאלאס מאבריקס ---
    "Luka Doncic": "לוקה דונציץ'", "Kyrie Irving": "קיירי אירווינג", "P.J. Washington": "פי ג'יי וושינגטון", "Dereck Lively II": "דרק לייבלי", "Klay Thompson": "קליי תומפסון",
    "Naji Marshall": "נאג'י מרשל", "Quentin Grimes": "קוונטין גריימס", "Daniel Gafford": "דניאל גאפורד", "Maxi Kleber": "מקסי קליבר", "Jaden Hardy": "ג'יידן הארדי",
    "Dwight Powell": "דווייט פאוול", "Dante Exum": "דאנטה אקסום", "Markieff Morris": "מרקיף מוריס", "Olivier-Maxence Prosper": "אוליבייה-מקסנס פרוספר", "A.J. Lawson": "איי.ג'יי לוסון",
    "Kessler Edwards": "קסלר אדוארדס", "Brandon Williams": "ברנדון ויליאמס", "Jazian Gortman": "ג'זיאן גורטמן",

    # --- בוסטון סלטיקס ---
    "Jayson Tatum": "ג'ייסון טייטום", "Jaylen Brown": "ג'יילן בראון", "Kristaps Porzingis": "קריסטאפס פורזינגיס", "Derrick White": "דריק וייט", "Anfernee Simons": "אנפרני סיימונס",
    "Payton Pritchard": "פייטון פריצארד", "Sam Hauser": "סאם האוזר", "Al Horford": "אל הורפורד", "Jordan Walsh": "ג'ורדן וולש", "Baylor Scheierman": "ביילור שיירמן",
    "Luke Kornet": "לוק קורנט", "Xavier Tillman": "קסבייר טילמן", "Neemias Queta": "נמיאס קייטה", "Jaden Springer": "ג'יידן ספרינגר", "Anton Watson": "אנטון ווטסון",
    "Drew Peterson": "דרו פיטרסון", "JD Davison": "ג'יי די דייוויסון", "Ron Harper Jr.": "רון הארפר ג'וניור",

    # --- סן אנטוניו ספרס ---
    "Victor Wembanyama": "ויקטור ומבניאמה", "Chris Paul": "כריס פול", "Devin Vassell": "דווין ואסל", "Stephon Castle": "סטפון קאסל", "Jeremy Sochan": "ג'רמי סוהאן",
    "Harrison Barnes": "הריסון בארנס", "Keldon Johnson": "קלדון ג'ונסון", "Tre Jones": "טרה ג'ונס", "Malaki Branham": "מלאכי ברנהם", "Zach Collins": "זאק קולינס",
    "Julian Champagnie": "ג'וליאן שמפאני", "Sandro Mamukelashvili": "סנדרו מאמוקלושווילי", "Blake Wesley": "בלייק וסלי", "Sidy Cissoko": "סידי סיסוקו", "Charles Bassey": "צ'ארלס באסי",
    "David Duke Jr.": "דייוויד דיוק ג'וניור", "Riley Minix": "ריילי מיניקס", "Harrison Ingram": "הריסון אינגרם",

    # --- פיניקס סאנס ---
    "Devin Booker": "דווין בוקר", "Jalen Green": "ג'יילן גרין", "Bradley Beal": "בראדלי ביל", "Jusuf Nurkic": "יוסוף נורקיץ'", "Grayson Allen": "גרייסון אלן",
    "Royce O'Neale": "רויס אוניל", "Bol Bol": "בול בול", "Tyus Jones": "טיוס ג'ונס", "Mason Plumlee": "מייסון פלאמלי", "Oso Ighodaro": "אוסו איגודארו",
    "Ryan Dunn": "ראיין דאן", "Josh Okogie": "ג'וש אוקוגי", "Damion Lee": "דמיון לי", "Monte Morris": "מונטה מוריס", "Jalen Bridges": "ג'יילן ברידג'ס",
    "TyTy Washington": "טיי-טיי וושינגטון", "Collin Gillespie": "קולין גילספי", "Frank Kaminsky": "פרנק קמינסקי",

    # --- לוס אנג'לס לייקרס ---
    "LeBron James": "לברון ג'יימס", "Anthony Davis": "אנתוני דייוויס", "Deandre Ayton": "דיאנדרה אייטון", "Austin Reaves": "אוסטין ריבס", "Rui Hachimura": "רוי האצ'ימורה",
    "Dalton Knecht": "דלטון קנקט", "D'Angelo Russell": "דיאנג'לו ראסל", "Max Christie": "מקס כריסטי", "Gabe Vincent": "גייב וינסנט", "Jarred Vanderbilt": "ג'ארד ונדרבילט",
    "Jaxson Hayes": "ג'קסון הייז", "Cam Reddish": "קאם רדיש", "Bronny James": "ברוני ג'יימס", "Christian Wood": "כריסטיאן ווד", "Jalen Hood-Schifino": "ג'יילן הוד-שיפינו",
    "Maxwell Lewis": "מקסוול לואיס", "Armel Traore": "ארמל טראורה", "Christian Koloko": "כריסטיאן קולוקו",

    # --- שיקגו בולס ---
    "Matas Buzelis": "מאטאס בוזליס", "Josh Giddey": "ג'וש גידי", "Coby White": "קובי וייט", "Patrick Williams": "פטריק ויליאמס", "Zach LaVine": "זאק לאבין",
    "Ayo Dosunmu": "איו דוסונמו", "Jalen Smith": "ג'יילן סמית'", "Julian Phillips": "ג'וליאן פיליפס", "Tre Jones": "טרה ג'ונס", "Collin Sexton": "קולין סקסטון",
    "Dalen Terry": "דיילן טרי", "Lonzo Ball": "לונזו בול", "Torrey Craig": "טורי קרייג", "Jevon Carter": "ג'בון קארטר", "Adama Sanogo": "אדאמה סנוגו",
    "DJ Steward": "די ג'יי סטיוארט", "E.J. Liddell": "אי ג'יי לידל", "Kenneth Lofton Jr.": "קנת' לופטון ג'וניור",

    # --- אוקלהומה סיטי ת'אנדר ---
    "Shai Gilgeous-Alexander": "שיי גילג'ס-אלכסנדר", "Chet Holmgren": "צ'ט הולמגרן", "Jalen Williams": "ג'יילן ויליאמס", "Alex Sarr": "אלכס סאר", "Cason Wallace": "קייסון וואלאס",
    "Luguentz Dort": "לו דורט", "Isaiah Joe": "איזאיה ג'ו", "Jaylin Williams": "ג'יילין ויליאמס", "Aaron Wiggins": "ארון ויגינס", "Ousmane Dieng": "אוסמן דיינג",
    "Kenrich Williams": "קנריץ' ויליאמס", "Dillon Jones": "דילון ג'ונס", "Ajay Mitchell": "אג'יי מיצ'ל", "Nikola Topic": "ניקולה טופיץ'", "Adam Flagler": "אדם פלאגלר",
    "Keyontae Johnson": "קיאון ג'ונסון'", "Malevy Leons": "מאלבי לאונס", "Branden Carlson": "ברנדון קרלסון",

    # --- אטלנטה הוקס ---
    "Dejounte Murray": "דז'ונטה מארי", "Jalen Johnson": "ג'יילן ג'ונסון", "Zaccharie Risacher": "זקארי ריסאשה", "Onyeka Okongwu": "אונייקה אוקונגוו", "C.J. McCollum": "סי.ג'יי מקולום",
    "Dyson Daniels": "דייסון דניאלס", "Nickeil Alexander-Walker": "ניקיל אלכסנדר-ווקר", "Jonathan Kuminga": "ג'ונתן קומינגה", "Bogdan Bogdanovic": "בוגדן בוגדנוביץ'", "Gabe Vincent": "גייב וינסנט",
    "De'Andre Hunter": "דיאנדרה האנטר", "Kobe Bufkin": "קובי באפקין", "Larry Nance Jr.": "לארי נאנס ג'וניור", "Garrison Mathews": "גאריסון מתיוס", "Cody Zeller": "קודי זלר",
    "David Roddy": "דייוויד רודי", "Mouhamed Gueye": "מוחמד גיי", "Keaton Wallace": "קיטון וואלאס",

    # --- ברוקלין נטס ---
    "Michael Porter Jr.": "מייקל פורטר ג'וניור", "Nic Claxton": "ניק קלקסטון", "Noah Clowney": "נואה קלאוני", "Egor Demin": "איגור דיומין", "Nolan Traore": "נולן טראורה",
    "Ben Saraf": "בן שרף", "Danny Wolf": "דני וולף", "Ziaire Williams": "זיאייר ויליאמס", "Day'Ron Sharpe": "דיירון שארפ", "Drake Powell": "דרייק פאוול",
    "Dariq Whitehead": "דאריק וייטהד", "Jalen Wilson": "ג'יילן וילסון", "Cam Johnson": "קמרון ג'ונסון", "Trendon Watford": "טרנדון ווטפורד", "Keon Johnson": "קיון ג'ונסון",
    "Tyrese Martin": "טייריס מרטין", "Jaylen Martin": "ג'יילן מרטין", "Cui Yongxi": "יונשי קוי", "Isaiah Hartenstein": "אייזיאה הרטנשטיין", "Jeremiah Robinson-Earl": "ג'רמיה רובינסון-ארל",

    # --- שארלוט הורנטס ---
    "LaMelo Ball": "לאמלו בול", "Brandon Miller": "ברנדון מילר", "Kon Knueppel": "קון קוניפל", "Miles Bridges": "מיילס ברידג'ס", "Coby White": "קובי וייט",
    "Grant Williams": "גראנט ויליאמס", "Tidjane Salaun": "טיג'אן סאלון", "Moussa Diabate": "מוסא דיאבטה", "Josh Green": "ג'וש גרין", "Nick Richards": "ניק ריצ'רדס",
    "Tre Mann": "טרה מאן", "Vasilije Micic": "ואסיליה מיציץ'", "Mark Williams": "מארק ויליאמס", "Seth Curry": "סת' קארי", "Cody Martin": "קודי מרטין",
    "Nick Smith Jr.": "ניק סמית' ג'וניור", "KJ Simpson": "קיי.ג'יי סימפסון", "Taj Gibson": "טאג' גיבסון",

    # --- דטרויט פיסטונס ---
    "Cade Cunningham": "קייד קנינגהם", "Jaden Ivey": "ג'יידן אייבי", "Tobias Harris": "טוביאס האריס", "Jalen Duren": "ג'יילן דורן", "Ausar Thompson": "אסאר תומפסון",
    "Ron Holland": "רון הולנד", "Isaiah Stewart": "אייזיה סטיוארט", "Simone Fontecchio": "סימונה פונטקיו", "Malik Beasley": "מליק ביזלי", "Tim Hardaway Jr.": "טים הארדוויי ג'וניור",
    "Wendell Moore Jr.": "ונדל מור ג'וניור", "Paul Reed": "פול ריד", "Marcus Sasser": "מרכוס סאסר", "Bobi Klintman": "בובי קלינטמן", "Camara Toumani": "טומאני קמארה",
    "Daniss Jenkins": "דניס ג'נקינס", "Cole Swider": "קול סווידר", "Alondes Williams": "אלונדס ויליאמס",

    # --- אינדיאנה פייסרס ---
    "Tyrese Haliburton": "טייריס הליברטון", "Pascal Siakam": "פסקל סיאקם", "Myles Turner": "מיילס טרנר", "Bennedict Mathurin": "בנדיקט מאת'ורין", "Aaron Nesmith": "ארון ניסמית'",
    "Andrew Nembhard": "אנדרו נבהארד", "Obi Toppin": "אובי טופין", "T.J. McConnell": "טי ג'יי מקונל", "Jarace Walker": "ג'ראס ווקר", "Ben Sheppard": "בן שפרד",
    "Isaiah Jackson": "איזאיה ג'קסון", "James Wiseman": "ג'יימס וייסמן", "Johnny Furphy": "ג'וני פרפי", "Kendall Brown": "קנדל בראון", "James Johnson": "ג'יימס ג'ונסון",
    "Enrique Freeman": "אנריקה פרימן", "Tristen Newton": "טריסטן ניוטון", "Quenton Jackson": "קוונטון ג'קסון",

    # --- מיאמי היט ---
    "Jimmy Butler": "ג'ימי באטלר", "Bam Adebayo": "באם אדבאיו", "Tyler Herro": "טיילר הירו", "Terry Rozier": "טרי רוזייר", "Jaime Jaquez Jr.": "חיימה חאקז",
    "Nikola Jovic": "ניקולה יוביץ'", "Kel'el Ware": "קלל וור", "Duncan Robinson": "דאנקן רובינסון", "Haywood Highsmith": "היווד הייסמית'", "Kevin Love": "קווין לאב",
    "Pelle Larsson": "פלה לארסון", "Josh Richardson": "ג'וש ריצ'רדסון", "Thomas Bryant": "תומאס בריאנט", "Alec Burks": "אלק ברקס", "Nassir Little": "נאסיר ליטל",
    "Dru Smith": "דרו סמית'", "Christopher Smith": "כריסטופר סמית'", "Keshad Johnson": "קשאד ג'ונסון",

    # --- מילווקי באקס ---
    "Giannis Antetokounmpo": "יאניס אנטטוקומפו", "Damian Lillard": "דמיאן לילארד", "Khris Middleton": "כריס מידלטון", "Brook Lopez": "ברוק לופז", "Bobby Portis": "בובי פורטיס",
    "Gary Trent Jr.": "גארי טרנט ג'וניור", "Delon Wright": "דלון רייט", "Pat Connaughton": "פאט קונאטון", "Taurean Prince": "טוריין פרינס", "AJ Johnson": "איי ג'יי ג'ונסון",
    "Tyler Smith": "טיילר סמית'", "Andre Jackson Jr.": "אנדרה ג'קסון ג'וניור", "MarJon Beauchamp": "מרג'ון בוצ'אמפ", "AJ Green": "איי ג'יי גרין", "Chris Livingston": "כריס ליבינגסטון",
    "Thanasis Antetokounmpo": "תנאסיס אנטטוקומפו", "Stanley Umude": "סטנלי אומודה", "Anzejs Pasecniks": "אנג'ייס פאסצ'ניקס",

    # --- מינסוטה טימברוולבס ---
    "Anthony Edwards": "אנתוני אדוארדס", "Julius Randle": "ג'וליוס רנדל", "Rudy Gobert": "רודי גובר", "Donte DiVincenzo": "דונטה דיווינצ'נזו", "Naz Reid": "נאז ריד",
    "Mike Conley": "מייק קונלי", "Jaden McDaniels": "ג'יידן מקדניאלס", "Rob Dillingham": "רוב דילינגהאם", "Nickeil Alexander-Walker": "ניקיל אלכסנדר-ווקר", "Joe Ingles": "ג'ו אינגלס",
    "Terrence Shannon Jr.": "טרנס שאנון ג'וניור", "Josh Minott": "ג'וש מינוט", "Leonard Miller": "לאונרד מילר", "Luka Garza": "לוקה גרזה", "PJ Dozier": "פי ג'יי דוזייר",
    "Daishen Nix": "דיישן ניקס", "Jesse Edwards": "ג'סי אדוארדס", "Jaylen Clark": "ג'יילן קלארק",

    # --- ניו אורלינס פליקנס ---
    "Zion Williamson": "זאיון ויליאמסון", "Brandon Ingram": "ברנדון אינגרם", "Dejounte Murray": "דז'ונטה מארי", "CJ McCollum": "סי.ג'יי מקולום", "Herb Jones": "הרב ג'ונס",
    "Trey Murphy III": "טריי מרפי", "Daniel Theis": "דניאל תייס", "Yves Missi": "איב מיסי", "Jordan Hawkins": "ג'ורדן הוקינס", "Jose Alvarado": "חוסה אלבראדו",
    "Javonte Green": "ג'בונטה גרין", "Jeremiah Robinson-Earl": "ג'רמיה רובינסון-ארל", "Antonio Reeves": "אנטוניו ריבס", "Karane Ingram": "קארן אינגרם", "Jamal Cain": "ג'מאל קיין",
    "Trey Jemison": "טריי ג'מיסון", "BJ Boston": "ברנדון בוסטון", "Elfrid Payton": "אלפריד פייטון",

    # --- ניו יורק ניקס ---
    "Jalen Brunson": "ג'יילן ברונסון", "Karl-Anthony Towns": "קארל-אנתוני טאונס", "OG Anunoby": "או ג'י אנונובי", "Mikal Bridges": "מיקאל ברידג'ס", "Josh Hart": "ג'וש הארט",
    "Miles McBride": "מיילס מקברייד", "Cameron Payne": "קמרון פיין", "Mitchell Robinson": "מיטשל רובינסון", "Precious Achiuwa": "פרשס אצ'יווה", "Jericho Sims": "ג'ריקו סימס",
    "Tyler Kolek": "טיילר קולק", "Pacome Dadiet": "פאקום דאדייה", "Landry Shamet": "לנדרי שאמט", "Kolek Tyler": "טיילר קולק", "Ariel Hukporti": "אריאל הוקפורטי",
    "Kevin McCullar Jr.": "קווין מקולר ג'וניור", "Jacob Toppin": "ג'ייקוב טופין", "Boo Buie": "בו בויי",

    # --- אורלנדו מג'יק ---
    "Paolo Banchero": "פאולו באנקרו", "Franz Wagner": "פרנץ ואגנר", "Jalen Suggs": "ג'יילן סאגס", "Kentavious Caldwell-Pope": "קנטביוס קולדוול-פופ", "Wendell Carter Jr.": "ונדל קרטר ג'וניור",
    "Cole Anthony": "קול אנתוני", "Jonathan Isaac": "ג'ונתן אייזק", "Moritz Wagner": "מוריץ ואגנר", "Anthony Black": "אנתוני בלאק", "Gary Harris": "גארי האריס",
    "Goga Bitadze": "גוגה ביטאדזה", "Tristan da Silva": "טריסטן דה סילבה", "Caleb Houstan": "קיילב יוסטן", "Jett Howard": "ג'ט הווארד", "Cory Joseph": "קורי ג'וזף",
    "Mac McClung": "מאק מקלנג", "Trevelin Queen": "טרבלין קווין", "Ethan Thompson": "איתן תומפסון",

    # --- פילדלפיה 76 ---
    "Joel Embiid": "ג'ואל אמביד", "Tyrese Maxey": "טייריס מקסי", "Paul George": "פול ג'ורג'", "Kelly Oubre Jr.": "קלי אוברה ג'וניור", "Caleb Martin": "קיילב מרטין",
    "Kyle Lowry": "קייל לאורי", "Andre Drummond": "אנדרה דראמונד", "Eric Gordon": "אריק גורדון", "Guerschon Yabusele": "גרשון יאבוסלה", "Jared McCain": "ג'ארד מקיין",
    "KJ Martin": "קיי.ג'יי מרטין", "Ricky Council IV": "ריקי קאונסיל", "Reggie Jackson": "רג'י ג'קסון", "Adem Bona": "אדם בונה", "Lester Quinones": "לסטר קיניונס",
    "Jeff Dowtin Jr.": "ג'ף דאוטן", "Justin Edwards": "ג'סטין אדוארדס", "David Jones": "דייוויד ג'ונס",

    # --- סקרמנטו קינגס ---
    "De'Aaron Fox": "דיארון פוקס", "Domantas Sabonis": "דומנטאס סאבוניס", "Demar DeRozan": "דמאר דרוזן", "Keegan Murray": "קיגן מארי", "Malik Monk": "מליק מונק",
    "Kevin Huerter": "קווין הרטר", "Keon Ellis": "קיון אליס", "Trey Lyles": "טריי ליילס", "Alex Len": "אלכס לן", "Devin Carter": "דווין קרטר",
    "Doug McDermott": "דאג מקדרמוט", "Jordan McLaughlin": "ג'ורדן מקלופלין", "Orlando Robinson": "אורלנדו רובינסון", "Colby Jones": "קולבי ג'ונס", "Isaac Jones": "אייזק ג'ונס",
    "Mason Jones": "מייסון ג'ונס", "Jalen McDaniels": "ג'יילן מקדניאלס", "Isaiah Crawford": "איזאיה קרופורד",

    # --- טורונטו ראפטורס ---
    "Scottie Barnes": "סקוטי בארנס", "RJ Barrett": "אר ג'יי בארט", "Immanuel Quickley": "עמנואל קוויקלי", "Jakob Poeltl": "יאקוב פולטל", "Gradey Dick": "גריידי דיק",
    "Kelly Olynyk": "קלי אוליניק", "Davion Mitchell": "דוביון מיצ'ל", "Ochai Agbaji": "אוצ'אי אגבאג'י", "Bruce Brown": "ברוס בראון", "Chris Boucher": "כריס בושה",
    "Ja'Kobe Walter": "ג'ייקובי וולטר", "Jonathan Mogbo": "ג'ונתן מוגבו", "Jamal Shead": "ג'מאל שיד", "Bruno Fernando": "ברונו פרננדו", "Garrett Temple": "גארט טמפל",
    "Ulrich Chomche": "אולריך שומשה", "DJ Carton": "די.ג'יי קארטון", "Jared Rhoden": "ג'ארד רודן",

    # --- יוטה ג'אז ---
    "Lauri Markkanen": "לאורי מארקנן", "Collin Sexton": "קולין סקסטון", "John Collins": "ג'ון קולינס", "Walker Kessler": "ווקר קסלר", "Keyonte George": "קיאנטה ג'ורג'",
    "Jordan Clarkson": "ג'ורדן קלארקסון", "Cody Williams": "קודי ויליאמס", "Taylor Hendricks": "טיילור הנדריקס", "Brice Sensabaugh": "ברייס סנסאבו", "Isaiah Collier": "איזאיה קולייר",
    "Kyle Filipowski": "קייל פיליפובסקי", "Drew Eubanks": "דרו יובנקס", "Johnny Juzang": "ג'וני ג'וזאנג", "Svi Mykhailiuk": "סבי מיכאיליוק", "Patty Mills": "פאטי מילס",
    "Micah Potter": "מייקה פוטר", "Jason Preston": "ג'ייסון פרסטון", "Oscar Tshiebwe": "אוסקר טשיבווה",

    # --- וושינגטון וויזארדס ---
    "Kyle Kuzma": "קייל קוזמה", "Jordan Poole": "ג'ורדן פול", "Alex Sarr": "אלכס סאר", "Bub Carrington": "באב קרינגטון", "Bilal Coulibaly": "בילאל קוליבאלי",
    "Malcolm Brogdon": "מלקולם ברוגדון", "Jonas Valanciunas": "יונאס ולנצ'יונאס", "Corey Kispert": "קורי קיספרט", "Kyshawn George": "קישון ג'ורג'", "Marvin Bagley III": "מרווין באגלי",
    "Saddiq Bey": "סדיק ביי", "Richaun Holmes": "רשון הולמס", "Johnny Davis": "ג'וני דייוויס", "Anthony Gill": "אנתוני גיל", "Patrick Baldwin Jr.": "פטריק בולדווין",
    "Jared Butler": "ג'ארד באטלר", "Tristan Vukcevic": "טריסטן ווקצ'ביץ'", "Justin Champagnie": "ג'סטין שמפאני",

    # --- גולדן סטייט ווריורס ---
    "Stephen Curry": "סטף קרי", "Draymond Green": "דריימונד גרין", "Jonathan Kuminga": "ג'ונתן קומינגה", "Andrew Wiggins": "אנדרו ויגינס", "Brandin Podziemski": "ברנדין פודז'מסקי",
    "Buddy Hield": "באדי הילד", "De'Anthony Melton": "דיאנתוני מלטון", "Kyle Anderson": "קייל אנדרסון", "Trayce Jackson-Davis": "טרייס ג'קסון-דייוויס", "Moses Moody": "מוזס מודי",
    "Kevon Looney": "קאבון לוני", "Gary Payton II": "גארי פייטון ג'וניור", "Lindy Waters III": "לינדי ווטרס", "Gui Santos": "גאי סנטוס", "Quint Post": "קווינטן פוסט",
    "Pat Spencer": "פט ספנסר", "Reece Beekman": "ריס ביקמן", "Jerome Robinson": "ג'רום רובינסון",

    # --- לוס אנג'לס קליפרס ---
    "James Harden": "ג'יימס הארדן", "Kawhi Leonard": "קוואי לנארד", "Norman Powell": "נורמן פאוול", "Ivica Zubac": "איביצה זובאץ", "Derrick Jones Jr.": "דריק ג'ונס ג'וניור",
    "Terance Mann": "טרנס מאן", "Kevin Porter Jr.": "קווין פורטר ג'וניור", "Kris Dunn": "קריס דאן", "Nicolas Batum": "ניקולא באטום", "Amir Coffey": "אמיר קופי",
    "Mo Bamba": "מו במבה", "PJ Tucker": "פי.ג'יי טאקר", "Bones Hyland": "בונז היילנד", "Kai Jones": "קאי ג'ונס", "Jordan Miller": "ג'ורדן מילר",
    "Cam Christie": "קאם כריסטי", "Kobe Brown": "קובי בראון", "Trentyn Flowers": "טרנטין פלאוורס",

    # --- דנבר נאגטס ---
    "Nikola Jokic": "ניקולה יוקיץ'", "Jamal Murray": "ג'מאל מארי", "Michael Porter Jr.": "מייקל פורטר ג'וניור", "Aaron Gordon": "ארון גורדון", "Russell Westbrook": "ראסל ווסטברוק",
    "Christian Braun": "כריסטיאן בראון", "Peyton Watson": "פייטון ווטסון", "Dario Saric": "דאריו שאריץ'", "Julian Strawther": "ג'וליאן סטראותר", "DeAndre Jordan": "דיאנדרה ג'ורדן",
    "Zeke Nnaji": "זיק נאג'י", "Hunter Tyson": "האנטר טייסון", "Vlatko Cancar": "בלאטקו צ'נצ'אר", "DaRon Holmes II": "דארון הולמס", "Jalen Pickett": "ג'יילן פיקט",
    "Trey Alexander": "טריי אלכסנדר", "PJ Hall": "פי ג'יי הול", "Spencer Jones": "ספנסר ג'ונס",

    # --- שמות להוספה ---
    "DeMar DeRozan": "דמאר דרוזן", "Tidjane Salaün": "טיג'אן סאלון", "Kristaps Porziņģis": "קריסטאפס פורזינגיס", "VJ Edgecombe": "וי.ג'יי אדג'קום",

}

BAD_TRANSLATIONS_FIXES = {
    "שחור דולף": "נאסיר ליטל", "ירמיהו פחד": "ג'רמיה פירס", "ישעיהו הרטנשטיין": "אייזיאה הרטנשטיין",
    "ישעיהו ליברס": "אייזיאה ליברס", "ישעיהו סטיבנס": "אייזיאה סטיבנס", "ג'רן ג'קסון": "ג'רן ג'קסון ג'וניור",
    "ברוקס ברנייזר": "ברוקס בארנהייזר", "ג'ייק לרביה": "ג'ייק לארייביה", "דרו טים": "דרו טימי",
    "מקסים ריינאו": "מקסים ריינו"
}

PLAYER_PHOTOS = {
    # --- טורונטו ראפטורס (TOR) ---
    "Scottie Barnes": "https://pbs.twimg.com/media/GQ2kGz0W0AA6WnZ?format=jpg&name=4096x4096", # סקוטי בארנס
    "Immanuel Quickley": "https://pbs.twimg.com/media/GRKkH09WwAAls2P?format=jpg&name=4096x4096", # עמנואל קוויקלי
    "RJ Barrett": "https://pbs.twimg.com/media/HFxDNj5XQAA0Ssh?format=jpg&name=900x900", # אר ג'יי בארט
    "Brandon Ingram": "https://pbs.twimg.com/media/HFgd9wZXAAA7vtH?format=png&name=900x900", # ברנדון אינגרם (עבר לטורונטו)

    # --- פילדלפיה 76 (PHI) ---
    "Joel Embiid": "https://pbs.twimg.com/media/Gi_Y0rXXUAAesyw?format=jpg&name=small", # ג'ואל אמביד
    "Paul George": "https://pbs.twimg.com/media/HFBkIV_bMAAtkJ4?format=jpg&name=900x900", # פול ג'ורג'
    "Tyrese Maxey": "https://pbs.twimg.com/media/GbzB1sFWEAsJ-qm?format=jpg&name=large", # טייריס מקסי
    "V.J. Edgecombe": "https://pbs.twimg.com/media/G8lFpK2XcAE20MB?format=jpg&name=medium", # וי ג'יי אדג'קום

    # --- אורלנדו מג'יק (ORL) ---
    "Paolo Banchero": "https://pbs.twimg.com/media/HEYXKEtWQAAsvRJ?format=jpg&name=4096x4096", # פאולו באנקרו
    "Desmond Bane": "https://pbs.twimg.com/media/HFCk3GObUAA-ZPS?format=jpg&name=large", # דזמונד ביין (עבר לאורלנדו)
    "Franz Wagner": "https://pbs.twimg.com/media/HEht1_ubwAAbTr7?format=jpg&name=medium",
    "Anthony Black": "https://pbs.twimg.com/media/G92xPPeWYAA3zNs?format=jpg&name=large", # אנתוני בלאק

    # --- אטלנטה הוקס (ATL) ---
    "Jalen Johnson": "https://pbs.twimg.com/media/HEdWYpEaYAAjsLp?format=jpg&name=4096x4096",
    "C.J. McCollum": "https://pbs.twimg.com/media/HFDyZBkWQAANpGb?format=jpg&name=large",
    "Jonathan Kuminga": "https://pbs.twimg.com/media/HCBaan5bcAA7fTP?format=jpg&name=4096x4096",
    "Dyson Daniels": "https://pbs.twimg.com/media/HFBtqW3boAApV26?format=jpg&name=large",
    "Nickeil Alexander-Walker": "https://pbs.twimg.com/media/HE3TGiNbQAATlRD?format=png&name=900x900",

    # --- פורטלנד טרייל בלייזרס (POR) ---
    "Deni Avdija": "https://pbs.twimg.com/media/HFGSriabwAA6jEP?format=jpg&name=large",
    "Jrue Holiday": "https://pbs.twimg.com/media/HE9WF-6WoAA0FZ3?format=jpg&name=large",
    "Scoot Henderson": "https://pbs.twimg.com/media/HDWBwvSasAAaq-U?format=jpg&name=large",
    "Shaedon Sharpe": "https://pbs.twimg.com/media/G8s37tHWEAE-Il2?format=jpg&name=medium",
    "Toumani Camara": "https://pbs.twimg.com/media/HE_c3NzW4AAdAtH?format=jpg&name=4096x4096",
    "Donovan Clingan": "https://pbs.twimg.com/media/HD5ZLK_XEAAYf-J?format=png&name=900x900",
    "Jerami Grant": "https://pbs.twimg.com/media/HD5sFEJboAEx5MY?format=png&name=900x900",

    # --- ניו יורק ניקס (NYK) ---
    "Jalen Brunson": "https://pbs.twimg.com/media/HDS9_92XQAEDtUw?format=jpg&name=large",
    "Karl-Anthony Towns": "https://pbs.twimg.com/media/HFBCrBVXEAAc6Nq?format=jpg&name=small",
    "OG Anunoby": "https://pbs.twimg.com/media/GDcyl68aAAAQ_WR?format=jpg&name=large",
    "Josh Hart": "https://pbs.twimg.com/media/GHyvj-4aYAA0aoq?format=jpg&name=4096x4096",

    # --- לוס אנג'לס לייקרס (LAL) ---
    "Luka Doncic": "https://pbs.twimg.com/media/HEyyfuRXcAIfvk1?format=jpg&name=large",
    "LeBron James": "https://pbs.twimg.com/media/HEuD_HjbMAA6i5v?format=jpg&name=large",
    "Austin Reaves": "https://pbs.twimg.com/media/HCi-STObIAALKq4?format=jpg&name=large",
    "Luke Kennard": "https://pbs.twimg.com/media/HC6_x8Oa4AA9fZg?format=jpg&name=large",
    "Deandre Ayton": "https://pbs.twimg.com/media/HFY8UZhWkAA8HN9?format=jpg&name=large",
    "Rui Hachimura": "https://pbs.twimg.com/media/Fz6V0kYWYAE91_S?format=jpg&name=4096x4096",

    # --- פיניקס סאנס (PHX) ---
    "Devin Booker": "https://pbs.twimg.com/media/HErmPOCawAA6E52?format=jpg&name=small",
    "Jalen Green": "https://pbs.twimg.com/media/HErmPOCawAA6E52?format=jpg&name=small",
    "Dillon Brooks": "https://pbs.twimg.com/media/HE7UfEXacAAgI_G?format=jpg&name=large",
    "Grayson Allen": "https://pbs.twimg.com/media/HF00xFVasAUdizB?format=jpg&name=large",

    # --- בוסטון סלטיקס (BOS) ---
    "Jayson Tatum": "https://pbs.twimg.com/media/HE3UmrYbUAE2mnN?format=jpg&name=900x900",
    "Jaylen Brown": "https://pbs.twimg.com/media/G7NwhP8WMAAs3zg?format=jpg&name=4096x4096",
    "Derrick White": "https://pbs.twimg.com/media/GlUsMUdXUAAaRq6?format=jpg&name=4096x4096",
    "Payton Pritchard": "https://pbs.twimg.com/media/GlUsLkFaIAAj6_i?format=jpg&name=4096x4096",
    "Neemias Queta": "https://pbs.twimg.com/media/HFMIwKXaYAAgGq6?format=jpg&name=4096x4096",

    # --- אינדיאנה פייסרס (IND) ---
    "Ivica Zubac": "https://pbs.twimg.com/media/HD4r0qvbYAAN44M?format=jpg&name=4096x4096",
    "Pascal Siakam": "https://pbs.twimg.com/media/GL7hFFiW4AAOdID?format=jpg&name=small",
    "Andrew Nembhard": "https://pbs.twimg.com/media/HFAUUMhXAAACuXc?format=jpg&name=small",
    "Duncan Robinson": "https://pbs.twimg.com/media/HEKI4zOXAAA5alk?format=jpg&name=large",

    # --- יוסטון רוקטס (HOU) ---
    "Alperen Sengun": "https://pbs.twimg.com/media/HDvmRFhXwAE2TZJ?format=jpg&name=large",
    "Kevin Durant": "https://pbs.twimg.com/media/G31F5X9WsAAELmJ?format=jpg&name=large",
    "Amen Thompson": "https://pbs.twimg.com/media/HFXDVJSX0AAxnMC?format=png&name=900x900",
    "Reed Sheppard": "https://pbs.twimg.com/media/HEyU4yUWMAASlUd?format=jpg&name=large",
    "Jabari Smith Jr.": "https://pbs.twimg.com/media/HExpXj4WwAAO1S_?format=jpg&name=large",
    "Tari Eason": "https://pbs.twimg.com/media/Fn907YkaUAEMIZv?format=jpg&name=900x900",

    # --- שארלוט הורנטס (CHA) ---
    "LaMelo Ball": "https://pbs.twimg.com/media/HFLzHA2WAAErS4C?format=jpg&name=small",
    "Coby White": "https://pbs.twimg.com/media/HE9T5e5WcAAXUbU?format=jpg&name=small",
    "Kon Knueppel": "https://pbs.twimg.com/media/HFDbM0WXcAAfizY?format=jpg&name=small",
    "Brandon Miller": "https://pbs.twimg.com/media/HD4YQaxWYAAIrqo?format=jpg&name=medium",
    "Miles Bridges": "https://pbs.twimg.com/media/HE8YBE_bwAAnSBM?format=jpg&name=medium",

    # --- סן אנטוניו ספרס (SAS) ---
    "De'Aaron Fox": "https://pbs.twimg.com/media/HFF_wLcaoAAaG3e?format=jpg&name=small",
    "Victor Wembanyama": "https://pbs.twimg.com/media/HE4BF_XbAAAG1Rn?format=jpg&name=large",
    "Stephon Castle": "https://pbs.twimg.com/media/HDQdkthXAAAuQWe?format=jpg&name=4096x4096",
    "Dylan Harper": "https://pbs.twimg.com/media/HFRPUCYbcAA9Rcl?format=jpg&name=large",
    "Devin Vassell": "https://pbs.twimg.com/media/G6vRmQFW4AAb-oU?format=jpg&name=medium",

    # --- גולדן סטייט ווריורס (GSW) ---
    "Stephen Curry": "https://pbs.twimg.com/media/HGAYmaLXcAAoK39?format=jpg&name=large",
    "Draymond Green": "https://pbs.twimg.com/media/HDki7SYXoAAGSl6?format=jpg&name=large",
    "Brandin Podziemski": "https://pbs.twimg.com/media/HEJD73qXwAECtyg?format=jpg&name=large",
    "Kristaps Porzingis": "https://pbs.twimg.com/media/HEoKtyjasAAgQOW?format=jpg&name=large",

    # --- דטרויט פיסטונס (DET) ---
    "Cade Cunningham": "https://pbs.twimg.com/media/HCg83iJXYAAeXNj?format=jpg&name=large",
    "Jalen Duren": "https://pbs.twimg.com/media/HE6ujcDW8AAKQzb?format=jpg&name=medium",
    "Daniss Jenkins": "https://pbs.twimg.com/media/HE8d7JYboAAmdjq?format=jpg&name=large",
    "Tobias Harris": "https://pbs.twimg.com/media/HFErsVXW4AEALYu?format=jpg&name=large",
    "Duncan Robinson": "https://pbs.twimg.com/media/G_YVq3cWkAEsUnX?format=jpg&name=large",

    # --- אוקלהומה סיטי ת'אנדר (OKC) ---
    "Shai Gilgeous-Alexander": "https://pbs.twimg.com/media/HEtr3e9XMAA5FTB?format=jpg&name=4096x4096",
    "Chet Holmgren": "https://pbs.twimg.com/media/F9hq_qmXAAAyK3F?format=jpg&name=small",
    "Jalen Williams": "https://pbs.twimg.com/media/HFL4YjkWYAERxSJ?format=jpg&name=large",
    "Isaiah Hartenstein": "https://pbs.twimg.com/media/G5NXZE0boAAgWuL?format=jpg&name=4096x4096",

    # --- קליבלנד קאבלירס (CLE) ---
    "Donovan Mitchell": "https://i.iheart.com/v3/re/assets.getty/69d39478e34e77ebb4e689bb?ops=max(1060,0),quality(80)",
    "James Harden": "https://pbs.twimg.com/media/HCWruXfXUAE6zo8?format=jpg&name=large",
    "Evan Mobley": "https://pbs.twimg.com/media/GlDQARJWcAAs_bu?format=jpg&name=large",

    # --- מינסוטה טימברוולבס (MIN) ---
    "Anthony Edwards": "https://pbs.twimg.com/media/GoXE3iDXwAA9Y58?format=jpg&name=large",
    "Julius Randle": "https://pbs.twimg.com/media/GatbPLdWkAAtExz?format=jpg&name=4096x4096",
    "Naz Reid": "https://pbs.twimg.com/media/G-pV2b5aYAArzJf?format=jpg&name=medium",
    "Ayo Dosunmu": "https://pbs.twimg.com/media/HFPn_2KbIAANWWy?format=png&name=900x900",
    "Jaden McDaniels": "https://pbs.twimg.com/media/HGC3fH_XAAAKR0r?format=jpg&name=medium",
    "Rudy Gobert": "https://pbs.twimg.com/media/G44NY0fakAA33lt?format=jpg&name=large",

    # --- ברוקלין נטס (BKN) ---
    "Ben Saraf": "https://pbs.twimg.com/media/HET8BYNXMAAI9zl?format=jpg&name=small",
    "Danny Wolf": "https://pbs.twimg.com/media/HCXLU3mbAAAd_Ma?format=jpg&name=small",

    # --- ממפיס גריזליס (MEM) ---
    "Rayan Rupert": "https://pbs.twimg.com/media/HFK-IMba8AAOUqk?format=jpg&name=large",
    "Jaylen Wells": "https://pbs.twimg.com/media/HCh8V-JXoAAbdTD?format=jpg&name=large",

    # --- דאלאס מאבריקס (DAL) ---
    "Cooper Flagg": "https://pbs.twimg.com/media/HFOAjTZX0AApO14?format=jpg&name=small",

    # --- דנבר נאגטס (DEN) ---
    "Nikola Jokic": "https://pbs.twimg.com/media/HE6I760XUAAzL3U?format=jpg&name=medium",
    "Jamal Murray": "https://pbs.twimg.com/media/HC_bc_eXkAAEnAC?format=jpg&name=large",
    "Aaron Gordon": "https://pbs.twimg.com/media/HFSElLqbUAEZUWW?format=jpg&name=medium",
    "Christian Braun": "https://pbs.twimg.com/media/HFGEAHOaQAA0iB8?format=jpg&name=large",
}

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

                if "names" not in data:
                    data["names"] = {}
                if "games" not in data:
                    data["games"] = {}
                if "sent_events" not in data:
                    data["sent_events"] = {}

                return data
        except Exception as e:
            print(f"⚠️ שגיאה בטעינת cache: {e}")

    return {"names": {}, "games": {}, "sent_events": {}}
    
def save_cache():
    try:
        tmp_file = CACHE_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=4, ensure_ascii=False)
        os.replace(tmp_file, CACHE_FILE)
    except Exception as e:
        print(f"⚠️ שגיאה בשמירת cache: {e}")

cache = load_cache()

def make_event_key(game_id, event_type, period=None, away_score=None, home_score=None):
    parts = [str(game_id), str(event_type)]

    if period is not None:
        parts.append(f"p{period}")

    if away_score is not None and home_score is not None:
        parts.append(f"{int(away_score)}-{int(home_score)}")

    raw_key = "|".join(parts)
    return raw_key


def claim_event(event_key):
    """
    תופס אירוע בצורה אטומית.
    אם כבר נתפס בעבר - מחזיר False.
    אם זו הפעם הראשונה - יוצר קובץ ומחזיר True.
    """
    try:
        os.makedirs(SENT_EVENTS_DIR, exist_ok=True)

        digest = hashlib.sha256(event_key.encode("utf-8")).hexdigest()
        marker_path = os.path.join(SENT_EVENTS_DIR, f"{digest}.done")

        fd = os.open(marker_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)

        cache["sent_events"][digest] = {
            "event_key": event_key,
            "created_at": datetime.now().isoformat()
        }
        save_cache()

        return True

    except FileExistsError:
        return False

    except Exception as e:
        print(f"❌ שגיאה ב-claim_event: {e}")
        return False

def translate_name(name):
    if not name:
        return ""

    # 1) אם השם כבר קיים במילון שחקנים
    if name in NBA_PLAYERS_HEB:
        return NBA_PLAYERS_HEB[name]

    # 2) אם זה שם קבוצה
    if name in NBA_TEAMS_HEBREW:
        return NBA_TEAMS_HEBREW[name]

    # 3) אם כבר שמרנו תרגום ידני/קודם
    if name in cache["names"]:
        cached_name = cache["names"][name]
        if cached_name in BAD_TRANSLATIONS_FIXES:
            fixed = BAD_TRANSLATIONS_FIXES[cached_name]
            cache["names"][name] = fixed
            save_cache()
            return fixed
        return cached_name

    try:
        clean_name = (
            name.replace("Jr.", "")
                .replace("III", "")
                .replace("II", "")
                .strip()
        )

        translated = translator.translate(clean_name)
        print(f"🌍 תרגום גוגל: {name} -> {translated}")

        # 4) תיקון תרגומים גרועים
        if translated in BAD_TRANSLATIONS_FIXES:
            translated = BAD_TRANSLATIONS_FIXES[translated]

        cache["names"][name] = translated
        save_cache()
        return translated

    except Exception as e:
        print(f"❌ Error translating {name}: {e}")
        return name

def get_player_photo(player):
    try:
        first = (player.get("firstName") or "").strip()
        last = (player.get("familyName") or "").strip()
        full_name = f"{first} {last}".strip()

        if not full_name:
            print("⚠️ אין שם שחקן")
            return None

        print(f"🔎 מחפש תמונה עבור: {full_name}")

        # בדיקה רגילה
        if full_name in PLAYER_PHOTOS:
            return PLAYER_PHOTOS[full_name]

        # נרמול תווים
        normalized = (
            full_name.replace("ć", "c")
                     .replace("č", "c")
                     .replace("š", "s")
                     .replace("ž", "z")
                     .replace("đ", "d")
                     .replace("ñ", "n")
                     .replace("é", "e")
                     .replace("á", "a")
                     .replace("ó", "o")
                     .replace("í", "i")
        )

        if normalized in PLAYER_PHOTOS:
            return PLAYER_PHOTOS[normalized]

        return None

    except Exception as e:
        print(f"❌ שגיאה בשליפת תמונת שחקן: {e}")
        return None

def get_stat_line(p):
    s = p.get('statistics', {})
    points = s.get('points', 0)
    rebounds = s.get('reboundsTotal', 0)
    assists = s.get('assists', 0)

    line = f"{points} נק', {rebounds} רב', {assists} אס'"

    if s.get('steals', 0) > 0:
        line += f", {s['steals']} חט'"
    if s.get('blocks', 0) > 0:
        line += f", {s['blocks']} חס'"

    return line

def to_num(v):
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def calculate_mvp_score(p):
    s = p.get("statistics", {})

    points = to_num(s.get("points"))
    rebounds = to_num(s.get("reboundsTotal"))
    assists = to_num(s.get("assists"))
    steals = to_num(s.get("steals"))
    blocks = to_num(s.get("blocks"))
    turnovers = to_num(s.get("turnovers"))
    plus_minus = to_num(s.get("plusMinus"))

    # נוסחה דטרמיניסטית ודי קרובה לתחושת "MVP"
    return (
        points * 5.0 +
        plus_minus * 3.0 +
        assists * 2.0 +
        rebounds * 1.8 +
        steals * 3.5 +
        blocks * 3.5 -
        turnovers * 2.5
    )


def mvp_sort_key(p):
    s = p.get("statistics", {})
    name = f"{p.get('firstName', '')} {p.get('familyName', '')}".strip().lower()

    try:
        pid = int(p.get("personId") or p.get("playerId") or 0)
    except Exception:
        pid = 0

    return (
        calculate_mvp_score(p),
        to_num(s.get("points")),
        to_num(s.get("plusMinus")),
        to_num(s.get("assists")),
        to_num(s.get("reboundsTotal")),
        to_num(s.get("steals")),
        to_num(s.get("blocks")),
        -to_num(s.get("turnovers")),
        -pid,
        name
    )

def format_msg(box, label, is_final=False, is_start=False, is_drama=False, drama_text=None):
    photo_url = None

    away, home = box['awayTeam'], box['homeTeam']

    a_full = translate_name(f"{away['teamCity']} {away['teamName']}")
    h_full = translate_name(f"{home['teamCity']} {home['teamName']}")

    period = box.get('period', 0)
    s_space = "ㅤ"

    combined_len = len(a_full) + len(h_full)
    padding = max(0, 22 - combined_len)

    if is_drama:
        header_emoji = "😱"
    elif is_final:
        header_emoji = "🏁"
    elif is_start:
        header_emoji = "🚀"
    else:
        header_emoji = "⏱️"

    header_text = f"{header_emoji} <b>{label}</b> {header_emoji}"
    msg = f"\u200f{header_text}\n"
    msg += f"\u200f🏀 <b>{a_full} 🆚 {h_full}</b> 🏀{s_space * padding}\n\n"

    # =========================
    # הודעת פתיחה
    # =========================
    if is_start:
        if period == 1:
            for team in [away, home]:
                t_full_name = translate_name(f"{team['teamCity']} {team['teamName']}")

                starters = [
                    translate_name(f"{p.get('firstName', '')} {p.get('familyName', '')}".strip())
                    for p in team.get('players', [])
                    if p.get('starter') == '1'
                ]

                out = [
                    translate_name(f"{p.get('firstName', '')} {p.get('familyName', '')}".strip())
                    for p in team.get('players', [])
                    if p.get('status') == 'INACTIVE'
                ]

                msg += f"\u200f🏀 <b>{t_full_name}</b>\n"
                msg += f"\u200f📍 <b>חמישייה:</b> {', '.join(starters) if starters else 'טרם פורסם'}\n"
                if out:
                    msg += f"\u200f❌ <b>חיסורים:</b> {', '.join(out[:5])}\n"
                msg += "\n"

        return msg, None

    # =========================
    # הודעת דרמה
    # =========================
    away_score = int(away.get('score', 0))
    home_score = int(home.get('score', 0))
    score_str = f"<b>{max(away_score, home_score)} - {min(away_score, home_score)}</b>"

    if is_drama:
        if drama_text is None:
            drama_text = f"טירוף! שוויון {score_str} הולכים להארכה!"
        msg += f"\u200f🔥 <b>{drama_text}</b> 🔥\n\n"
        return msg, None

    # =========================
    # כותרת תוצאה
    # =========================
    if away_score == home_score:
        msg += f"\u200f🔥 <b>שוויון {score_str}</b> 🔥\n\n"
    else:
        leader_name = a_full if away_score > home_score else h_full
        win_emoji = "🏆" if is_final else "🔥"

        if is_final:
            diff = abs(away_score - home_score)

            if diff >= 25:
                action = "מפרקת"
            elif diff >= 15:
                action = "מביסה"
            else:
                action = "מנצחת"
        else:
            action = "מובילה"

        msg += f"\u200f{win_emoji} <b>{leader_name} {action} {score_str}</b> {win_emoji}\n\n"

    # =========================
    # כמה שחקנים להציג
    # =========================
    count = 3 if is_final else 2

    for team in [away, home]:
        t_full_stats = translate_name(f"{team['teamCity']} {team['teamName']}")
        msg += f"\u200f📍 <b>{t_full_stats}:</b>\n"

        players_with_points = [
            p for p in team.get('players', [])
            if p.get('statistics', {}).get('points', 0) > 0
        ]

        top = sorted(
            players_with_points,
            key=lambda x: x.get('statistics', {}).get('points', 0),
            reverse=True
        )[:count]

        if not top:
            msg += "\u200fאין עדיין סטטיסטיקה בולטת\n\n"
            continue

        for i, p in enumerate(top):
            medal = ["🥇", "🥈", "🥉"][i]
            player_name = translate_name(f"{p.get('firstName', '')} {p.get('familyName', '')}".strip())
            msg += f"\u200f{medal} <b>{player_name}</b>: {get_stat_line(p)}\n"

        msg += "\n"

    # =========================
    # MVP רק בסיום משחק
    # =========================
    if is_final:
        away_score = int(away.get("score", 0))
        home_score = int(home.get("score", 0))

        if away_score > home_score:
            candidates = [p for p in away.get("players", []) if p.get("statistics")]
        elif home_score > away_score:
            candidates = [p for p in home.get("players", []) if p.get("statistics")]
        else:
            candidates = [p for p in (away.get("players", []) + home.get("players", [])) if p.get("statistics")]

        if candidates:
            mvp = sorted(candidates, key=mvp_sort_key, reverse=True)[0]
            mvp_name = translate_name(f"{mvp.get('firstName', '')} {mvp.get('familyName', '')}".strip())

            msg += f"\u200f🏆 <b>ה-MVP של המשחק: {mvp_name}</b>\n"
            msg += f"\u200f📊 {get_stat_line(mvp)}\n"

            # חיפוש תמונה ל-MVP
            photo_url = get_player_photo(mvp)

    return msg, photo_url

def send_telegram(text, photo_url=None, event_key=None):
    global CURRENT_SHABBAT_OR_YOM_TOV

    if CURRENT_SHABBAT_OR_YOM_TOV:
        print("⏸️ שבת/חג פעיל - ההודעה לא נשלחה")
        return False

    if event_key:
        if not claim_event(event_key):
            print("🚫 נחסמה הודעה כפולה (event already claimed)")
            return False

    payload = {"chat_id": CHAT_ID, "parse_mode": "HTML"}

    safe_text = html.escape(text)
    safe_text = safe_text.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")

    try:
        if photo_url:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                data={**payload, "photo": photo_url, "caption": safe_text},
                timeout=20
            )
        else:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                data={**payload, "text": safe_text},
                timeout=15
            )

        if r.status_code == 200:
            print("📨 נשלח (מאושר)")
            return True

        print(f"❌ טלגרם החזיר סטטוס {r.status_code}: {r.text}")
        return False

    except Exception as e:
        print(f"❌ שגיאה בשליחה: {e}")
        return False
        
def safe_get_json(url, timeout=10):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"❌ שגיאה בבקשת JSON: {url} | {e}")
        return None

def get_boxscore(gid):
    url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
    data = safe_get_json(url, timeout=10)
    if not data or "game" not in data:
        print(f"⚠️ boxscore לא תקין עבור משחק {gid}")
        return None
    return data

def run():
    global CURRENT_SHABBAT_OR_YOM_TOV

    print("🚀 בוט NBA משודרג - גרסה מלאה- כולל הארכותי!")

    first_run = True

    while True:
        try:
            current_time = datetime.now().strftime("%H:%M:%S")
            print(f"🔍 [{current_time}] סורק משחקים...")

            CURRENT_SHABBAT_OR_YOM_TOV = is_shabbat_or_yom_tov()

            try:
                resp_raw = requests.get(NBA_URL, headers=HEADERS, timeout=10)
                if resp_raw.status_code != 200:
                    print(f"❌ שגיאת API: {resp_raw.status_code}")
                    time.sleep(10)
                    continue

                resp = resp_raw.json()
            except Exception as e:
                print(f"❌ שגיאה בשליפת scoreboard: {e}")
                time.sleep(10)
                continue

            games = resp.get('scoreboard', {}).get('games', [])

            # =======================
            # סיבוב ראשון (ללא שליחה)
            # =======================
            if first_run:
                print("⚡ אתחול ראשוני - לא נשלחות הודעות")

                for g in games:
                    gid = g.get('gameId')
                    if not gid:
                        continue

                    status = g.get('gameStatus')
                    period = g.get('period', 0)
                    txt = (g.get('gameStatusText') or '').lower()

                    if gid not in cache["games"]:
                        cache["games"][gid] = []

                    log = cache["games"][gid]

                    if status == 2:
                        if period in [1, 3] and f"q{period}" in txt:
                            log.append(f"start_q{period}")

                        if "half" in txt:
                            log.append(txt)
                        if "end" in txt:
                            log.append(txt)

                        if period == 4:
                            log.append("drama_q4")

                        if period > 4:
                            log.append(f"drama_ot_{period}")

                    elif status == 3:
                        log.append("FINAL_SENT")

                    cache["games"][gid] = log[-50:]

                save_cache()
                first_run = False
                continue

            # =======================
            # לולאת משחקים
            # =======================
            for g in games:
                gid = g.get('gameId')
                if not gid:
                    continue

                status = g.get('gameStatus')
                period = g.get('period', 0)
                txt = (g.get('gameStatusText') or '').lower()

                if gid not in cache["games"]:
                    cache["games"][gid] = []

                log = cache["games"][gid]
                game_final_key = "FINAL_SENT"

                def get_boxscore():
                    try:
                        r = requests.get(
                            f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json",
                            headers=HEADERS,
                            timeout=10
                        )
                        if r.status_code != 200:
                            print(f"❌ שגיאת boxscore {gid}")
                            return None
                        return r.json()
                    except Exception as e:
                        print(f"❌ שגיאת boxscore: {e}")
                        return None

                # =======================
                # פתיחת רבע
                # =======================
                if status == 2 and period in [1, 3] and f"q{period}" in txt:
                    s_key = f"start_q{period}"
                
                    if s_key not in log:
                        b_resp = get_boxscore()
                        if not b_resp:
                            continue
                
                        label = "המשחק יצא לדרך!" if period == 1 else f"רבע {period} יצא לדרך!"
                        m, p = format_msg(b_resp['game'], label, is_start=True)
                        event_key = make_event_key(gid, f"start_q{period}", period=period)
                        send_telegram(m, p, event_key=event_key)
                        log.append(s_key)
                
                # =======================
                # מחצית
                # =======================
                if status == 2 and "half" in txt and txt not in log:
                    b_resp = get_boxscore()
                    if not b_resp:
                        continue
                
                    m, p = format_msg(b_resp['game'], "סיום מחצית")
                    event_key = make_event_key(gid, "halftime", period=period)
                    send_telegram(m, p, event_key=event_key)
                    log.append(txt)
                
                # =======================
                # סיום רבעים
                # =======================
                elif status == 2 and "end" in txt and period < 4 and txt not in log:
                    b_resp = get_boxscore()
                    if not b_resp:
                        continue
                
                    m, p = format_msg(b_resp['game'], f"סיום רבע {period}")
                    event_key = make_event_key(gid, "end_quarter", period=period)
                    send_telegram(m, p, event_key=event_key)
                
                    log.append(txt)
                
                # =======================
                # סיום רבע 4
                # =======================
                elif status == 2 and "end" in txt and period == 4 and txt not in log:
                    b_resp = get_boxscore()
                    if not b_resp:
                        continue
                
                    game_data = b_resp['game']
                    try:
                        home_score = int(game_data.get('homeTeam', {}).get('score', 0))
                        away_score = int(game_data.get('awayTeam', {}).get('score', 0))
                    except:
                        continue
                
                    if home_score == away_score:
                        m, p = format_msg(game_data, "סיום רבע 4")
                        event_key = make_event_key(gid, "end_quarter", period=4, away_score=away_score, home_score=home_score)
                        send_telegram(m, p, event_key=event_key)
                
                        log.append(txt)
                
                        if "drama_q4" not in log:
                            drama_txt = f"טירוף! שוויון {home_score} - {away_score} הולכים להארכה!"
                            m, p = format_msg(
                                game_data,
                                "דרמה ב-NBA!",
                                is_drama=True,
                                drama_text=drama_txt
                            )
                            event_key = make_event_key(gid, "drama_q4", period=4, away_score=away_score, home_score=home_score)
                            send_telegram(m, p, event_key=event_key)
                
                            log.append("drama_q4")
                    else:
                        log.append(txt)
                
                # =======================
                # הארכות
                # =======================
                elif status == 2 and "end" in txt and period > 4 and txt not in log:
                    b_resp = get_boxscore()
                    if not b_resp:
                        continue
                
                    game_data = b_resp['game']
                    try:
                        home_score = int(game_data.get('homeTeam', {}).get('score', 0))
                        away_score = int(game_data.get('awayTeam', {}).get('score', 0))
                    except:
                        continue
                
                    ot_num = period - 4
                
                    if home_score != away_score:
                        log.append(txt)
                    else:
                        label_ot = "סיום הארכה" if ot_num == 1 else f"סיום הארכה {ot_num}"
                        m, p = format_msg(game_data, label_ot)
                
                        event_key = make_event_key(gid, "end_ot", period=period, away_score=away_score, home_score=home_score)
                        send_telegram(m, p, event_key=event_key)
                
                        log.append(txt)
                
                        drama_key = f"drama_ot_{period}"
                        if drama_key not in log:
                            drama_txt = f"טירוף! שוויון {home_score} - {away_score} הולכים להארכה {ot_num + 1}!"
                            m, p = format_msg(
                                game_data,
                                "דרמה ב-NBA!",
                                is_drama=True,
                                drama_text=drama_txt
                            )
                            event_key = make_event_key(gid, f"drama_ot_{period}", period=period, away_score=away_score, home_score=home_score)
                            send_telegram(m, p, event_key=event_key)
                
                            log.append(drama_key)
                
                # =======================
                # סיום משחק
                # =======================
                if status == 3 and game_final_key not in log:
                    b_resp = get_boxscore()
                    if not b_resp:
                        continue
                
                    game_data = b_resp['game']
                    final_period = game_data.get('period', 4)
                    label_final = "סיום המשחק"
                
                    if final_period > 4:
                        label_final += f" (אחרי הארכה {final_period - 4})"
                
                    away_score = int(game_data.get('awayTeam', {}).get('score', 0))
                    home_score = int(game_data.get('homeTeam', {}).get('score', 0))
                
                    m, p = format_msg(game_data, label_final, is_final=True)
                    event_key = make_event_key(gid, "final", period=final_period, away_score=away_score, home_score=home_score)
                    send_telegram(m, p, event_key=event_key)
                
                    log.append(game_final_key)

                # שמירה + חיתוך log
                cache["games"][gid] = log[-50:]

            save_cache()

        except Exception as e:
            print(f"❌ שגיאה כללית בלולאה: {e}")

        time.sleep(10)

if __name__ == "__main__":
    print("🚀 RUN STARTED")
    run()

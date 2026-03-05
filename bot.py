import requests
import time
import json
import os
from datetime import datetime
from deep_translator import GoogleTranslator

# ==========================================
# הגדרות מערכת וטוקנים
# ==========================================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
CACHE_FILE = "nba_cache.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}

translator = GoogleTranslator(source='en', target='iw')

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
    "Deni Avdija": "דני אבדיה", "Jrue Holiday": "ג'רו הולידיי", "Jerami Grant": "ג'ראמי גרנט", "Scoot Henderson": "סקוט הנדרסון", "Donovan Clingan": "דונובן קלינגן",
    "Shaedon Sharpe": "שיידון שארפ", "Damian Lillard": "דמיאן לילארד", "Yang Hansen": "יאנג הנסן", "Vit Krejci": "ויט קרייצ'י", "Toumani Camara": "טומאני קמארה",
    "Matisse Thybulle": "מטיס תייבול", "Kris Murray": "קריס מארי", "Blake Wesley": "בלייק וסלי", "Robert Williams III": "רוברט ויליאמס", "Rayan Rupert": "ראיין רופרט",
    "Sidy Cissoko": "סידי סיסוקו", "Caleb Love": "קאלב לאב", "Bobi Klintman": "בובי קלינטמן",

    # --- אוקלוהומה סיטי ת'אנדר ---
    "Shai Gilgeous-Alexander": "שיי גילג'ס-אלכסנדר", "Chet Holmgren": "צ'ט הולמגרן", "Jalen Williams": "ג'יילן ויליאמס", "Alex Sarr": "אלכס סאר", "Cason Wallace": "קייסון וואלאס",
    "Luguentz Dort": "לוגנץ דורט", "Isaiah Joe": "איזאיה ג'ו", "Jaylin Williams": "ג'יילין ויליאמס", "Aaron Wiggins": "ארון ויגינס", "Ousmane Dieng": "אוסמן דיינג",
    "Kenrich Williams": "קנריץ' ויליאמס", "Dillon Jones": "דילון ג'ונס", "Ajay Mitchell": "אג'יי מיצ'ל", "Nikola Topic": "ניקולה טופיץ'", "Adam Flagler": "אדם פלאגלר",
    "Keyontae Johnson": "קיאנטה ג'ורג'", "Malevy Leons": "מאלבי לאונס", "Branden Carlson": "ברנדן קרלסון",

    # --- קליבלנד קאבלירס ---
    "James Harden": "ג'יימס הארדן", "Donovan Mitchell": "דונובן מיצ'ל", "Evan Mobley": "אוון מובלי", "Jarrett Allen": "ג'ארט אלן", "Caris LeVert": "קאריס לוורט",
    "Dennis Schroder": "דניס שרודר", "Max Strus": "מקס סטרוס", "Isaac Okoro": "אייזק אוקורו", "Georges Niang": "ג'ורג' ניאנג", "Dean Wade": "דין וייד",
    "Sam Merrill": "סאם מריל", "Tyrese Proctor": "טייריס פרוקטור", "Keon Ellis": "קיון אליס", "Craig Porter Jr.": "קרייג פורטר ג'וניור", "Jaylon Tyson": "ג'יילן טייסון",
    "JT Thor": "ג'יי.טי ת'ור", "Luke Travers": "לוק טראברס", "Emoni Bates": "אמוני בייטס",

    # --- יוסטון רוקטס ---
    "Kevin Durant": "קווין דוראנט", "Alperen Sengun": "אלפרן שנגון", "Amen Thompson": "אמן תומפסון", "Reed Sheppard": "ריד שפרד", "Jabari Smith Jr.": "ג'בארי סמית' ג'וניור",
    "Tari Eason": "טארי איסון", "Cam Whitmore": "קאם ויטמור", "Dorian Finney-Smith": "דוריאן פיני-סמית'", "Clint Capela": "קלינט קפלה", "Josh Okogie": "ג'וש אוקוגי",
    "Aaron Holiday": "ארון הולידיי", "Jock Landale": "ג'וק לנדייל", "Jae'Sean Tate": "ג'יישון טייט", "Steven Adams": "סטיבן אדאמס", "Jack McVeigh": "ג'ק מקווי",
    "N'Faly Dante": "נפאלי דאנטה", "Jermaine Samuels": "ג'רמיין סמואלס", "Nate Williams": "נייט ויליאמס",

    # --- דאלאס מאבריקס ---
    "Luka Doncic": "לוקה דונצ'יץ'", "Kyrie Irving": "קיירי אירווינג", "P.J. Washington": "פי.ג'יי וושינגטון", "Dereck Lively II": "דרק לייבלי", "Klay Thompson": "קליי תומפסון",
    "Naji Marshall": "נאג'י מרשל", "Quentin Grimes": "קוונטין גריימס", "Daniel Gafford": "דניאל גאפורד", "Maxi Kleber": "מקסי קליבר", "Jaden Hardy": "ג'יידן הארדי",
    "Dwight Powell": "דווייט פאוול", "Dante Exum": "דאנטה אקסום", "Markieff Morris": "מרקיף מוריס", "Olivier-Maxence Prosper": "אוליבייה-מקסנס פרוספר", "A.J. Lawson": "איי.ג'יי לוסון",
    "Kessler Edwards": "קסלר אדוארדס", "Brandon Williams": "ברנדון ויליאמס", "Jazian Gortman": "ג'זיאן גורטמן",

    # --- בוסטון סלטיקס ---
    "Jayson Tatum": "ג'ייסון טייטום", "Jaylen Brown": "ג'יילן בראון", "Kristaps Porzingis": "קריסטאפס פורזינגיס", "Derrick White": "דריק וייט", "Anfernee Simons": "אנפרני סיימונס",
    "Payton Pritchard": "פייטון פריצ'רד", "Sam Hauser": "סאם האוזר", "Al Horford": "אל הורפורד", "Jordan Walsh": "ג'ורדן וולש", "Baylor Scheierman": "ביילור שיירמן",
    "Luke Kornet": "לוק קורנט", "Xavier Tillman": "קסבייר טילמן", "Neemias Queta": "נמיאס קייטה", "Jaden Springer": "ג'יידן ספרינגר", "Anton Watson": "אנטון ווטסון",
    "Drew Peterson": "דרו פיטרסון", "JD Davison": "ג'יי.די דייוויסון", "Ron Harper Jr.": "רון הארפר ג'וניור",

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
    "DJ Steward": "די.ג'יי סטיוארט", "E.J. Liddell": "אי.ג'יי לידל", "Kenneth Lofton Jr.": "קנת' לופטון ג'וניור",

    # --- אוקלהומה סיטי ת'אנדר ---
    "Shai Gilgeous-Alexander": "שיי גילג'ס-אלכסנדר", "Chet Holmgren": "צ'ט הולמגרן", "Jalen Williams": "ג'יילן ויליאמס", "Alex Sarr": "אלכס סאר", "Cason Wallace": "קייסון וואלאס",
    "Luguentz Dort": "לוגנץ דורט", "Isaiah Joe": "איזאיה ג'ו", "Jaylin Williams": "ג'יילין ויליאמס", "Aaron Wiggins": "ארון ויגינס", "Ousmane Dieng": "אוסמן דיינג",
    "Kenrich Williams": "קנריץ' ויליאמס", "Dillon Jones": "דילון ג'ונס", "Ajay Mitchell": "אג'יי מיצ'ל", "Nikola Topic": "ניקולה טופיץ'", "Adam Flagler": "אדם פלאגלר",
    "Keyontae Johnson": "קיאנטה ג'ורג'", "Malevy Leons": "מאלבי לאונס", "Branden Carlson": "ברנדון קרלסון",

    # --- אטלנטה הוקס ---
    "Dejounte Murray": "דז'ונטה מארי", "Jalen Johnson": "ג'יילן ג'ונסון", "Zaccharie Risacher": "זקארי ריסאשה", "Onyeka Okongwu": "אונייקה אוקונגוו", "C.J. McCollum": "סי.ג'יי מקולום",
    "Dyson Daniels": "דייסון דניאלס", "Nickeil Alexander-Walker": "ניקיל אלכסנדר-ווקר", "Jonathan Kuminga": "ג'ונתן קומינגה", "Bogdan Bogdanovic": "בוגדן בוגדנוביץ'", "Gabe Vincent": "גייב וינסנט",
    "De'Andre Hunter": "דיאנדרה האנטר", "Kobe Bufkin": "קובי באפקין", "Larry Nance Jr.": "לארי נאנס ג'וניור", "Garrison Mathews": "גאריסון מתיוס", "Cody Zeller": "קודי זלר",
    "David Roddy": "דייוויד רודי", "Mouhamed Gueye": "מוחמד גיי", "Keaton Wallace": "קיטון וואלאס",

    # --- ברוקלין נטס ---
    "Michael Porter Jr.": "מייקל פורטר ג'וניור", "Nic Claxton": "ניק קלקסטון", "Noah Clowney": "נואה קלאוני", "Egor Demin": "איגור דמין", "Nolan Traore": "נולן טראורה",
    "Ben Saraf": "בן שרף", "Danny Wolf": "דני וולף", "Ziaire Williams": "זיאייר ויליאמס", "Day'Ron Sharpe": "דיירון שארפ", "Drake Powell": "דרייק פאוול",
    "Dariq Whitehead": "דאריק וייטהד", "Jalen Wilson": "ג'יילן וילסון", "Cam Johnson": "קמרון ג'ונסון", "Trendon Watford": "טרנדון ווטפורד", "Keon Johnson": "קיון ג'ונסון",
    "Tyrese Martin": "טייריס מרטין", "Jaylen Martin": "ג'יילן מרטין", "Cui Yongxi": "יונשי קוי",

    # --- שארלוט הורנטס ---
    "LaMelo Ball": "לאמלו בול", "Brandon Miller": "ברנדון מילר", "Kon Knueppel": "קון קנופל", "Miles Bridges": "מיילס ברידג'ס", "Coby White": "קובי וייט",
    "Grant Williams": "גראנט ויליאמס", "Tidjane Salaun": "טיג'אן סאלון", "Moussa Diabate": "מוסא דיאבטה", "Josh Green": "ג'וש גרין", "Nick Richards": "ניק ריצ'רדס",
    "Tre Mann": "טרה מאן", "Vasilije Micic": "ואסיליה מיציץ'", "Mark Williams": "מארק ויליאמס", "Seth Curry": "סת' קארי", "Cody Martin": "קודי מרטין",
    "Nick Smith Jr.": "ניק סמית' ג'וניור", "KJ Simpson": "קיי.ג'יי סימפסון", "Taj Gibson": "טאג' גיבסון",

    # --- דטרויט פיסטונס ---
    "Cade Cunningham": "קייד קנינגהאם", "Jaden Ivey": "ג'יידן אייבי", "Tobias Harris": "טוביאס האריס", "Jalen Duren": "ג'יילן דורן", "Ausar Thompson": "אוסאר תומפסון",
    "Ron Holland": "רון הולנד", "Isaiah Stewart": "אייזיה סטיוארט", "Simone Fontecchio": "סימונה פונטקיו", "Malik Beasley": "מליק ביזלי", "Tim Hardaway Jr.": "טים הארדוויי ג'וניור",
    "Wendell Moore Jr.": "ונדל מור ג'וניור", "Paul Reed": "פול ריד", "Marcus Sasser": "מרכוס סאסר", "Bobi Klintman": "בובי קלינטמן", "Camara Toumani": "טומאני קמארה",
    "Daniss Jenkins": "דניס ג'נקינס", "Cole Swider": "קול סווידר", "Alondes Williams": "אלונדס ויליאמס",

    # --- אינדיאנה פייסרס ---
    "Tyrese Haliburton": "טייריס הליברטון", "Pascal Siakam": "פסקל סיאקם", "Myles Turner": "מיילס טרנר", "Bennedict Mathurin": "בנדיקט מאת'ורין", "Aaron Nesmith": "ארון ניסמית'",
    "Andrew Nembhard": "אנדרו נבהארד", "Obi Toppin": "אובי טופין", "T.J. McConnell": "טי.ג'יי מקונל", "Jarace Walker": "ג'ראס ווקר", "Ben Sheppard": "בן שפרד",
    "Isaiah Jackson": "איזאיה ג'קסון", "James Wiseman": "ג'יימס וייסמן", "Johnny Furphy": "ג'וני פרפי", "Kendall Brown": "קנדל בראון", "James Johnson": "ג'יימס ג'ונסון",
    "Enrique Freeman": "אנריקה פרימן", "Tristen Newton": "טריסטן ניוטון", "Quenton Jackson": "קוונטון ג'קסון",

    # --- מיאמי היט ---
    "Jimmy Butler": "ג'ימי באטלר", "Bam Adebayo": "באם אדבאיו", "Tyler Herro": "טיילר הירו", "Terry Rozier": "טרי רוזייר", "Jaime Jaquez Jr.": "חיימה חאקז",
    "Nikola Jovic": "ניקולה יוביץ'", "Kel'el Ware": "קלל וור", "Duncan Robinson": "דאנקן רובינסון", "Haywood Highsmith": "היווד הייסמית'", "Kevin Love": "קווין לאב",
    "Pelle Larsson": "פלה לארסון", "Josh Richardson": "ג'וש ריצ'רדסון", "Thomas Bryant": "תומאס בריאנט", "Alec Burks": "אלק ברקס", "Nassir Little": "נאסיר ליטל",
    "Dru Smith": "דרו סמית'", "Christopher Smith": "כריסטופר סמית'", "Keshad Johnson": "קשאד ג'ונסון",

    # --- מילווקי באקס ---
    "Giannis Antetokounmpo": "יאניס אנטטוקומפו", "Damian Lillard": "דמיאן לילארד", "Khris Middleton": "כריס מידלטון", "Brook Lopez": "ברוק לופז", "Bobby Portis": "בובי פורטיס",
    "Gary Trent Jr.": "גארי טרנט ג'וניור", "Delon Wright": "דלון רייט", "Pat Connaughton": "פאט קונאטון", "Taurean Prince": "טוריין פרינס", "AJ Johnson": "איי.ג'יי ג'ונסון",
    "Tyler Smith": "טיילר סמית'", "Andre Jackson Jr.": "אנדרה ג'קסון ג'וניור", "MarJon Beauchamp": "מרג'ון בוצ'אמפ", "AJ Green": "איי.ג'יי גרין", "Chris Livingston": "כריס ליבינגסטון",
    "Thanasis Antetokounmpo": "תנאסיס אנטטוקומפו", "Stanley Umude": "סטנלי אומודה", "Anzejs Pasecniks": "אנג'ייס פאסצ'ניקס",

    # --- מינסוטה טימברוולבס ---
    "Anthony Edwards": "אנתוני אדוארדס", "Julius Randle": "ג'וליוס רנדל", "Rudy Gobert": "רודי גובר", "Donte DiVincenzo": "דונטה דיווינצ'נזו", "Naz Reid": "נאז ריד",
    "Mike Conley": "מייק קונלי", "Jaden McDaniels": "ג'יידן מקדניאלס", "Rob Dillingham": "רוב דילינגהאם", "Nickeil Alexander-Walker": "ניקיל אלכסנדר-ווקר", "Joe Ingles": "ג'ו אינגלס",
    "Terrence Shannon Jr.": "טרנס שאנון ג'וניור", "Josh Minott": "ג'וש מינוט", "Leonard Miller": "לאונרד מילר", "Luka Garza": "לוקה גרזה", "PJ Dozier": "פי.ג'יי דוזייר",
    "Daishen Nix": "דיישן ניקס", "Jesse Edwards": "ג'סי אדוארדס", "Jaylen Clark": "ג'יילן קלארק",

    # --- ניו אורלינס פליקנס ---
    "Zion Williamson": "זאיון ויליאמסון", "Brandon Ingram": "ברנדון אינגרם", "Dejounte Murray": "דז'ונטה מארי", "CJ McCollum": "סי.ג'יי מקולום", "Herb Jones": "הרב ג'ונס",
    "Trey Murphy III": "טריי מרפי", "Daniel Theis": "דניאל תייס", "Yves Missi": "איב מיסי", "Jordan Hawkins": "ג'ורדן הוקינס", "Jose Alvarado": "חוסה אלבראדו",
    "Javonte Green": "ג'בונטה גרין", "Jeremiah Robinson-Earl": "ג'רמיה רובינסון-ארל", "Antonio Reeves": "אנטוניו ריבס", "Karane Ingram": "קארן אינגרם", "Jamal Cain": "ג'מאל קיין",
    "Trey Jemison": "טריי ג'מיסון", "BJ Boston": "ברנדון בוסטון", "Elfrid Payton": "אלפריד פייטון",

    # --- ניו יורק ניקס ---
    "Jalen Brunson": "ג'יילן ברונסון", "Karl-Anthony Towns": "קארל-אנתוני טאונס", "OG Anunoby": "או.ג'י אנונובי", "Mikal Bridges": "מיקאל ברידג'ס", "Josh Hart": "ג'וש הארט",
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
    "KJ Martin": "קיי.ג'יי מרטין", "Ricky Council IV": "ריקי קאונסיל", "Reggie Jackson": "רז'י ג'קסון", "Adem Bona": "אדם בונה", "Lester Quinones": "לסטר קיניונס",
    "Jeff Dowtin Jr.": "ג'ף דאוטן", "Justin Edwards": "ג'סטין אדוארדס", "David Jones": "דייוויד ג'ונס",

    # --- סקרמנטו קינגס ---
    "De'Aaron Fox": "דיארון פוקס", "Domantas Sabonis": "דומנטאס סאבוניס", "Demar DeRozan": "דמאר דרוזן", "Keegan Murray": "קיגן מארי", "Malik Monk": "מליק מונק",
    "Kevin Huerter": "קווין הרטר", "Keon Ellis": "קיון אליס", "Trey Lyles": "טריי ליילס", "Alex Len": "אלכס לן", "Devin Carter": "דווין קרטר",
    "Doug McDermott": "דאג מקדרמוט", "Jordan McLaughlin": "ג'ורדן מקלופלין", "Orlando Robinson": "אורלנדו רובינסון", "Colby Jones": "קולבי ג'ונס", "Isaac Jones": "אייזק ג'ונס",
    "Mason Jones": "מייסון ג'ונס", "Jalen McDaniels": "ג'יילן מקדניאלס", "Isaiah Crawford": "איזאיה קרופורד",

    # --- טורונטו ראפטורס ---
    "Scottie Barnes": "סקוטי בארנס", "RJ Barrett": "אר.ג'יי בארט", "Immanuel Quickley": "עמנואל קוויקלי", "Jakob Poeltl": "יאקוב פולטל", "Gradey Dick": "גריידי דיק",
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
    "Stephen Curry": "סטפן קארי", "Draymond Green": "דריימונד גרין", "Jonathan Kuminga": "ג'ונתן קומינגה", "Andrew Wiggins": "אנדרו ויגינס", "Brandin Podziemski": "ברנדין פודז'מסקי",
    "Buddy Hield": "באדי הילד", "De'Anthony Melton": "דיאנתוני מלטון", "Kyle Anderson": "קייל אנדרסון", "Trayce Jackson-Davis": "טרייס ג'קסון-דייוויס", "Moses Moody": "מוזס מודי",
    "Kevon Looney": "קevon לוני", "Gary Payton II": "גארי פייטון השני", "Lindy Waters III": "לינדי ווטרס", "Gui Santos": "גאי סנטוס", "Quint Post": "קווינטן פוסט",
    "Pat Spencer": "פאט ספנסר", "Reece Beekman": "ריס ביקמן", "Jerome Robinson": "ג'רום רובינסון",

    # --- לוס אנג'לס קליפרס ---
    "James Harden": "ג'יימס הארדן", "Kawhi Leonard": "קוואי לנארד", "Norman Powell": "נורמן פאוול", "Ivica Zubac": "איביצה זובאץ", "Derrick Jones Jr.": "דריק ג'ונס ג'וניור",
    "Terance Mann": "טרנס מאן", "Kevin Porter Jr.": "קווין פורטר ג'וניור", "Kris Dunn": "קריס דאן", "Nicolas Batum": "ניקולא באטום", "Amir Coffey": "אמיר קופי",
    "Mo Bamba": "מו במבה", "PJ Tucker": "פי.ג'יי טאקר", "Bones Hyland": "בונז היילנד", "Kai Jones": "קאי ג'ונס", "Jordan Miller": "ג'ורדן מילר",
    "Cam Christie": "קאם כריסטי", "Kobe Brown": "קובי בראון", "Trentyn Flowers": "טרנטין פלאוורס",

    # --- דנבר נאגטס ---
    "Nikola Jokic": "ניקולה יוקיץ'", "Jamal Murray": "ג'מאל מארי", "Michael Porter Jr.": "מייקל פורטר ג'וניור", "Aaron Gordon": "ארון גורדון", "Russell Westbrook": "ראסל ווסטברוק",
    "Christian Braun": "כריסטיאן בראון", "Peyton Watson": "פייטון ווטסון", "Dario Saric": "דאריו שאריץ'", "Julian Strawther": "ג'וליאן סטראותר", "DeAndre Jordan": "דיאנדרה ג'ורדן",
    "Zeke Nnaji": "זיק נאג'י", "Hunter Tyson": "האנטר טייסון", "Vlatko Cancar": "בלאטקו צ'נצ'אר", "DaRon Holmes II": "דארון הולמס", "Jalen Pickett": "ג'יילן פיקט",
    "Trey Alexander": "טריי אלכסנדר", "PJ Hall": "פי.ג'יי הול", "Spencer Jones": "ספנסר ג'ונס"
}

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "names" not in data: data["names"] = {}
                if "games" not in data: data["games"] = {}
                return data
        except: pass
    return {"names": {}, "games": {}}

cache = load_cache()

def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=4, ensure_ascii=False)

def translate_name(name):
    if not name:
        return ""

    # שלב א': בדיקה במילון השחקנים המעודכן שלך (NBA_PLAYERS_HEB)
    if name in NBA_PLAYERS_HEB:
        return NBA_PLAYERS_HEB[name]
    
    # שלב ב': בדיקה במילון הקבוצות (אם השם הוא שם של קבוצה)
    if name in NBA_TEAMS_HEBREW:
        return NBA_TEAMS_HEBREW[name]

    # שלב ג': בדיקה ב-Cache (כדי לא לתרגם פעמיים בגוגל שמות שכבר מצאנו)
    if name in cache["names"]:
        return cache["names"][name]

    # שלב ד': תרגום אוטומטי בגוגל (כגיבוי לשחקנים חסרים)
    try:
        # ניקוי סיומות כמו Jr. כדי לשפר את התרגום
        clean_name = name.replace("Jr.", "").replace("III", "").strip()
        translated = translator.translate(clean_name)
        
        # שמירה ב-Cache לפעם הבאה
        cache["names"][name] = translated
        save_cache()
        return translated
    except Exception as e:
        print(f"Error translating {name}: {e}")
        return name # אם גם גוגל נכשל, מחזירים את השם באנגלית

def get_stat_line(p):
    s = p['statistics']
    line = f"{s['points']} נק', {s['reboundsTotal']} רב', {s['assists']} אס'"
    if s.get('steals', 0) > 0: line += f", {s['steals']} חט'"
    if s.get('blocks', 0) > 0: line += f", {s['blocks']} חס'"
    return line

def format_msg(box, label, is_final=False, is_start=False, is_drama=False):
    photo_url = None
    away, home = box['awayTeam'], box['homeTeam']
    
    # שינוי 1: שם מלא (עיר + כינוי) בכל ההודעות בכותרת
    a_full = translate_name(f"{away['teamCity']} {away['teamName']}")
    h_full = translate_name(f"{home['teamCity']} {home['teamName']}")
    
    period = box.get('period', 0)
    s_space = "ㅤ" 
    
    combined_len = len(a_full) + len(h_full)
    padding = max(0, 22 - combined_len)
    
    if is_drama: header_emoji = "😱"
    elif is_final: header_emoji = "🏁"
    elif is_start: header_emoji = "🚀"
    else: header_emoji = "⏱️"
    
    header_text = f"{header_emoji} <b>{label}</b> {header_emoji}"
    msg = f"\u200f{header_text}\n"
    msg += f"\u200f🏀 <b>{a_full} 🆚 {h_full}</b> 🏀{s_space * padding}\n\n"

    if is_start:
        if period == 1:
            for team in [away, home]:
                # שינוי 2: שם מלא בחמישיות
                t_full_name = translate_name(f"{team['teamCity']} {team['teamName']}")
                starters = [translate_name(f"{p['firstName']} {p['familyName']}") for p in team['players'] if p.get('starter') == '1']
                out = [translate_name(f"{p['firstName']} {p['familyName']}") for p in team['players'] if p.get('status') == 'INACTIVE']
                
                msg += f"\u200f🏀 <b>{t_full_name}</b>\n"
                msg += f"\u200f📍 <b>חמישייה:</b> {', '.join(starters) if starters else 'טרם פורסם'}\n"
                if out:
                    msg += f"\u200f❌ <b>חיסורים:</b> {', '.join(out[:5])}\n"
                msg += "\n"
        
        # שינוי 3: ביטול תמונה בפתיחה
        return msg, None

    score_str = f"<b>{max(away['score'], home['score'])} - {min(away['score'], home['score'])}</b>"
    
    if is_drama:
        msg += f"\u200f🔥 <b>טירוף! שוויון {score_str} הולכים להארכה!</b> 🔥\n\n"
        return msg, None # ביטול תמונה בדרמה

    leader_name = a_full if away['score'] > home['score'] else h_full
    win_emoji = "🏆" if is_final else "🔥"
    if away['score'] == home['score']:
        msg += f"\u200f🔥 <b>שוויון {score_str}</b> 🔥\n\n"
    else:
        action = "מנצחת" if is_final else "מובילה"
        msg += f"\u200f{win_emoji} <b>{leader_name} {action} {score_str}</b> {win_emoji}\n\n"

    count = 3 if (period >= 4 or is_final) else 2
    for team in [away, home]:
        # שינוי 4: שם מלא מעל רשימת הסטטיסטיקה (📍 הקבוצה המלאה:)
        t_full_stats = translate_name(f"{team['teamCity']} {team['teamName']}")
        msg += f"\u200f📍 <b>{t_full_stats}:</b>\n"
        top = sorted([p for p in team['players'] if p['statistics']['points'] > 0], 
                     key=lambda x: x['statistics']['points'], reverse=True)[:count]
        for i, p in enumerate(top):
            medal = ["🥇", "🥈", "🥉"][i]
            msg += f"\u200f{medal} <b>{translate_name(p['firstName']+' '+p['familyName'])}</b>: {get_stat_line(p)}\n"
        msg += "\n"

    if is_final:
        all_p = away['players'] + home['players']
        mvp = max(all_p, key=lambda x: x['statistics']['points'] + x['statistics']['reboundsTotal'] + x['statistics']['assists'])
        msg += f"\u200f🏆 <b>ה-MVP של המשחק: {translate_name(mvp['firstName']+' '+mvp['familyName'])}</b>\n"
        msg += f"\u200f📊 {get_stat_line(mvp)}\n"
        # שינוי 5: ביטול תמונה בסיום (MVP)
        photo_url = None
    
    return msg, photo_url

def send_telegram(text, photo_url=None):
    payload = {"chat_id": CHAT_ID, "parse_mode": "HTML"}
    try:
        if photo_url:
            r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto", data={**payload, "photo": photo_url, "caption": text}, timeout=20)
            if r.status_code == 200: return
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={**payload, "text": text}, timeout=15)
    except: pass

def run():
    print("🚀 בוט NBA משודרג - גרסה מלאה (250+ שורות) - כולל הארכות ופוסטר כוכב ביתי!")
    while True:
        try:
            current_time = datetime.now().strftime("%H:%M:%S")
            print(f"🔍 [{current_time}] סורק משחקים...")
            resp = requests.get(NBA_URL, headers=HEADERS, timeout=10).json()
            games = resp.get('scoreboard', {}).get('games', [])

            for g in games:
                gid, status, period, txt = g['gameId'], g['gameStatus'], g.get('period', 0), g.get('gameStatusText', '').lower()
                if gid not in cache["games"]: cache["games"][gid] = []
                log = cache["games"][gid]
                game_final_key = "FINAL_SENT"

                # --- 1. הודעות יצא לדרך (רבע 1 עם חמישיות, רבע 3 פשוט) ---
                if status == 2 and period in [1, 3] and f"q{period}" in txt:
                    s_key = f"start_q{period}"
                    if (period == 1 or period == 3) and s_key not in log:
                        b_resp = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json", headers=HEADERS).json()
                        label = "המשחק יצא לדרך!" if period == 1 else f"רבע {period} יצא לדרך!"
                        m, p = format_msg(b_resp['game'], label, is_start=True)
                        send_telegram(m, p)
                        log.append(s_key)
                        save_cache()
                        print(f"✅ נשלחה פתיחת רבע {period}: {gid}")

                # --- 2. לוגיקת הארכה (שוויון בסיום רבע 4 ומעלה) ---
                if status == 2 and period >= 4 and "end" in txt and g['homeTeam']['score'] == g['awayTeam']['score']:
                    d_key = f"drama_period_{period}"
                    if d_key not in log:
                        b_resp = requests.get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json", headers=HEADERS).json()
                        m, p = format_msg(b_resp['game'], "דרמה ב-NBA!", is_drama=True)
                        send_telegram(m, p)
                        log.append(d_key)
                        log.append(txt) # מונע הודעת סיום רבע רגילה בשוויון
                        save_cache()
                        print(f"😱 נשלחה הודעת דרמה (הארכה): {gid}")

                # --- 3. הודעות סיום מסודרות ללא כפילויות ---
                if status == 3 and game_final_key not in log:
                   
                        b_resp = requests.get(
                            f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json",
                            headers=HEADERS
                        ).json()

                        m, p = format_msg(b_resp['game'], "סיום המשחק", is_final=True)
                        send_telegram(m, p)

                        log.append(game_final_key)
                        save_cache()
                        print(f"🏁 נשלח סיום משחק {gid}")
                        
                # ⛔ אם המשחק לא הסתיים – מטפלים רק במחצית ורבעים
                elif status != 3:

                        # מחצית
                        if "half" in txt and txt not in log:
                            b_resp = requests.get(
                                f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json",
                                headers=HEADERS
                            ).json()

                            m, p = format_msg(b_resp['game'], "סיום מחצית")
                            send_telegram(m, p)

                            log.append(txt)
                            save_cache()
                            print(f"⏸ נשלחה מחצית {gid}")

                        # סיום רבע רגיל (רק רבעים 1-3)
                        elif "end" in txt and txt not in log and period < 4:
                            b_resp = requests.get(
                                f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json",
                                headers=HEADERS
                            ).json()

                            m, p = format_msg(b_resp['game'], f"סיום רבע {period}")
                            send_telegram(m, p)

                            log.append(txt)
                            save_cache()
                            print(f"⏱ נשלח סיום רבע {period} {gid}")

                        # סיום הארכה בלבד
                        elif "end" in txt and txt not in log and period > 4:
                            b_resp = requests.get(
                                f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json",
                                headers=HEADERS
                            ).json()

                            m, p = format_msg(b_resp['game'], f"סיום הארכה {period-4}")
                            send_telegram(m, p)

                            log.append(txt)
                            save_cache()
                            print(f"⏱ נשלחה הארכה {gid}")

        except Exception as e:
            print(f"❌ שגיאה בלוגיקה: {e}")
        
        time.sleep(15)

if __name__ == "__main__":
    run()

import requests
import time
import re

TELEGRAM_TOKEN = "8284141482:AAGG1vPtJrLeAvL7kADMeuFGbEydIq08ib0"
CHAT_ID = "-1003714393119"

SCOREBOARD_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
BOXSCORE_URL = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{}.json"

CHECK_INTERVAL = 10  # שניות

# =========================
# תרגומים
# =========================
NBA_TEAMS_HEBREW = {
    "Atlanta Hawks": "אטלנטה הוקס",
    "Boston Celtics": "בוסטון סלטיקס",
    "Brooklyn Nets": "ברוקלין נטס",
    "Charlotte Hornets": "שארלוט הורנטס",
    "Chicago Bulls": "שיקגו בולס",
    "Cleveland Cavaliers": "קליבלנד קאבלירס",
    "Dallas Mavericks": "דאלאס מאבריקס",
    "Denver Nuggets": "דנבר נאגטס",
    "Detroit Pistons": "דטרויט פיסטונס",
    "Golden State Warriors": "גולדן סטייט ווריורס",
    "Houston Rockets": "יוסטון רוקטס",
    "Indiana Pacers": "אינדיאנה פייסרס",
    "LA Clippers": "לוס אנג'לס קליפרס",
    "Los Angeles Clippers": "לוס אנג'לס קליפרס",
    "Los Angeles Lakers": "לוס אנג'לס לייקרס",
    "Memphis Grizzlies": "ממפיס גריזליס",
    "Miami Heat": "מיאמי היט",
    "Milwaukee Bucks": "מילווקי באקס",
    "Minnesota Timberwolves": "מינסוטה טימברוולבס",
    "New Orleans Pelicans": "ניו אורלינס פליקנס",
    "New York Knicks": "ניו יורק ניקס",
    "Oklahoma City Thunder": "אוקלהומה סיטי ת'אנדר",
    "Orlando Magic": "אורלנדו מג'יק",
    "Philadelphia 76ers": "פילדלפיה סבנטי סיקסרס",
    "Phoenix Suns": "פיניקס סאנס",
    "Portland Trail Blazers": "פורטלנד טרייל בלייזרס",
    "Sacramento Kings": "סקרמנטו קינגס",
    "San Antonio Spurs": "סן אנטוניו ספרס",
    "Toronto Raptors": "טורונטו ראפטורס",
    "Utah Jazz": "יוטה ג'אז",
    "Washington Wizards": "וושינגטון וויזארדס"
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

def translate_name(name):
    if not name:
        return name

    if name in NBA_PLAYERS_HEB:
        return NBA_PLAYERS_HEB[name]

    if name in NBA_TEAMS_HEBREW:
        return NBA_TEAMS_HEBREW[name]

    for eng, heb in NBA_TEAMS_HEBREW.items():
        if eng in name:
            return name.replace(eng, heb)

    return name

# =========================
# Session
# =========================
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
})

# נשמור על משחקים שכבר נשלחה עליהם התראת קלאץ'
sent_clutch_alerts = set()

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        response = session.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=15
        )
        if response.status_code != 200:
            print("Telegram API error:", response.status_code, response.text)
            return False
        return True
    except Exception as e:
        print("Telegram send failed:", e)
        return False

def get_json(url):
    response = session.get(url, timeout=15)
    response.raise_for_status()
    return response.json()

def parse_clock(game_status_text):
    """
    דוגמאות צפויות:
    'Q4 03:41'
    'OT 01:12'
    מחזיר: (mins, secs, total_seconds)
    """
    if not game_status_text:
        return None, None, None

    match = re.search(r'(\d{1,2}):(\d{2})$', game_status_text.strip())
    if not match:
        return None, None, None

    mins = int(match.group(1))
    secs = int(match.group(2))
    total_seconds = mins * 60 + secs
    return mins, secs, total_seconds

def clean_clock(clock_text):
    mins, secs, total_seconds = parse_clock(clock_text)
    if total_seconds is None:
        return clock_text
    return f"{mins}:{secs:02d}"

def get_team_full_name(team_obj):
    city = team_obj.get("teamCity", "")
    name = team_obj.get("teamName", "")
    full = f"{city} {name}".strip()
    return translate_name(full)

def get_team_score(team_obj):
    try:
        return int(team_obj.get("score", 0))
    except:
        return 0

def get_top_scorer(team_obj):
    players = team_obj.get("players", [])
    valid_players = []

    for p in players:
        stats = p.get("statistics", {})
        pts = stats.get("points")
        if pts is None:
            pts = 0
        valid_players.append((pts, p))

    if not valid_players:
        return None

    valid_players.sort(key=lambda x: x[0], reverse=True)
    pts, star = valid_players[0]

    full_name = f"{star.get('firstName', '').strip()} {star.get('familyName', '').strip()}".strip()
    return {
        "name": translate_name(full_name),
        "points": pts
    }

def format_clutch_msg(game_box, raw_clock):
    away = game_box["awayTeam"]
    home = game_box["homeTeam"]

    away_name = get_team_full_name(away)
    home_name = get_team_full_name(home)

    away_score = get_team_score(away)
    home_score = get_team_score(home)

    clean_time = clean_clock(raw_clock)

    if away_score > home_score:
        leader_text = f"{away_name} מובילה"
    elif home_score > away_score:
        leader_text = f"{home_name} מובילה"
    else:
        leader_text = "שוויון"

    msg = "‏🚨 <b>התראת קלאץ'!</b> 🚨\n"
    msg += f"‏🏀 <b>{away_name} 🆚 {home_name}</b>\n\n"

    if away_score == home_score:
        msg += f"‏🔥 <b>שוויון {away_score} - {home_score}</b>\n\n"
    else:
        msg += f"‏🔥 <b>{leader_text} {away_score} - {home_score}</b>\n\n"

    msg += f"‏⏱️ <b>זמן לסיום: {clean_time}</b>\n\n"

    msg += "‏📍 <b>קלעים מובילים:</b>\n"

    home_star = get_top_scorer(home)
    away_star = get_top_scorer(away)

    if home_star:
        msg += f"‏🏆 <b>{home_name}</b>: {home_star['name']} ({home_star['points']})\n"

    if away_star:
        msg += f"‏🏆 <b>{away_name}</b>: {away_star['name']} ({away_star['points']})\n"

    return msg

def should_send_clutch_alert(game):
    """
    שולח התראה רק אם:
    - המשחק בלייב (gameStatus == 2)
    - רבע 4 או הארכה
    - נשארו 4:00 או פחות
    - הפרש 3 או פחות
    """
    try:
        game_id = game.get("gameId")
        status = game.get("gameStatus")
        period = game.get("period", 0)
        clock_text = game.get("gameStatusText", "")

        if not game_id:
            return False, "אין gameId"

        if status != 2:
            return False, "המשחק לא בלייב"

        if period < 4:
            return False, "עדיין לא רבע 4"

        _, _, total_seconds = parse_clock(clock_text)
        if total_seconds is None:
            return False, f"לא הצלחתי לקרוא שעון: {clock_text}"

        if total_seconds > 240:
            return False, "נשארו יותר מ-4 דקות"

        home_score = get_team_score(game.get("homeTeam", {}))
        away_score = get_team_score(game.get("awayTeam", {}))
        diff = abs(home_score - away_score)

        if diff > 3:
            return False, f"הפרש גבוה מדי: {diff}"

        if game_id in sent_clutch_alerts:
            return False, "כבר נשלחה התראה למשחק הזה"

        return True, "המשחק עומד בכל תנאי הקלאץ'"
    except Exception as e:
        return False, f"שגיאה ב-should_send_clutch_alert: {e}"

def check_for_clutch():
    try:
        data = get_json(SCOREBOARD_URL)
        games = data.get("scoreboard", {}).get("games", [])

        if not games:
            print("לא נמצאו משחקים")
            return

        for game in games:
            game_id = game.get("gameId")
            ok, reason = should_send_clutch_alert(game)
            print(f"Game {game_id}: {reason}")

            if not ok:
                continue

            try:
                box = get_json(BOXSCORE_URL.format(game_id))
                game_box = box.get("game")

                if not game_box:
                    print(f"Game {game_id}: אין game בתוך boxscore")
                    continue

                clock_text = game.get("gameStatusText", "")
                msg = format_clutch_msg(game_box, clock_text)

                sent_ok = send_telegram(msg)
                if sent_ok:
                    sent_clutch_alerts.add(game_id)
                    print(f"Game {game_id}: clutch alert sent")
                else:
                    print(f"Game {game_id}: שליחה לטלגרם נכשלה")

            except Exception as e:
                print(f"Game {game_id}: boxscore error - {e}")

    except Exception as e:
        print("Scoreboard error:", e)

if __name__ == "__main__":
    print("🚀 Clutch bot is running...")
    while True:
        check_for_clutch()
        time.sleep(CHECK_INTERVAL)

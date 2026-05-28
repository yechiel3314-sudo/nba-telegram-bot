#!/usr/bin/env python3
"""
Single-file X/Twitter to Telegram football news forwarder.

Run:
  python3 football_x_to_telegram.py

No X API key is needed. It reads public RSS-style mirrors, so availability
can change depending on those mirrors. Telegram bot token is required.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ====== SETTINGS ======

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "8480434397:AAF8ay6JxuYsf7ytVOLG73bVJiJQHq8CMx4",
)
TELEGRAM_CHAT_ID = "-1003869452843"

X_ACCOUNTS = [
    "FabrizioRomano",
    "David_Ornstein",
    "DiMarzio",
    "JacobsBen",
    "lauriewhitwell",
    "SamLee",
    "_pauljoyce",
    "Matt_Law_DT",
    "MatteMoretto",
    "ffpolo",
    "gerardromero",
    "AranchaMOBILE",
    "JLSanchez78",
    "AlfredoPedulla",
    "Plettigoal",
    "cfbayern",
    "FabriceHawkins",
    "Tanziloic",
]

ACCOUNT_DISPLAY_NAMES = {
    "FabrizioRomano": "פבריציו רומאנו - כללי",
    "David_Ornstein": "דיוויד אורנשטיין - כללי",
    "DiMarzio": "ג׳אנלוקה די מארציו - כללי",
    "JacobsBen": "בן ג׳ייקובס - כללי",
    "lauriewhitwell": "לורי וויטוול - מנצ׳סטר יונייטד",
    "SamLee": "סם לי - מנצ׳סטר סיטי",
    "_pauljoyce": "פול ג׳ויס - ליברפול",
    "Matt_Law_DT": "מאט לאו - צ׳לסי",
    "MatteMoretto": "מתאו מורטו - ספרד",
    "ffpolo": "פרננדו פולו - ברצלונה",
    "gerardromero": "חרארד רומרו - ברצלונה",
    "AranchaMOBILE": "ארנצ׳ה רודריגז - ריאל מדריד",
    "JLSanchez78": "חוסה לואיס סאנצ׳ז - ריאל מדריד",
    "AlfredoPedulla": "אלפרדו פדולה - איטליה",
    "86_longo": "דניאלה לונגו - מילאן",
    "Plettigoal": "פלוריאן פלטנברג - גרמניה",
    "cfbayern": "כריסטיאן פאלק - גרמניה",
    "FabriceHawkins": "פבריס הוקינס - צרפת",
    "Tanziloic": "לואיק טנזי - צרפת",
}

TARGET_LANGUAGE = "he"
CHECK_EVERY_SECONDS = 45
# Keep one full scan cycle within about 45 seconds: accounts are fetched in parallel,
# and each feed request fails fast instead of waiting a long time on blocked RSS mirrors.
HTTP_RETRIES = 1
RETRY_SLEEP_SECONDS = 0.5
FEED_REQUEST_TIMEOUT_SECONDS = 8
MAX_PARALLEL_ACCOUNT_CHECKS = 8
MAX_NEW_POSTS_PER_ACCOUNT_PER_CHECK = 6
SEND_LAST_POST_ON_FIRST_RUN = False
SEND_LAST_POST_ON_EVERY_START = False
SEND_STARTUP_STATUS_MESSAGE = True
MAX_IMAGES_PER_POST = 4
STATE_FILE = "football_x_to_telegram_state.json"
SEND_IMAGES_AFTER_TEXT = False
RTL_MARK = "\u200f"

FEED_TEMPLATES = [
    "https://rsshub.app/twitter/user/{username}",
    "https://rsshub.rssforever.com/twitter/user/{username}",
    "https://nitter.net/{username}/rss",
]

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
VIDEO_EXTENSIONS = (".mp4", ".mov", ".m3u8", ".webm", ".avi", ".mkv")
ARTICLE_DOMAINS_TO_REMOVE = (
    "nytimes.com",
    "theathletic.com",
    "telegraph.co.uk",
    "dailymail.co.uk",
    "skysports.com",
    "bbc.com",
    "bbc.co.uk",
    "espn.com",
    "marca.com",
    "as.com",
    "sport.es",
    "mundodeportivo.com",
    "relevo.com",
    "gazzetta.it",
    "calciomercato.com",
    "lequipe.fr",
    "footmercato.net",
)

# Handles / @mentions often arrive as one glued token, so translate them
# before removing the @ sign and before sending the text to machine translation.
HANDLE_REPLACEMENTS = {
    "@SkySports": "סקיי ספורטס",
    "SkySports": "סקיי ספורטס",
    "@SkySportsNews": "סקיי ספורטס ניוז",
    "SkySportsNews": "סקיי ספורטס ניוז",
    "@TheAthletic": "דה אתלטיק",
    "TheAthletic": "דה אתלטיק",
    "@TheAthleticFC": "דה אתלטיק",
    "TheAthleticFC": "דה אתלטיק",
    "@BBCSport": "בי־בי־סי ספורט",
    "BBCSport": "בי־בי־סי ספורט",
    "@BBCMOTD": "מאץ׳ אוף דה דיי",
    "BBCMOTD": "מאץ׳ אוף דה דיי",
    "@ESPNFC": "ESPN FC",
    "ESPNFC": "ESPN FC",
    "@guardian_sport": "הגרדיאן ספורט",
    "guardian_sport": "הגרדיאן ספורט",
    "@TeleFootball": "טלגרף פוטבול",
    "TeleFootball": "טלגרף פוטבול",
    "@MailSport": "דיילי מייל ספורט",
    "MailSport": "דיילי מייל ספורט",
    "@FabrizioRomano": "פבריציו רומאנו",
    "FabrizioRomano": "פבריציו רומאנו",
    "@David_Ornstein": "דיוויד אורנשטיין",
    "David_Ornstein": "דיוויד אורנשטיין",
    "@DiMarzio": "ג׳אנלוקה די מארציו",
    "DiMarzio": "ג׳אנלוקה די מארציו",
    "@JacobsBen": "בן ג׳ייקובס",
    "JacobsBen": "בן ג׳ייקובס",
    "@lauriewhitwell": "לורי וויטוול",
    "lauriewhitwell": "לורי וויטוול",
    "@SamLee": "סם לי",
    "SamLee": "סם לי",
    "@_pauljoyce": "פול ג׳ויס",
    "_pauljoyce": "פול ג׳ויס",
    "@Matt_Law_DT": "מאט לאו",
    "Matt_Law_DT": "מאט לאו",
    "@MatteMoretto": "מתאו מורטו",
    "MatteMoretto": "מתאו מורטו",
    "@ffpolo": "פרננדו פולו",
    "ffpolo": "פרננדו פולו",
    "@gerardromero": "חרארד רומרו",
    "gerardromero": "חרארד רומרו",
    "@AranchaMOBILE": "ארנצ׳ה רודריגז",
    "AranchaMOBILE": "ארנצ׳ה רודריגז",
    "@JLSanchez78": "חוסה לואיס סאנצ׳ז",
    "JLSanchez78": "חוסה לואיס סאנצ׳ז",
    "@AlfredoPedulla": "אלפרדו פדולה",
    "AlfredoPedulla": "אלפרדו פדולה",
    "@86_longo": "דניאלה לונגו",
    "86_longo": "דניאלה לונגו",
    "@Plettigoal": "פלוריאן פלטנברג",
    "Plettigoal": "פלוריאן פלטנברג",
    "@cfbayern": "כריסטיאן פאלק",
    "cfbayern": "כריסטיאן פאלק",
    "@FabriceHawkins": "פבריס הוקינס",
    "FabriceHawkins": "פבריס הוקינס",
    "@Tanziloic": "לואיק טנזי",
    "Tanziloic": "לואיק טנזי",
    "@SkySport": "סקיי ספורט",
    "SkySport": "סקיי ספורט",
    "@SkySportDE": "סקיי ספורט גרמניה",
    "SkySportDE": "סקיי ספורט גרמניה",
    "@skysportde": "סקיי ספורט גרמניה",
    "skysportde": "סקיי ספורט גרמניה",
    "@kerry_hau": "קרי האו",
    "kerry_hau": "קרי האו",
    "@PipersierraR": "פיפה סיירה",
    "PipersierraR": "פיפה סיירה",
    "@CLMerlo": "ססאר לואיס מרלו",
    "CLMerlo": "ססאר לואיס מרלו",
    "@mundodeportivo": "מונדו דפורטיבו",
    "mundodeportivo": "מונדו דפורטיבו",
    "@JijantesFC": "ג׳יגאנטס",
    "JijantesFC": "ג׳יגאנטס",
    "@RMCsport": "RMC ספורט",
    "RMCsport": "RMC ספורט",
    "@lequipe": "לאקיפ",
    "lequipe": "לאקיפ",
    "@ActuFoot_": "אקטו פוט",
    "ActuFoot_": "אקטו פוט",
    "@MadridXtra": "מדריד אקסטרה",
    "MadridXtra": "מדריד אקסטרה",
    "@ManagingBarca": "מנג׳ינג בארסה",
    "ManagingBarca": "מנג׳ינג בארסה",
    "@Barca_Buzz": "בארסה באז",
    "Barca_Buzz": "בארסה באז",
    "@iMiaSanMia": "מיה סן מיה",
    "iMiaSanMia": "מיה סן מיה",
    "@FabrizioRomanoFC": "פבריציו רומאנו",
    "FabrizioRomanoFC": "פבריציו רומאנו",
}

BARE_EXTERNAL_DOMAIN_RE = re.compile(
    r"(?<!@)\b(?:[A-Za-z0-9-]+\.)+(?:com|co\.uk|net|org|io|app|fr|it|es|de|co|uk|news|sport|football)(?:/\S*)?",
    re.IGNORECASE,
)


FOOTBALL_TERMS = {
    "here we go": "הנה זה קורה",
    "breaking": "דיווח דרמטי",
    "exclusive": "בלעדי",
    "understand": "לפי המידע",
    "sources say": "לפי מקורות",
    "sources tell": "לפי מקורות",
    "club sources": "לפי מקורות במועדון",
    "deal agreed": "העסקה סוכמה",
    "agreement reached": "הושג סיכום",
    "verbal agreement": "סיכום בעל פה",
    "full agreement": "סיכום מלא",
    "personal terms": "תנאים אישיים",
    "personal terms agreed": "סוכמו התנאים האישיים",
    "medical tests": "בדיקות רפואיות",
    "medical booked": "נקבעו בדיקות רפואיות",
    "contract signed": "החוזה נחתם",
    "contract extension": "הארכת חוזה",
    "loan deal": "עסקת השאלה",
    "loan move": "מעבר בהשאלה",
    "permanent move": "מעבר קבוע",
    "option to buy": "אופציית רכישה",
    "obligation to buy": "חובת רכישה",
    "release clause": "סעיף שחרור",
    "sell-on clause": "סעיף אחוזים ממכירה עתידית",
    "add-ons": "בונוסים",
    "fixed fee": "סכום קבוע",
    "transfer fee": "דמי העברה",
    "free transfer": "העברה חופשית",
    "free agent": "שחקן חופשי",
    "advanced talks": "שיחות מתקדמות",
    "talks ongoing": "השיחות נמשכות",
    "deal off": "העסקה ירדה מהפרק",
    "green light": "אור ירוק",
    "set to join": "צפוי להצטרף",
    "set to sign": "צפוי לחתום",
    "close to joining": "קרוב להצטרף",
    "close to signing": "קרוב לחתימה",
    "joins": "מצטרף ל",
    "signs for": "חותם ב",
    "will sign": "יחתום",
    "has signed": "חתם",
    "bid submitted": "הוגשה הצעה",
    "formal bid": "הצעה רשמית",
    "bid rejected": "ההצעה נדחתה",
    "bid accepted": "ההצעה התקבלה",
    "official soon": "רשמי בקרוב",
    "done deal": "עסקה סגורה",
    "manager": "מאמן",
    "head coach": "מאמן ראשי",
    "sporting director": "מנהל מקצועי",
    "goalkeeper": "שוער",
    "centre back": "בלם",
    "center back": "בלם",
    "left back": "מגן שמאלי",
    "right back": "מגן ימני",
    "winger": "שחקן כנף",
    "striker": "חלוץ",
    "forward": "חלוץ",
    "injury": "פציעה",
    "injured": "פצוע",
    "suspended": "מושעה",
    "available": "זמין למשחק",
    "starting XI": "ההרכב הפותח",
    "clean sheet": "שער נקי",
    "stoppage time": "תוספת הזמן",
    "extra time": "הארכה",
    "penalty shootout": "דו-קרב פנדלים",
    "Champions League": "ליגת האלופות",
    "Europa League": "הליגה האירופית",
    "Conference League": "הקונפרנס ליג",
    "Premier League": "הפרמייר ליג",
    "La Liga": "לה ליגה",
    "Serie A": "סרייה א׳",
    "Bundesliga": "בונדסליגה",
    "Ligue 1": "ליגה 1",
}

TEAM_REPLACEMENTS = {
    "Manchester United": "מנצ׳סטר יונייטד",
    "Man United": "מנצ׳סטר יונייטד",
    "Man Utd": "מנצ׳סטר יונייטד",
    "Manchester City": "מנצ׳סטר סיטי",
    "Man City": "מנצ׳סטר סיטי",
    "Liverpool": "ליברפול",
    "Chelsea": "צ׳לסי",
    "Arsenal": "ארסנל",
    "Tottenham Hotspur": "טוטנהאם",
    "Tottenham": "טוטנהאם",
    "Spurs": "טוטנהאם",
    "Newcastle United": "ניוקאסל",
    "Newcastle": "ניוקאסל",
    "Aston Villa": "אסטון וילה",
    "West Ham United": "ווסטהאם",
    "West Ham": "ווסטהאם",
    "Brighton": "ברייטון",
    "Everton": "אברטון",
    "Leicester City": "לסטר סיטי",
    "Leicester": "לסטר",
    "Crystal Palace": "קריסטל פאלאס",
    "Wolves": "וולבס",
    "Fulham": "פולהאם",
    "Bournemouth": "בורנמות׳",
    "Brentford": "ברנטפורד",
    "Nottingham Forest": "נוטינגהאם פורסט",
    "Real Madrid": "ריאל מדריד",
    "Barcelona": "ברצלונה",
    "FC Barcelona": "ברצלונה",
    "Atletico Madrid": "אתלטיקו מדריד",
    "Atlético Madrid": "אתלטיקו מדריד",
    "Sevilla": "סביליה",
    "Valencia": "ולנסיה",
    "Villarreal": "ויאריאל",
    "Real Sociedad": "ריאל סוסיאדד",
    "Athletic Club": "אתלטיק בילבאו",
    "Athletic Bilbao": "אתלטיק בילבאו",
    "Real Betis": "בטיס",
    "Betis": "בטיס",
    "AC Milan": "מילאן",
    "Milan": "מילאן",
    "Inter Milan": "אינטר",
    "Inter": "אינטר",
    "Juventus": "יובנטוס",
    "Juve": "יובנטוס",
    "Napoli": "נאפולי",
    "Roma": "רומא",
    "Lazio": "לאציו",
    "Atalanta": "אטאלנטה",
    "Fiorentina": "פיורנטינה",
    "Torino": "טורינו",
    "Bayern Munich": "באיירן מינכן",
    "Bayern": "באיירן",
    "Borussia Dortmund": "בורוסיה דורטמונד",
    "Dortmund": "דורטמונד",
    "Bayer Leverkusen": "באייר לברקוזן",
    "Leverkusen": "לברקוזן",
    "RB Leipzig": "לייפציג",
    "Leipzig": "לייפציג",
    "Eintracht Frankfurt": "איינטרכט פרנקפורט",
    "Paris Saint-Germain": "פריז סן ז׳רמן",
    "PSG": "פ.ס.ז׳",
    "Marseille": "מארסיי",
    "Lyon": "ליון",
    "Monaco": "מונאקו",
    "Nice": "ניס",
    "Lille": "ליל",
    "Rennes": "רן",
    "MUFC": "מנצ׳סטר יונייטד",
    "MCFC": "מנצ׳סטר סיטי",
    "LFC": "ליברפול",
    "CFC": "צ׳לסי",
    "AFC": "ארסנל",
    "THFC": "טוטנהאם",
    "FCB": "ברצלונה",
    "Atleti": "אתלטיקו מדריד",
    "Atlético": "אתלטיקו מדריד",
    "Atletico Nacional": "אתלטיקו נסיונל",
    "Atlético Nacional": "אתלטיקו נסיונל",
    "Kaiserslautern": "קייזרסלאוטרן",
    "Bochum": "בוכום",
    "OM": "מארסיי",
    "Olympique de Marseille": "מארסיי",
    "Barça": "בארסה",
    "Barca": "בארסה",
}

PLAYER_REPLACEMENTS = {
    "Julian Alvarez": "ג׳וליאן אלווארז",
    "Julián Álvarez": "ג׳וליאן אלווארז",
    "Gabriel Jesus": "גבריאל ז׳סוס",
    "Samuel Martinez": "סמואל מרטינס",
    "Samuel Martínez": "סמואל מרטינס",
    "Massimiliano Allegri": "מסימיליאנו אלגרי",
    "Antonio Conte": "אנטוניו קונטה",
    "Mauricio Pochettino": "מאוריסיו פוצ׳טינו",
    "Oliver Glasner": "אוליבר גלסנר",
    "Andoni Iraola": "אנדוני איראולה",
    "Bruno Genesio": "ברונו ז׳נסיו",
    "Luis Enrique": "לואיס אנריקה",
    "Gregory Lorenzi": "גרגורי לורנצי",
    "Grégory Lorenzi": "גרגורי לורנצי",
    "Pep Guardiola": "פפ גווארדיולה",
    "Rayan": "ראיין",
    "Adam Dugdale": "אדם דוגדייל",
    "Will Salthouse": "וויל סולטהאוס",
    "Marcus Rashford": "מרקוס ראשפורד",
    "Anthony Gordon": "אנתוני גורדון",
    "Florian Wirtz": "פלוריאן וירץ",
    "Viktor Gyokeres": "ויקטור גיוקרש",
    "Victor Osimhen": "ויקטור אוסימן",
    "Kylian Mbappe": "קיליאן אמבפה",
    "Kylian Mbappé": "קיליאן אמבפה",
    "Vinicius Junior": "ויניסיוס ג׳וניור",
    "Vinícius Júnior": "ויניסיוס ג׳וניור",
    "Erling Haaland": "ארלינג הולאנד",
    "Mohamed Salah": "מוחמד סלאח",
    "Trent Alexander-Arnold": "טרנט אלכסנדר-ארנולד",
    "Alexander Isak": "אלכסנדר איסאק",
    "Bruno Fernandes": "ברונו פרננדש",
    "Lamine Yamal": "לאמין ימאל",
    "Nico Williams": "ניקו וויליאמס",
    "Rodrygo": "רודריגו",
    "Jude Bellingham": "ג׳וד בלינגהאם",
    "Harry Kane": "הארי קיין",
    "Lautaro Martinez": "לאוטרו מרטינס",
    "Lautaro Martínez": "לאוטרו מרטינס",
    "Rafael Leao": "רפאל לאאו",
    "Rafael Leão": "רפאל לאאו",
    "Xavi Simons": "צ׳אבי סימונס",
}

HEBREW_FINAL_FIXES = {
    "כאן אנחנו הולכים": "הנה זה קורה",
    "הנה אנחנו הולכים": "הנה זה קורה",
    "לפי הבנתי": "לפי המידע",
    "על פי מקורות": "לפי מקורות",
    "מקורות אומרים": "לפי מקורות",
    "הסכם מילולי": "סיכום בעל פה",
    "בדיקות רפואיות הוזמנו": "נקבעו בדיקות רפואיות",
    "בדיקה רפואית": "בדיקות רפואיות",
    "עסקת הלוואה": "עסקת השאלה",
    "מעבר הלוואה": "מעבר בהשאלה",
    "אופציה לקנות": "אופציית רכישה",
    "חובה לקנות": "חובת רכישה",
    "תשלום העברה": "דמי העברה",
    "העברה חינם": "העברה חופשית",
    "סוכן חופשי": "שחקן חופשי",
    "הצעה פורמלית": "הצעה רשמית",
    "הכרזה בקרוב": "הודעה רשמית בקרוב",
    "עסקה נעשתה": "עסקה סגורה",
    "מאמן ראש": "מאמן ראשי",
    "מנהל ספורטיבי": "מנהל מקצועי",
    "מנהל כדורגל": "מנהל מקצועי",
    "גיליון נקי": "שער נקי",
    "זמן עצירה": "תוספת הזמן",
    "זמן נוסף": "הארכה",
    "יריות עונשין": "דו-קרב פנדלים",
    "ליגה ראשונה": "הפרמייר ליג",
    "סדרה א": "סרייה א׳",
    "סרי א": "סרייה א׳",
    "טוויט": "פוסט",
    "ציוץ": "פוסט",
    "ציוצים": "פוסטים",
    " and ": " ו",
    " to ": " ל",
    " from ": " מ",
    " with ": " עם ",
    " for ": " עבור ",
    " in ": " ב",
    " on ": " על ",
    "ת׳האת׳להטיקפק": "דה אתלטיק",
    "ת'האת'להטיקפק": "דה אתלטיק",
    "סקיספורטדה": "סקיי ספורט גרמניה",
    "סקיספורט": "סקיי ספורט",
    "רמקספורט": "RMC ספורט",
    "רמק ספורט": "RMC ספורט",
    "פקבארקהלונא": "ברצלונה",
    "פקבייהרנ": "באיירן",
    "פק ו": "פ.ס.ז׳ ו",
    "פאריס פק": "פ.ס.ז׳",
    "נופק": "ניוקאסל",
    "ססקנאפולי": "נאפולי",
    "אללהגרי": "אלגרי",
    "מאססימיליאנו": "מסימיליאנו",
    "סקיספורטדה": "סקיי ספורט גרמניה",
    "ופל בוצ׳ומ": "בוכום",
    "האנדופארסהנאל": "הנד אוף ארסנל",
    "ברהאקינג": "דיווח דרמטי",
    "קהנטרהגואלס": "סנטר גולס",
    "ג׳יג׳אנטהספק": "ג׳יגאנטס",
    "אתלטיקונאקיונאל": "אתלטיקו נסיונל",
    "אטלéטיקונאקיונאל": "אתלטיקו נסיונל",
    "ת׳ה 29 y/o חלוץ will be זמין למשחק on a העברה חופשית": "החלוץ בן ה-29 יהיה זמין בהעברה חופשית",
    "not leading": "לא מובילה",
    "race to sign": "במרוץ להחתמת",
    "will be": "יהיה",
    "y/o": "בן",
    "sempre più su": "מתקרבת יותר ויותר ל",
    "per il post": "כמחליף של",
    "ha incontrato anche": "נפגשה גם עם",
    "del בארçא": "של בארסה",
    "con el agente de": "עם הסוכן של",
    "Noticia MD": "ידיעה של מונדו דפורטיבו",
}

STAT_REPLACEMENTS = {
    "goals": "שערים",
    "goal": "שער",
    "assists": "בישולים",
    "assist": "בישול",
    "appearances": "הופעות",
    "appearance": "הופעה",
    "matches": "משחקים",
    "match": "משחק",
    "minutes": "דקות",
    "apps": "הופעות",
}

LATIN_KEEP = {
    "VAR",
    "UEFA",
    "FIFA",
    "PSG",
    "MUFC",
    "MCFC",
    "LFC",
    "CFC",
    "AFC",
    "THFC",
    "FCB",
    "UCL",
    "UEL",
    "PL",
    "MLS",
    "RMC",
}

HEBREW_LETTER = {
    "a": "א",
    "b": "ב",
    "c": "ק",
    "d": "ד",
    "e": "ה",
    "f": "פ",
    "g": "ג",
    "h": "ה",
    "i": "י",
    "j": "ג׳",
    "k": "ק",
    "l": "ל",
    "m": "מ",
    "n": "נ",
    "o": "ו",
    "p": "פ",
    "q": "ק",
    "r": "ר",
    "s": "ס",
    "t": "ט",
    "u": "ו",
    "v": "ו",
    "w": "ו",
    "x": "קס",
    "y": "י",
    "z": "ז",
}


@dataclass
class Post:
    post_id: str
    username: str
    text: str
    link: str
    image_urls: list[str]
    video_urls: list[str]
    has_video: bool
    primary_has_video: bool
    quoted_has_video: bool
    quoted_author: str
    quoted_text: str


def http_get(url: str, timeout: int = FEED_REQUEST_TIMEOUT_SECONDS) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
    )
    last_error: Exception | None = None
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            if attempt < HTTP_RETRIES:
                time.sleep(RETRY_SLEEP_SECONDS * attempt)
    raise RuntimeError(f"GET failed after {HTTP_RETRIES} attempts: {url}. Last error: {last_error}")


def http_post_json(url: str, payload: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
            return json.loads(raw)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                error_data = json.loads(raw)
                retry_after = error_data.get("parameters", {}).get("retry_after")
            except Exception:
                retry_after = None
            last_error = RuntimeError(f"HTTP {exc.code}: {raw}")
            if exc.code == 429 and retry_after:
                time.sleep(int(retry_after) + 1)
            elif attempt < HTTP_RETRIES:
                time.sleep(RETRY_SLEEP_SECONDS * attempt)
        except Exception as exc:
            last_error = exc
            if attempt < HTTP_RETRIES:
                time.sleep(RETRY_SLEEP_SECONDS * attempt)
    raise RuntimeError(f"POST failed after {HTTP_RETRIES} attempts: {url}. Last error: {last_error}")


def strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def child_text(element: ET.Element, names: tuple[str, ...]) -> str:
    for child in element:
        if strip_namespace(child.tag) in names and child.text:
            return child.text.strip()
    return ""


def clean_text(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value or "", flags=re.IGNORECASE)
    value = re.sub(r"</p\s*>", "\n\n", value, flags=re.IGNORECASE)
    value = re.sub(r"</div\s*>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n+ *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def is_image_url(url: str) -> bool:
    lowered = url.lower().split("?", 1)[0]
    if lowered.endswith(VIDEO_EXTENSIONS):
        return False
    return lowered.endswith(IMAGE_EXTENSIONS) or "pbs.twimg.com/media" in lowered


def is_video_url(url: str) -> bool:
    lowered = url.lower().split("?", 1)[0]
    return lowered.endswith(VIDEO_EXTENSIONS) or "video.twimg.com" in lowered


def extract_images(raw_html: str, element: ET.Element) -> list[str]:
    images: list[str] = []
    for match in re.findall(r"<img[^>]+src=[\"']([^\"']+)[\"']", raw_html or "", re.I):
        url = html.unescape(match)
        if is_image_url(url):
            images.append(url)
    for child in element.iter():
        url = child.attrib.get("url") or child.attrib.get("href")
        mime = (child.attrib.get("type") or "").lower()
        medium = (child.attrib.get("medium") or "").lower()
        if url and (mime.startswith("image/") or medium == "image" or is_image_url(url)):
            images.append(url)
    return list(dict.fromkeys(images))


def extract_videos(raw_html: str, element: ET.Element) -> list[str]:
    videos: list[str] = []
    for match in re.findall(r"https?://[^\s\"'<>]+", raw_html or "", re.I):
        url = html.unescape(match)
        if is_video_url(url):
            videos.append(url)
    for child in element.iter():
        url = child.attrib.get("url") or child.attrib.get("href")
        mime = (child.attrib.get("type") or "").lower()
        medium = (child.attrib.get("medium") or "").lower()
        if url and (mime.startswith("video/") or medium == "video" or is_video_url(url)):
            videos.append(url)
    return list(dict.fromkeys(videos))


def has_video_marker(raw_html: str, element: ET.Element) -> bool:
    lowered = (raw_html or "").lower()
    if "video.twimg.com" in lowered or "media:player" in lowered:
        return True
    for child in element.iter():
        mime = (child.attrib.get("type") or "").lower()
        medium = (child.attrib.get("medium") or "").lower()
        if mime.startswith("video/") or medium == "video":
            return True
    return False


def text_has_video_marker(text: str) -> bool:
    return bool(re.search(r"(?im)^\s*(video|watch video|וידאו|וידיאו)\s*$", text or ""))


def split_primary_and_quoted_text(text: str) -> tuple[str, str, str]:
    lines = [line.strip() for line in (text or "").splitlines()]
    kept: list[str] = []
    quoted: list[str] = []
    quoted_author = ""
    in_quote = False

    for line in lines:
        if not line:
            if in_quote:
                if quoted and quoted[-1]:
                    quoted.append("")
            elif kept and kept[-1]:
                kept.append("")
            continue
        if kept and re.search(r"\(@[A-Za-z0-9_]{1,20}\)", line):
            quoted_author = re.sub(r"\s*\(@[A-Za-z0-9_]{1,20}\).*", "", line).strip()
            in_quote = True
            continue
        if kept and line.lower() in {"quoted post", "quote", "retweet", "retweeted"}:
            in_quote = True
            continue
        if in_quote:
            quoted.append(line)
        else:
            kept.append(line)

    primary_text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept).strip()) or text
    quoted_text = re.sub(r"\n{3,}", "\n\n", "\n".join(quoted).strip())
    return primary_text, quoted_author, quoted_text


def normalize_link(link: str, username: str) -> str:
    if not link:
        return f"https://x.com/{username}"
    parsed = urllib.parse.urlparse(link)
    if "nitter" in parsed.netloc and parsed.path:
        return f"https://x.com{parsed.path}"
    return link


def parse_posts(username: str, xml_bytes: bytes) -> list[Post]:
    root = ET.fromstring(xml_bytes)
    items = [element for element in root.iter() if strip_namespace(element.tag) in ("item", "entry")]
    posts: list[Post] = []
    for item in items:
        title = child_text(item, ("title",))
        description = child_text(item, ("description", "summary", "content"))
        raw_text = description or title
        text, quoted_author, quoted_text = split_primary_and_quoted_text(clean_text(raw_text))
        link = normalize_link(child_text(item, ("link",)), username)

        if not link:
            for child in item:
                if strip_namespace(child.tag) == "link" and child.attrib.get("href"):
                    link = normalize_link(child.attrib["href"], username)
                    break

        guid = child_text(item, ("guid", "id")) or link or title
        post_id = f"{username}:{guid}"
        images = extract_images(raw_text, item)
        videos = extract_videos(raw_text, item)
        raw_has_video = bool(videos) or has_video_marker(raw_text, item)
        primary_has_video = text_has_video_marker(text)
        quoted_has_video = text_has_video_marker(quoted_text)
        if raw_has_video and not primary_has_video and not quoted_has_video:
            quoted_has_video = bool(quoted_text)
            primary_has_video = not quoted_has_video
        has_video = raw_has_video or primary_has_video or quoted_has_video

        if text or link:
            posts.append(
                Post(
                    post_id=post_id,
                    username=username,
                    text=text,
                    link=link,
                    image_urls=images,
                    video_urls=videos,
                    has_video=has_video,
                    primary_has_video=primary_has_video,
                    quoted_has_video=quoted_has_video,
                    quoted_author=quoted_author,
                    quoted_text=quoted_text,
                )
            )
    return posts


def fetch_posts(username: str) -> list[Post]:
    for template in FEED_TEMPLATES:
        url = template.format(username=urllib.parse.quote(username))
        try:
            posts = parse_posts(username, http_get(url))
            if posts:
                return posts
        except Exception as exc:
            logging.warning("Feed failed for @%s: %s", username, exc)
    logging.error("All feed sources failed or returned empty for @%s", username)
    return []


def apply_phrase_replacements(text: str, replacements: dict[str, str]) -> str:
    for source, target in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        if re.fullmatch(r"[A-Za-z0-9 ._'’:-]+", source):
            pattern = r"(?<![A-Za-z0-9_])" + re.escape(source) + r"(?![A-Za-z0-9_])"
            text = re.sub(pattern, target, text, flags=re.IGNORECASE)
        else:
            text = text.replace(source, target)
    return text


def apply_team_replacements(text: str) -> str:
    return apply_phrase_replacements(text, TEAM_REPLACEMENTS)


def apply_player_replacements(text: str) -> str:
    return apply_phrase_replacements(text, PLAYER_REPLACEMENTS)


def normalize_stats(text: str) -> str:
    for english, hebrew in STAT_REPLACEMENTS.items():
        text = re.sub(rf"\b(\d+)\s*{re.escape(english)}\b", rf"\1 {hebrew}", text, flags=re.IGNORECASE)
        text = re.sub(rf"\b{re.escape(english)}\s*(\d+)\b", rf"\1 {hebrew}", text, flags=re.IGNORECASE)
    return text


def remove_article_links(text: str) -> str:
    """Backward-compatible wrapper: remove all external links from post text.

    The post URL and video URL are still added separately by build_message().
    This function only cleans links that appeared inside the post body.
    """
    return remove_external_links(text)


def remove_external_links(text: str) -> str:
    """Remove links that appeared inside the post body.

    build_message() still adds the real X post link separately at the end,
    and video links are still added only when the code detects a video.
    """
    text = text or ""
    # Full URLs, including X short links such as t.co and article links.
    text = re.sub(r"https?://[^\s<>()]+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"www\.[^\s<>()]+", "", text, flags=re.IGNORECASE)
    # Bare domains that sometimes remain after RSS/HTML cleanup, e.g. skysports.com/...
    text = BARE_EXTERNAL_DOMAIN_RE.sub("", text)
    # Some mirrors leave shortened/link-only tokens without scheme.
    text = re.sub(r"(?<!@)\b(?:t\.co|x\.com|twitter\.com)/\S+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?m)^\s*(?:🔗|link|לינק|קישור)\s*:?.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def apply_handle_replacements(text: str) -> str:
    for source, target in sorted(HANDLE_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True):
        if source.startswith("@"):
            pattern = r"(?<![A-Za-z0-9_])" + re.escape(source) + r"(?![A-Za-z0-9_])"
        else:
            pattern = r"(?<![@A-Za-z0-9_])" + re.escape(source) + r"(?![A-Za-z0-9_])"
        text = re.sub(pattern, target, text, flags=re.IGNORECASE)
    return text


def clean_before_translation(text: str) -> str:
    text = html.unescape(text or "")
    # Remove URLs/domains first so bare domains like lequipe.fr do not become לאקיפ.fr.
    text = remove_external_links(text)
    text = apply_handle_replacements(text)
    text = re.sub(r"(?<!\w)#([A-Za-z0-9_]+)", r"\1", text)
    # Unknown @mentions: keep the handle text, but remove @ so Telegram won't create a clickable mention.
    text = re.sub(r"(?<!\w)@([A-Za-z0-9_]+)", r"\1", text)
    text = re.sub(r"(?im)^\s*(video|watch video|וידאו|וידיאו)\s*$", "", text)
    text = text.replace("&amp;", "&")
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def google_translate(text: str) -> str:
    query = urllib.parse.urlencode(
        {"client": "gtx", "sl": "auto", "tl": TARGET_LANGUAGE, "dt": "t", "q": text}
    )
    url = f"https://translate.googleapis.com/translate_a/single?{query}"
    data = json.loads(http_get(url, timeout=20).decode("utf-8"))
    return "".join(part[0] for part in data[0] if part and part[0]).strip()


def mymemory_translate(text: str) -> str:
    query = urllib.parse.urlencode({"q": text, "langpair": f"auto|{TARGET_LANGUAGE}"})
    url = f"https://api.mymemory.translated.net/get?{query}"
    data = json.loads(http_get(url, timeout=20).decode("utf-8"))
    return html.unescape(data.get("responseData", {}).get("translatedText", "")).strip()


def latin_ratio(text: str) -> float:
    hebrew = len(re.findall(r"[א-ת]", text or ""))
    latin = len(re.findall(r"[A-Za-z]", text or ""))
    if hebrew + latin == 0:
        return 0.0
    return latin / (hebrew + latin)


def looks_untranslated(original: str, translated: str) -> bool:
    if not translated:
        return True
    original_clean = re.sub(r"\s+", " ", original).strip().lower()
    translated_clean = re.sub(r"\s+", " ", translated).strip().lower()
    if original_clean == translated_clean:
        return True
    return latin_ratio(translated) > 0.45


def translate_in_sentences(text: str) -> str:
    pieces = re.split(r"(?<=[.!?])\s+|\n+", text)
    translated: list[str] = []
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        try:
            translated.append(google_translate(piece))
            time.sleep(0.05)
        except Exception:
            translated.append(piece)
    return "\n\n".join(translated).strip()


def transliterate_word(word: str) -> str:
    lower = word.lower()
    special = [
        ("ch", "צ׳"),
        ("sh", "ש"),
        ("th", "ת׳"),
        ("ph", "פ"),
        ("ck", "ק"),
        ("oo", "ו"),
        ("ee", "י"),
        ("ou", "או"),
        ("ai", "יי"),
        ("ay", "יי"),
        ("ei", "יי"),
        ("ie", "י"),
    ]
    out = ""
    i = 0
    while i < len(lower):
        matched = False
        for src, dst in special:
            if lower.startswith(src, i):
                out += dst
                i += len(src)
                matched = True
                break
        if matched:
            continue
        ch = lower[i]
        out += HEBREW_LETTER.get(ch, ch)
        i += 1
    return out.strip("׳-' ")


def transliterate_latin_names(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        phrase = match.group(0).strip()
        if phrase in LATIN_KEEP:
            return phrase
        if len(phrase) <= 2:
            return phrase
        if phrase.lower() in {"com", "http", "https", "www"}:
            return ""
        words = re.split(r"[\s_-]+", phrase)
        return " ".join(transliterate_word(word) for word in words if word)

    return re.sub(r"\b[A-Z][A-Za-zÀ-ÿ'’-]*(?:[\s_-]+[A-Z][A-Za-zÀ-ÿ'’-]*)*\b", repl, text)


def final_hebrew_polish(text: str) -> str:
    text = html.unescape(text or "")
    # Remove URLs/domains first so bare domains like lequipe.fr do not become לאקיפ.fr.
    text = remove_external_links(text)
    text = apply_handle_replacements(text)
    text = apply_team_replacements(text)
    text = apply_player_replacements(text)
    text = apply_phrase_replacements(text, HEBREW_FINAL_FIXES)
    text = normalize_stats(text)
    text = transliterate_latin_names(text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"([א-ת])\s+-\s+([א-ת])", r"\1-\2", text)
    text = re.sub(r"\b(\d+)\s*-\s*(\d+)\b", r"\1-\2", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.replace("\n ", "\n").replace(" \n", "\n")
    return text.strip()


def translate_text(text: str) -> str:
    if not text:
        return ""
    cleaned = clean_before_translation(text)
    prepared = apply_player_replacements(apply_team_replacements(apply_phrase_replacements(cleaned, FOOTBALL_TERMS)))
    last_error: Exception | None = None

    for source_text in (prepared, cleaned):
        for provider in ("google", "mymemory"):
            try:
                translated = google_translate(source_text) if provider == "google" else mymemory_translate(source_text)
                if looks_untranslated(source_text, translated):
                    translated = translate_in_sentences(source_text)
                translated = final_hebrew_polish(translated)
                if latin_ratio(translated) <= 0.25:
                    return translated
            except Exception as exc:
                last_error = exc
                logging.warning("Translation failed with %s: %s", provider, exc)

    logging.error("Translation fallback used. Last error: %s", last_error)
    return final_hebrew_polish(prepared)


def tidy_translated_text(text: str) -> str:
    text = html.unescape(text or "").strip()
    text = final_hebrew_polish(text)
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"(?im)^\s*(וידאו|וידיאו)\s*$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def rtl(text: str) -> str:
    return "\n".join(f"{RTL_MARK}{line}" if line.strip() else line for line in text.splitlines())


def telegram_api(method: str, payload: dict[str, Any]) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    response = http_post_json(url, payload)
    if not response.get("ok"):
        raise RuntimeError(f"Telegram error: {response}")


def trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def trim_keep_ending(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    parts = text.rsplit("\n\n", 1)
    if len(parts) == 2 and len(parts[1]) < limit - 80:
        ending = parts[1]
        prefix_limit = limit - len(ending) - 6
        return text[:prefix_limit].rstrip() + "...\n\n" + ending
    return trim(text, limit)


def build_message(post: Post, translated: str, quoted_translated: str = "") -> str:
    translated = tidy_translated_text(translated)
    quoted_translated = tidy_translated_text(quoted_translated)
    display_name = ACCOUNT_DISPLAY_NAMES.get(post.username, post.username)
    safe_account = html.escape(rtl(f"{display_name}:"))
    safe_body = html.escape(rtl(translated or "עדכון חדש"))
    safe_quoted_author = html.escape(rtl(final_hebrew_polish(post.quoted_author or "פוסט מצוטט")))
    safe_quoted_body = html.escape(rtl(quoted_translated))
    safe_link = html.escape(post.link)
    video_label = f"<b>{html.escape(rtl('וידיאו מצורף:'))}</b>"
    post_link_label = f"<b>{html.escape(rtl('קישור לפוסט:'))}</b>"
    parts = [f"<b>{safe_account}</b>", "", safe_body]
    if post.link and post.primary_has_video:
        parts.extend(["", "", video_label, safe_link])
    if safe_quoted_body:
        parts.extend(["", f"<b>{html.escape(rtl('פוסט מצוטט:'))}</b>", safe_quoted_author, safe_quoted_body])
        if post.link and post.quoted_has_video:
            parts.extend(["", video_label, safe_link])
    if post.link:
        parts.extend(["", "", post_link_label, safe_link])
    return "\n".join(parts)


def send_post(post: Post) -> None:
    translated = translate_text(post.text)
    quoted_translated = translate_text(post.quoted_text) if post.quoted_text else ""
    message = build_message(post, translated, quoted_translated)
    images = post.image_urls[:MAX_IMAGES_PER_POST]
    if images and SEND_IMAGES_AFTER_TEXT:
        telegram_api(
            "sendMessage",
            {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": trim(message, 4096),
                "disable_web_page_preview": True,
                "parse_mode": "HTML",
            },
        )
        media = [{"type": "photo", "media": image_url} for image_url in images]
        try:
            telegram_api("sendMediaGroup", {"chat_id": TELEGRAM_CHAT_ID, "media": media})
        except Exception as exc:
            logging.warning("Text was sent, but images failed: %s", exc)
        return

    if images:
        media: list[dict[str, Any]] = []
        for index, image_url in enumerate(images):
            item: dict[str, Any] = {"type": "photo", "media": image_url}
            if index == 0:
                item["caption"] = trim_keep_ending(message, 1024)
                item["parse_mode"] = "HTML"
            media.append(item)
        try:
            telegram_api("sendMediaGroup", {"chat_id": TELEGRAM_CHAT_ID, "media": media})
            return
        except Exception as exc:
            logging.warning("Could not send images, falling back to text only: %s", exc)

    telegram_api(
        "sendMessage",
        {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": trim(message, 4096),
            "disable_web_page_preview": True,
            "parse_mode": "HTML",
        },
    )


def state_path() -> Path:
    return Path(__file__).resolve().parent / STATE_FILE


def load_state() -> dict[str, list[str]]:
    path = state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {key: list(value) for key, value in data.items()}
    except Exception:
        logging.warning("Could not read state file. Starting fresh.")
        return {}


def save_state(state: dict[str, list[str]]) -> None:
    path = state_path()
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def validate_settings() -> None:
    if not TELEGRAM_BOT_TOKEN or "PASTE" in TELEGRAM_BOT_TOKEN:
        raise ValueError("Put your Telegram bot token in TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID or "PUT_" in str(TELEGRAM_CHAT_ID) or "PASTE" in str(TELEGRAM_CHAT_ID):
        raise ValueError("Put your Telegram group chat ID in TELEGRAM_CHAT_ID")
    if not X_ACCOUNTS:
        raise ValueError("Add at least one X/Twitter account to X_ACCOUNTS")


def fetch_posts_safely(username: str) -> tuple[str, list[Post]]:
    try:
        return username, fetch_posts(username)
    except Exception as exc:
        logging.error("Unexpected fetch failure for @%s: %s", username, exc)
        return username, []


def fetch_all_accounts() -> dict[str, list[Post]]:
    """Fetch all accounts in parallel so a full scan is not one-by-one."""
    results: dict[str, list[Post]] = {username: [] for username in X_ACCOUNTS}
    workers = min(MAX_PARALLEL_ACCOUNT_CHECKS, max(1, len(X_ACCOUNTS)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(fetch_posts_safely, username): username for username in X_ACCOUNTS}
        for future in as_completed(future_map):
            username, posts = future.result()
            results[username] = posts
    return results


def run_once(state: dict[str, list[str]], startup_cycle: bool = False) -> int:
    first_run = not any(state.values())
    sent = 0
    all_posts = fetch_all_accounts()

    for username in X_ACCOUNTS:
        seen = set(state.get(username, []))
        posts = all_posts.get(username, [])
        if not posts:
            continue
        new_posts = [post for post in posts if post.post_id not in seen]
        if startup_cycle and SEND_LAST_POST_ON_EVERY_START:
            latest_post = posts[0]
            try:
                send_post(latest_post)
                seen.add(latest_post.post_id)
                sent += 1
            except Exception as exc:
                logging.error("Failed sending startup latest post for @%s: %s", username, exc)
            for post in posts:
                seen.add(post.post_id)
            state[username] = list(seen)[-300:]
            continue
        if first_run and SEND_LAST_POST_ON_FIRST_RUN:
            latest_post = posts[0]
            if latest_post.post_id not in seen:
                try:
                    send_post(latest_post)
                    seen.add(latest_post.post_id)
                    sent += 1
                except Exception as exc:
                    logging.error("Failed sending startup test post for @%s: %s", username, exc)
            for post in posts:
                seen.add(post.post_id)
            state[username] = list(seen)[-300:]
            continue
        if first_run:
            for post in posts:
                seen.add(post.post_id)
            state[username] = list(seen)[-300:]
            continue
        for post in reversed(new_posts[:MAX_NEW_POSTS_PER_ACCOUNT_PER_CHECK]):
            try:
                send_post(post)
                seen.add(post.post_id)
                sent += 1
                time.sleep(0.2)
            except Exception as exc:
                logging.error("Failed sending %s: %s", post.link, exc)
        state[username] = list(seen)[-300:]
    return sent

def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    validate_settings()
    print(f"Football bot is running. Accounts: {', '.join('@' + account for account in X_ACCOUNTS)}", flush=True)
    print(f"Checking every {CHECK_EVERY_SECONDS} seconds.", flush=True)
    if SEND_STARTUP_STATUS_MESSAGE:
        try:
            telegram_api(
                "sendMessage",
                {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": "בוט הכדורגל הופעל. עכשיו בודק פוסטים אחרונים...",
                    "disable_web_page_preview": True,
                },
            )
        except Exception as exc:
            logging.error("Startup Telegram test message failed: %s", exc)
    startup_cycle = True
    while True:
        cycle_started = time.time()
        try:
            state = load_state()
            sent = run_once(state, startup_cycle=startup_cycle)
            startup_cycle = False
            save_state(state)
            if sent:
                print(f"Sent {sent} new post(s).", flush=True)
        except Exception as exc:
            logging.error("Unexpected error. Bot will keep running: %s", exc)

        elapsed = time.time() - cycle_started
        # Start the next cycle every 45 seconds from the previous cycle start.
        # If a cycle takes longer because many new posts are being translated/sent,
        # start the next one immediately instead of adding another 45-second wait.
        time.sleep(max(0, CHECK_EVERY_SECONDS - elapsed))


if __name__ == "__main__":
    main()

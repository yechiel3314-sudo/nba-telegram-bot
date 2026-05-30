#!/usr/bin/env python3
"""
Single-file X/Twitter to Telegram NBA news forwarder.

Run:
  python3 x_to_telegram_single.py

What this version does:
- Scans all accounts in parallel every 30 seconds.
- Checks several public RSS mirrors for each account and merges the results.
- Sends photos together with the Telegram message caption.
- Never sends videos as files. If a post has video, it adds a video link line.
- Removes all links from the post body. Only the final X post link is kept.
- Uses Gemini translation if you add GEMINI_API_KEY or GEMINI_API_KEYS.
- Falls back to free Google Translate + MyMemory if Gemini is unavailable.

Important:
- ChatGPT Plus does not include API usage for a server bot.
- RSS mirrors can be late. If the mirror itself publishes late, the bot cannot
  see the post earlier without an official/paid X data source.
"""

from __future__ import annotations

import hashlib
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
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


# ====== SETTINGS ======

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "8795392686:AAFElKo3sML_dqA9YaVz2iArTUoYGcGgBuI",
)
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-1003918247986")

# Optional AI translation. Put this in Railway Variables:
# GEMINI_API_KEY=your_key
# Or several keys separated by commas:
# GEMINI_API_KEYS=key1,key2,key3
GEMINI_API_KEYS = [
    key.strip()
    for key in (
        os.environ.get("GEMINI_API_KEYS", "") or os.environ.get("GEMINI_API_KEY", "")
    ).split(",")
    if key.strip()
]
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
GEMINI_FAST_MODEL = os.environ.get("GEMINI_FAST_MODEL", GEMINI_MODEL)

X_ACCOUNTS = [
    "NBA",
    "ShamsCharania",
    "highkin",
    "ChrisBHaynes",
    "UnderdogNBA",
    "TheDunkCentral",
    "LegionHoops",
    "NBACentral",
    "ClutchPoints",
]

PRIORITY_X_ACCOUNTS = set(X_ACCOUNTS)

ACCOUNT_DISPLAY_NAMES = {
    "NBA": "NBA",
    "ShamsCharania": "שאמס צ'ראניה",
    "highkin": "שון הייקין - פורטלנד",
    "ChrisBHaynes": "כריס היינס",
    "UnderdogNBA": "אנדרדוג NBA",
    "TheDunkCentral": "דאנק סנטרל",
    "LegionHoops": "לגיון הופס",
    "NBACentral": "NBA סנטרל",
    "ClutchPoints": "קלאץ' פוינטס",
}

TARGET_LANGUAGE = "he"
CHECK_EVERY_SECONDS = 8
HTTP_RETRIES = 3
REQUEST_TIMEOUT_SECONDS = 10
FEED_REQUEST_TIMEOUT_SECONDS = 4
FEED_COLLECTION_TIMEOUT_SECONDS = 5
MAX_PARALLEL_ACCOUNT_CHECKS = 28
MAX_PARALLEL_FEED_CHECKS_PER_ACCOUNT = 8
MAX_NEW_POSTS_PER_ACCOUNT_PER_CHECK = 20
NIGHT_MODE_ENABLED = True
NIGHT_START_HOUR = 0
NIGHT_END_HOUR = 7
NIGHT_CHECK_EVERY_SECONDS = 30
NIGHT_MAX_PARALLEL_ACCOUNT_CHECKS = 8
NIGHT_MAX_PARALLEL_POST_SENDS = 4
SEND_LAST_POST_ON_FIRST_RUN = False
SEND_LAST_POST_ON_EVERY_START = False
SEND_STARTUP_STATUS_MESSAGE = False
SHABBAT_MODE_ENABLED = True
SHABBAT_TIMEZONE = "Asia/Jerusalem"
SHABBAT_HEBCAL_GEOID = "281184"  # Jerusalem
SHABBAT_HAVDALAH_MINUTES = 50
SHABBAT_HEBCAL_CACHE_SECONDS = 6 * 60 * 60
SHABBAT_HEBCAL_TIMEOUT_SECONDS = 4
SHABBAT_SLEEP_SECONDS = 300
SHABBAT_CACHE_FILE = "nba_shabbat_times_cache.json"
MAX_PARALLEL_POST_SENDS = 12
MAX_IMAGES_PER_POST = 4
MAX_VIDEO_BYTES = 50 * 1024 * 1024
SEND_VIDEO_FILES = True
STATE_FILE = "nba_x_to_telegram_state.json"
TRANSLATION_CACHE_FILE = "nba_translation_cache.json"
RTL_MARK = "\u200f"

FEED_TEMPLATES = [
    "https://rsshub.app/twitter/user/{username}",
    "https://rsshub.rssforever.com/twitter/user/{username}",
    "https://nitter.net/{username}/rss",
    "https://nitter.poast.org/{username}/rss",
    "https://nitter.privacydev.net/{username}/rss",
    "https://nitter.tiekoetter.com/{username}/rss",
    "https://nitter.oksocial.net/{username}/rss",
]

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
VIDEO_EXTENSIONS = (".mp4", ".mov", ".m3u8", ".webm", ".avi", ".mkv")

BARE_EXTERNAL_DOMAIN_RE = re.compile(
    r"(?<!@)\b(?:[A-Za-z0-9-]+\.)+(?:com|co\.uk|net|org|io|app|fr|it|es|de|co|uk|news|sport|football|tv)(?:/[^\s]*)?",
    re.IGNORECASE,
)

URL_RE = re.compile(
    r"https?://[^\s<>()\"']+|www\.[^\s<>()\"']+|(?<!@)\b(?:t\.co|x\.com|twitter\.com)/\S+",
    re.IGNORECASE,
)

PODCAST_BLOCK_PATTERNS = (
    r"\bpodcast\b",
    r"\bfull\s+episode\b",
    r"\bfull\s+show\b",
    r"\blisten\s+(?:now|to|here)\b",
    r"\bwatch\s+(?:now|the\s+full|here)\b",
    r"\bnew\s+episode\b",
    r"\bepisode\s+\d+\b",
    r"האזינו",
    r"להאזנה",
    r"פודקאסט",
    r"הפודקאסט",
    r"צפו\s+בפודקאסט",
    r"צפו\s+בפרק",
    r"פרק\s+מלא",
    r"הפרק\s+המלא",
    r"לצפייה\s+בפרק",
    r"לצפייה\s+בפודקאסט",
    r"פרק\s+חדש",
)

PODCAST_DOMAINS = (
    "spotify.com",
    "open.spotify.com",
    "podcasts.apple.com",
    "apple.co",
    "podcasts.google.com",
    "anchor.fm",
    "podbean.com",
    "buzzsprout.com",
    "megaphone.fm",
    "omny.fm",
    "simplecast.com",
    "acast.com",
    "audioboom.com",
    "iheart.com",
    "soundcloud.com",
)


# ====== TRANSLATION DICTIONARIES ======

HANDLE_REPLACEMENTS = {
    "NBA": "NBA",
    "WNBA": "WNBA",
    "ShamsCharania": "שאמס צ'ראניה",
    "Shams Charania": "שאמס צ'ראניה",
    "Shams": "שאמס",
    "highkin": "שון הייקין",
    "Sean Highkin": "שון הייקין",
    "TheSteinLine": "מארק סטיין",
    "wojespn": "אדריאן ווג'נרובסקי",
    "espn_macmahon": "טים מקמהון",
    "BobbyMarks42": "בובי מרקס",
    "ChrisBHaynes": "כריס היינס",
    "UnderdogNBA": "אנדרדוג NBA",
    "TheDunkCentral": "דאנק סנטרל",
    "LegionHoops": "לגיון הופס",
    "NBACentral": "NBA סנטרל",
    "ClutchPoints": "קלאץ' פוינטס",
    "espn": "ESPN",
    "ESPNNBA": "ESPN NBA",
    "espn_macmahon": "טים מקמהון",
    "FabrizioRomano": "פבריציו רומאנו",
    "David_Ornstein": "דיוויד אורנשטיין",
    "DiMarzio": "ג'אנלוקה די מארציו",
    "JacobsBen": "בן ג'ייקובס",
    "NicoSchira": "ניקולה סקירה",
    "lauriewhitwell": "לורי וויטוול",
    "SamLee": "סם לי",
    "_pauljoyce": "פול ג'ויס",
    "Matt_Law_DT": "מאט לאו",
    "SimonJones_DM": "סיימון ג'ונס",
    "MatteMoretto": "מתאו מורטו",
    "ffpolo": "פרננדו פולו",
    "gerardromero": "ג'ראד רומרו",
    "AranchaMOBILE": "ארנצ'ה רודריגז",
    "JLSanchez78": "חוסה לואיס סאנצ'ס",
    "AlfredoPedulla": "אלפרדו פדולה",
    "86_longo": "דניאלה לונגו",
    "Plettigoal": "פלוריאן פלטנברג",
    "cfbayern": "כריסטיאן פאלק",
    "FabriceHawkins": "פבריס הוקינס",
    "Tanziloic": "לואיק טנזי",
    "MonfortCarlos": "קרלוס מונפור",
    "SkySports": "סקיי ספורטס",
    "SkySportsNews": "סקיי ספורטס ניוז",
    "TheAthletic": "דה אתלטיק",
    "TheAthleticFC": "דה אתלטיק",
    "BBCSport": "בי-בי-סי ספורט",
    "ESPNFC": "ESPN FC",
    "guardian_sport": "הגרדיאן ספורט",
    "TeleFootball": "טלגרף פוטבול",
    "MailSport": "דיילי מייל ספורט",
    "SkySportDE": "סקיי ספורט גרמניה",
    "skysportde": "סקיי ספורט גרמניה",
    "kerry_hau": "קרי האו",
    "PipersierraR": "פיפה סיירה",
    "CLMerlo": "ססאר לואיס מרלו",
    "mundodeportivo": "מונדו דפורטיבו",
    "JijantesFC": "ג'יגאנטס",
    "RMCsport": "RMC ספורט",
    "lequipe": "לאקיפ",
    "ActuFoot_": "אקטו פוט",
    "MadridXtra": "מדריד אקסטרה",
    "ManagingBarca": "מנג'ינג בארסה",
    "Barca_Buzz": "בארסה באז",
    "iMiaSanMia": "מיה סן מיה",
}

SELF_QUOTE_ALIASES = {
    "NBA": ["NBA", "NBA Today", "אן בי איי"],
    "ShamsCharania": ["Shams Charania", "Shams", "שאמס צ'ראניה", "שאמס צראניה", "שאמש צ'ראניה"],
    "highkin": ["Sean Highkin", "Highkin", "שון הייקין", "שון הייקין - פורטלנד"],
    "ChrisBHaynes": ["Chris Haynes", "כריס היינס"],
    "UnderdogNBA": ["Underdog NBA", "אנדרדוג NBA"],
    "TheDunkCentral": ["Dunk Central", "The Dunk Central", "דאנק סנטרל"],
    "LegionHoops": ["Legion Hoops", "לגיון הופס"],
    "NBACentral": ["NBA Central", "NBA סנטרל"],
    "ClutchPoints": ["ClutchPoints", "Clutch Points", "קלאץ' פוינטס"],
}

FOOTBALL_TERMS = {
    "league sources tell": "לפי מקורות בליגה",
    "sources tell": "לפי מקורות",
    "sources say": "לפי מקורות",
    "per sources": "לפי מקורות",
    "breaking": "דיווח דרמטי",
    "free agent": "שחקן חופשי",
    "free agency": "שוק השחקנים החופשיים",
    "trade deadline": "דדליין הטריידים",
    "trade": "טרייד",
    "traded": "עבר בטרייד",
    "has been traded": "עבר בטרייד",
    "is being traded": "עובר בטרייד",
    "has requested a trade": "ביקש טרייד",
    "sign-and-trade": "חתימה והעברה",
    "first-round pick": "בחירת סיבוב ראשון",
    "second-round pick": "בחירת סיבוב שני",
    "draft pick": "בחירת דראפט",
    "NBA Draft": "דראפט ה-NBA",
    "two-way contract": "חוזה דו-כיווני",
    "two-way": "דו-כיווני",
    "training camp": "מחנה האימונים",
    "regular season": "העונה הסדירה",
    "postseason": "הפלייאוף",
    "playoffs": "הפלייאוף",
    "Finals": "הגמר",
    "conference finals": "גמר האזור",
    "game winner": "סל ניצחון",
    "career-high": "שיא קריירה",
    "season-high": "שיא עונתי",
    "home court": "הבית",
    "on the season": "העונה",
    "behind big performances from": "בזכות הופעות גדולות של",
    "went off": "התפוצץ",
    "extension": "הארכת חוזה",
    "max contract": "חוזה מקסימום",
    "rookie scale extension": "הארכת חוזה רוקי",
    "waived": "שוחרר",
    "buyout": "בייאאוט",
    "injury report": "דוח פציעות",
    "questionable": "בספק",
    "probable": "ככל הנראה ישחק",
    "ruled out": "לא ישחק",
    "questionable to return": "בספק לחזור",
    "doubtful": "בספק גדול",
    "day-to-day": "יום-יומי",
    "minutes restriction": "הגבלת דקות",
    "starting lineup": "החמישייה הפותחת",
    "depth chart": "רוטציה",
    "front office": "הנהלת הקבוצה",
    "head coach": "המאמן הראשי",
    "assistant coach": "עוזר המאמן",
    "general manager": "הג'נרל מנג'ר",
    "president of basketball operations": "נשיא פעולות הכדורסל",
    "basketball operations": "פעולות הכדורסל",
    "salary cap": "תקרת השכר",
    "luxury tax": "מס המותרות",
    "tax apron": "אפרון המס",
    "second apron": "האפרון השני",
    "player option": "אופציית שחקן",
    "team option": "אופציית קבוצה",
    "non-guaranteed": "לא מובטח",
    "guaranteed": "מובטח",
    "hard cap": "תקרה קשיחה",
    "double-double": "דאבל-דאבל",
    "triple-double": "טריפל-דאבל",
    "clutch": "קלאץ'",
    "buzzer-beater": "סל עם הבאזר",
    "shot clock": "שעון הזריקות",
    "overtime": "הארכה",
    "OT": "הארכה",
    "MVP": "MVP",
    "points": "נקודות",
    "rebounds": "ריבאונדים",
    "assists": "אסיסטים",
    "steals": "חטיפות",
    "blocks": "חסימות",
    "mins": "דקות",
    "minutes": "דקות",
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
    "negotiations ongoing": "המשא ומתן נמשך",
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
    "full back": "מגן",
    "midfielder": "קשר",
    "defensive midfielder": "קשר אחורי",
    "attacking midfielder": "קשר התקפי",
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
    "Serie A": "סרייה א'",
    "Bundesliga": "בונדסליגה",
    "Ligue 1": "ליגה 1",
}

TEAM_REPLACEMENTS = {
    "Atlanta Hawks": "אטלנטה הוקס",
    "Boston Celtics": "בוסטון סלטיקס",
    "Brooklyn Nets": "ברוקלין נטס",
    "BrooklynNets": "ברוקלין נטס",
    "Charlotte Hornets": "שארלוט הורנטס",
    "Chicago Bulls": "שיקגו בולס",
    "Cleveland Cavaliers": "קליבלנד קאבלירס",
    "Dallas Mavericks": "דאלאס מאבריקס",
    "Denver Nuggets": "דנבר נאגטס",
    "Detroit Pistons": "דטרויט פיסטונס",
    "Golden State Warriors": "גולדן סטייט ווריורס",
    "GoldenStateWarriors": "גולדן סטייט ווריורס",
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
    "Philadelphia 76ers": "פילדלפיה 76'רס",
    "Phoenix Suns": "פיניקס סאנס",
    "Portland Trail Blazers": "פורטלנד טרייל בלייזרס",
    "Sacramento Kings": "סקרמנטו קינגס",
    "San Antonio Spurs": "סן אנטוניו ספרס",
    "Toronto Raptors": "טורונטו ראפטורס",
    "Utah Jazz": "יוטה ג'אז",
    "Washington Wizards": "וושינגטון וויזארדס",
    "Warriors": "ווריורס",
    "Nets": "נטס",
    "Hawks": "הוקס",
    "Celtics": "סלטיקס",
    "Hornets": "הורנטס",
    "Bulls": "בולס",
    "Cavaliers": "קאבלירס",
    "Cavs": "קאבס",
    "Mavericks": "מאבריקס",
    "Mavs": "מאבריקס",
    "Nuggets": "נאגטס",
    "Pistons": "פיסטונס",
    "Rockets": "רוקטס",
    "Pacers": "פייסרס",
    "Clippers": "קליפרס",
    "Lakers": "לייקרס",
    "Grizzlies": "גריזליס",
    "Heat": "היט",
    "Bucks": "באקס",
    "Timberwolves": "טימברוולבס",
    "Lynx": "לינקס",
    "minnesotalynx": "מינסוטה לינקס",
    "Pelicans": "פליקנס",
    "Knicks": "ניקס",
    "Thunder": "ת'אנדר",
    "Magic": "מג'יק",
    "76ers": "76'רס",
    "Sixers": "סיקסרס",
    "Suns": "סאנס",
    "Blazers": "בלייזרס",
    "Trail Blazers": "טרייל בלייזרס",
    "Kings": "קינגס",
    "Spurs": "ספרס",
    "Raptors": "ראפטורס",
    "Jazz": "ג'אז",
    "Wizards": "וויזארדס",
    "הלוחמים": "הווריורס",
    "לוחמים": "ווריורס",
    "הרשתות": "הנטס",
    "רשתות": "נטס",
    "השמשות": "הסאנס",
    "שמשות": "סאנס",
    "קסם": "מג'יק",
    "הקסם": "המג'יק",
    "חלוצים": "בלייזרס",
    "שבילים": "בלייזרס",
    "קוצצים": "קליפרס",
    "הקוצצים": "הקליפרס",
    "אשפים": "וויזארדס",
    "אשף": "וויזארדס",
    "Manchester United": "מנצ'סטר יונייטד",
    "Man United": "מנצ'סטר יונייטד",
    "Man Utd": "מנצ'סטר יונייטד",
    "Manchester City": "מנצ'סטר סיטי",
    "Man City": "מנצ'סטר סיטי",
    "Liverpool": "ליברפול",
    "Chelsea": "צ'לסי",
    "Arsenal": "ארסנל",
    "Tottenham Hotspur": "טוטנהאם",
    "Tottenham": "טוטנהאם",
    "Spurs": "ספרס",
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
    "Bournemouth": "בורנמות'",
    "Brentford": "ברנטפורד",
    "Nottingham Forest": "נוטינגהאם פורסט",
    "Real Madrid": "ריאל מדריד",
    "Barcelona": "ברצלונה",
    "FC Barcelona": "ברצלונה",
    "Barça": "בארסה",
    "Barca": "בארסה",
    "Atletico Madrid": "אתלטיקו מדריד",
    "Atlético Madrid": "אתלטיקו מדריד",
    "Atleti": "אתלטיקו מדריד",
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
    "Paris Saint-Germain": "פריז סן ז'רמן",
    "PSG": "פ.ס.ז'",
    "Marseille": "מארסיי",
    "OM": "מארסיי",
    "Lyon": "ליון",
    "Monaco": "מונאקו",
    "Nice": "ניס",
    "Lille": "ליל",
    "Rennes": "רן",
    "MUFC": "מנצ'סטר יונייטד",
    "MCFC": "מנצ'סטר סיטי",
    "LFC": "ליברפול",
    "CFC": "צ'לסי",
    "AFC": "ארסנל",
    "THFC": "טוטנהאם",
    "FCB": "ברצלונה",
}

PLAYER_REPLACEMENTS = {
    "Marcus Rashford": "מרקוס ראשפורד",
    "Anthony Gordon": "אנתוני גורדון",
    "Florian Wirtz": "פלוריאן וירץ",
    "Viktor Gyokeres": "ויקטור גיוקרש",
    "Victor Osimhen": "ויקטור אוסימן",
    "Kylian Mbappe": "קיליאן אמבפה",
    "Kylian Mbappé": "קיליאן אמבפה",
    "Vinicius Junior": "ויניסיוס ג'וניור",
    "Vinícius Júnior": "ויניסיוס ג'וניור",
    "Erling Haaland": "ארלינג הולאנד",
    "Mohamed Salah": "מוחמד סלאח",
    "Trent Alexander-Arnold": "טרנט אלכסנדר-ארנולד",
    "Alexander Isak": "אלכסנדר איסאק",
    "Bruno Fernandes": "ברונו פרננדש",
    "Lamine Yamal": "לאמין ימאל",
    "Nico Williams": "ניקו וויליאמס",
    "Rodrygo": "רודריגו",
    "Jude Bellingham": "ג'וד בלינגהאם",
    "Harry Kane": "הארי קיין",
    "Lautaro Martinez": "לאוטרו מרטינס",
    "Lautaro Martínez": "לאוטרו מרטינס",
    "Rafael Leao": "רפאל לאאו",
    "Rafael Leão": "רפאל לאאו",
    "Xavi Simons": "צ'אבי סימונס",
    "Bernardo Silva": "ברנרדו סילבה",
    "Julian Alvarez": "חוליאן אלבארס",
    "Julián Álvarez": "חוליאן אלבארס",
    "Jose Mourinho": "ז'וזה מוריניו",
    "José Mourinho": "ז'וזה מוריניו",
    "Gabriel Jesus": "גבריאל ז'סוס",
    "Massimiliano Allegri": "מסימיליאנו אלגרי",
    "Antonio Conte": "אנטוניו קונטה",
    "Mauricio Pochettino": "מאוריסיו פוצ'טינו",
    "Pep Guardiola": "פפ גווארדיולה",
}

HEBREW_FINAL_FIXES = {
    "ניקולה שירה": "ניקולה סקירה",
    "ניקולו שירה": "ניקולה סקירה",
    "ניקולו סקירה": "ניקולה סקירה",
    "ניקולבה סקירה": "ניקולה סקירה",
    "ג'וליאן אלווארז": "חוליאן אלבארס",
    "ג׳וליאן אלווארז": "חוליאן אלבארס",
    "ג'וליאן אלוורז": "חוליאן אלבארס",
    "ג׳וליאן אלוורז": "חוליאן אלבארס",
    "ברנארדו סילבה": "ברנרדו סילבה",
    "ברנרדו סילבא": "ברנרדו סילבה",
    "זוזה מורינייו": "ז'וזה מוריניו",
    "זוזה מוריניו": "ז'וזה מוריניו",
    "ז׳וזה מורינייו": "ז'וזה מוריניו",
    "ז׳וזה מוריניו": "ז'וזה מוריניו",
    "ז'וזה מורינייו": "ז'וזה מוריניו",
    "ז'וזה מאוריניו": "ז'וזה מוריניו",
    "ז׳וזה מאוריניו": "ז'וזה מוריניו",
    "מאוריניו": "מוריניו",
    "חוזה מוריניו": "ז'וזה מוריניו",
    "אוסמן דמבלהה": "אוסמן דמבלה",
    "דהמבלהה": "דמבלה",
    "חרארד רומרו": "ג'ראד רומרו",
    "ז'ראר רומרו": "ג'ראד רומרו",
    "שאמש": "שאמס",
    "שאמש צ'ראניה": "שאמס צ'ראניה",
    "שאמש צ׳ראניה": "שאמס צ׳ראניה",
    "נהא טודיי": "NBA Today",
    "נבא טודיי": "NBA Today",
    "נבה טודיי": "NBA Today",
    "נ.ב.א טודיי": "NBA Today",
    "אנ.בי.איי טודיי": "NBA Today",
    "אן-בי-איי טודיי": "NBA Today",
    "אן בי איי טודיי": "NBA Today",
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
    "סדרה א": "סרייה א'",
    "סרי א": "סרייה א'",
    "טוויט": "פוסט",
    "ציוץ": "פוסט",
    "ציוצים": "פוסטים",
    " and ": " ו",
}

HEBREW_FINAL_FIXES.update(
    {
        "\u05d6\u05d5\u05d6\u05d4 \u05de\u05d5\u05e8\u05d9\u05e0\u05d9\u05d9\u05d5": "\u05d6'\u05d5\u05d6\u05d4 \u05de\u05d5\u05e8\u05d9\u05e0\u05d9\u05d5",
        "\u05d6\u05d5\u05d6\u05d4 \u05de\u05d5\u05e8\u05d9\u05e0\u05d9\u05d5": "\u05d6'\u05d5\u05d6\u05d4 \u05de\u05d5\u05e8\u05d9\u05e0\u05d9\u05d5",
        "\u05d6'\u05d5\u05d6\u05d4 \u05de\u05d0\u05d5\u05e8\u05d9\u05e0\u05d9\u05d5": "\u05d6'\u05d5\u05d6\u05d4 \u05de\u05d5\u05e8\u05d9\u05e0\u05d9\u05d5",
        "\u05d6\u05f3\u05d5\u05d6\u05d4 \u05de\u05d5\u05e8\u05d9\u05e0\u05d9\u05d9\u05d5": "\u05d6'\u05d5\u05d6\u05d4 \u05de\u05d5\u05e8\u05d9\u05e0\u05d9\u05d5",
        "\u05de\u05d0\u05d5\u05e8\u05d9\u05e0\u05d9\u05d5": "\u05de\u05d5\u05e8\u05d9\u05e0\u05d9\u05d5",
        "\u05d1\u05e8\u05e0\u05d0\u05e8\u05d3\u05d5 \u05e1\u05d9\u05dc\u05d1\u05d0": "\u05d1\u05e8\u05e0\u05e8\u05d3\u05d5 \u05e1\u05d9\u05dc\u05d1\u05d4",
        "\u05d1\u05e8\u05e0\u05d0\u05e8\u05d3\u05d5 \u05e1\u05d9\u05dc\u05d1\u05d4": "\u05d1\u05e8\u05e0\u05e8\u05d3\u05d5 \u05e1\u05d9\u05dc\u05d1\u05d4",
        "\u05d1\u05e8\u05e0\u05e8\u05d3\u05d5 \u05e1\u05d9\u05dc\u05d1\u05d0": "\u05d1\u05e8\u05e0\u05e8\u05d3\u05d5 \u05e1\u05d9\u05dc\u05d1\u05d4",
    }
)

STAT_REPLACEMENTS = {
    "goals": "שערים",
    "goal": "שער",
    "assists": "בישולים",
    "assist": "בישול",
    "blocks": "חסימות",
    "block": "חסימה",
    "appearances": "הופעות",
    "appearance": "הופעה",
    "matches": "משחקים",
    "match": "משחק",
    "minutes": "דקות",
    "apps": "הופעות",
}

LATIN_KEEP = {"NBA", "WNBA", "NBA Today", "VAR", "UEFA", "FIFA", "PSG", "UCL", "UEL", "MLS", "RMC", "ESPN", "FC"}

HEBREW_LETTER = {
    "a": "א", "b": "ב", "c": "ק", "d": "ד", "e": "ה", "f": "פ",
    "g": "ג", "h": "ה", "i": "י", "j": "ג'", "k": "ק", "l": "ל",
    "m": "מ", "n": "נ", "o": "ו", "p": "פ", "q": "ק", "r": "ר",
    "s": "ס", "t": "ט", "u": "ו", "v": "ו", "w": "ו", "x": "קס",
    "y": "י", "z": "ז",
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
    published_ts: float


def http_get(url: str, timeout: int = REQUEST_TIMEOUT_SECONDS) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/137.0",
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
                time.sleep(0.5)
    raise RuntimeError(f"GET failed: {url}. Last error: {last_error}")


def http_get_once(url: str, timeout: int = 4) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/137.0",
            "Accept": "application/json, text/plain, */*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def http_get_feed(url: str, timeout: int = FEED_REQUEST_TIMEOUT_SECONDS) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/137.0",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


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
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                error_data = json.loads(raw)
                retry_after = int(error_data.get("parameters", {}).get("retry_after", 0))
            except Exception:
                retry_after = 0
            last_error = RuntimeError(f"HTTP {exc.code}: {raw}")
            if exc.code == 429 and retry_after:
                time.sleep(retry_after + 1)
            elif attempt < HTTP_RETRIES:
                time.sleep(1.5 * attempt)
        except Exception as exc:
            last_error = exc
            if attempt < HTTP_RETRIES:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"POST failed after {HTTP_RETRIES} attempts: {last_error}")


def remote_file_size(url: str, timeout: int = 4) -> int | None:
    if not url or url.lower().split("?", 1)[0].endswith(".m3u8"):
        return None
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/137.0"}
    for method in ("HEAD", "GET"):
        request_headers = dict(headers)
        if method == "GET":
            request_headers["Range"] = "bytes=0-0"
        request = urllib.request.Request(url, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                content_length = response.headers.get("Content-Length")
                content_range = response.headers.get("Content-Range")
                if content_range:
                    match = re.search(r"/(\d+)\s*$", content_range)
                    if match:
                        return int(match.group(1))
                if content_length:
                    return int(content_length)
        except Exception:
            continue
    return None


def sendable_video_url(post: Post) -> str:
    for url in list(dict.fromkeys(post.video_urls)):
        size = remote_file_size(url)
        if size is not None and size <= MAX_VIDEO_BYTES:
            return url
    for url in fetch_external_video_urls(post):
        size = remote_file_size(url)
        if size is not None and size <= MAX_VIDEO_BYTES:
            return url
    return ""


def tweet_parts_from_link(link: str) -> tuple[str, str] | None:
    try:
        parsed = urllib.parse.urlparse(link)
    except Exception:
        return None
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) >= 3 and parts[-2].lower() == "status" and parts[-1].isdigit():
        return parts[-3], parts[-1]
    return None


def collect_video_urls(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, dict):
        for item in value.values():
            urls.extend(collect_video_urls(item))
    elif isinstance(value, list):
        for item in value:
            urls.extend(collect_video_urls(item))
    elif isinstance(value, str):
        clean_url = html.unescape(value)
        if is_video_url(clean_url):
            urls.append(clean_url)
    return urls


def fetch_external_video_urls(post: Post) -> list[str]:
    if not post.has_video or not post.link:
        return []
    tweet_parts = tweet_parts_from_link(post.link)
    if not tweet_parts:
        return []
    username, tweet_id = tweet_parts
    api_urls = [
        f"https://api.fxtwitter.com/{urllib.parse.quote(username)}/status/{tweet_id}",
        f"https://api.vxtwitter.com/{urllib.parse.quote(username)}/status/{tweet_id}",
    ]
    for api_url in api_urls:
        try:
            data = json.loads(http_get_once(api_url, timeout=4).decode("utf-8"))
            urls = collect_video_urls(data)
            if urls:
                return list(dict.fromkeys(urls))
        except Exception:
            continue
    return []


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
            target = quoted if in_quote else kept
            if target and target[-1]:
                target.append("")
            continue
        if kept and re.search(r"\(@[A-Za-z0-9_]{1,20}\)", line):
            quoted_author = re.sub(r"\s*\(@[A-Za-z0-9_]{1,20}\).*", "", line).strip()
            in_quote = True
            continue
        if kept and line.lower() in {"quoted post", "quote", "retweet", "retweeted"}:
            in_quote = True
            continue
        (quoted if in_quote else kept).append(line)

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


def parse_timestamp(item: ET.Element) -> float:
    value = child_text(item, ("pubDate", "published", "updated", "dc:date"))
    if not value:
        return 0.0
    try:
        return parsedate_to_datetime(value).timestamp()
    except Exception:
        return 0.0


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
        images = extract_images(raw_text, item)
        videos = extract_videos(raw_text, item)
        raw_has_video = bool(videos) or has_video_marker(raw_text, item)
        primary_has_video = text_has_video_marker(text)
        quoted_has_video = text_has_video_marker(quoted_text)
        if raw_has_video and not primary_has_video and not quoted_has_video:
            quoted_has_video = bool(quoted_text)
            primary_has_video = not quoted_has_video
        posts.append(
            Post(
                post_id=f"{username}:{guid}",
                username=username,
                text=text,
                link=link,
                image_urls=images,
                video_urls=videos,
                has_video=raw_has_video or primary_has_video or quoted_has_video,
                primary_has_video=primary_has_video,
                quoted_has_video=quoted_has_video,
                quoted_author=quoted_author,
                quoted_text=quoted_text,
                published_ts=parse_timestamp(item),
            )
        )
    return posts


def fetch_feed(username: str, template: str) -> list[Post]:
    url = template.format(username=urllib.parse.quote(username))
    return parse_posts(username, http_get_feed(url))


def fetch_posts(username: str) -> list[Post]:
    all_posts: dict[str, Post] = {}
    executor = ThreadPoolExecutor(max_workers=MAX_PARALLEL_FEED_CHECKS_PER_ACCOUNT)
    futures = [executor.submit(fetch_feed, username, template) for template in FEED_TEMPLATES]
    try:
        for future in as_completed(futures, timeout=FEED_COLLECTION_TIMEOUT_SECONDS):
            try:
                for post in future.result():
                    all_posts.setdefault(post.post_id, post)
            except Exception:
                continue
    except FuturesTimeoutError:
        logging.info("Fetch step: @%s skipped slow feed mirror(s) this cycle", username)
    finally:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
    posts = list(all_posts.values())
    posts.sort(key=lambda post: post.published_ts, reverse=True)
    return posts


def fetch_posts_safely(username: str) -> tuple[str, list[Post]]:
    started = time.perf_counter()
    try:
        posts = fetch_posts(username)
        return username, posts
    except Exception as exc:
        logging.warning("Fetch failed for @%s: %s", username, exc)
        return username, []


def ordered_accounts() -> list[str]:
    priority = [username for username in X_ACCOUNTS if username in PRIORITY_X_ACCOUNTS]
    regular = [username for username in X_ACCOUNTS if username not in PRIORITY_X_ACCOUNTS]
    return priority + regular


def is_night_mode_now() -> bool:
    if not NIGHT_MODE_ENABLED:
        return False
    hour = datetime.now(ZoneInfo(SHABBAT_TIMEZONE)).hour
    if NIGHT_START_HOUR <= NIGHT_END_HOUR:
        return NIGHT_START_HOUR <= hour < NIGHT_END_HOUR
    return hour >= NIGHT_START_HOUR or hour < NIGHT_END_HOUR


def current_check_every_seconds() -> int:
    return NIGHT_CHECK_EVERY_SECONDS if is_night_mode_now() else CHECK_EVERY_SECONDS


def current_max_parallel_account_checks() -> int:
    return NIGHT_MAX_PARALLEL_ACCOUNT_CHECKS if is_night_mode_now() else MAX_PARALLEL_ACCOUNT_CHECKS


def current_max_parallel_post_sends() -> int:
    return NIGHT_MAX_PARALLEL_POST_SENDS if is_night_mode_now() else MAX_PARALLEL_POST_SENDS


def fetch_all_accounts() -> dict[str, list[Post]]:
    results: dict[str, list[Post]] = {username: [] for username in X_ACCOUNTS}
    workers = min(current_max_parallel_account_checks(), max(1, len(X_ACCOUNTS)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(fetch_posts_safely, username): username for username in ordered_accounts()}
        for future in as_completed(future_map):
            username, posts = future.result()
            results[username] = posts
    return results


def shabbat_cache_path() -> Path:
    return Path(__file__).resolve().parent / SHABBAT_CACHE_FILE


def parse_hebcal_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo(SHABBAT_TIMEZONE))
    except Exception:
        return None


def fallback_shabbat_now(now: datetime) -> bool:
    # Conservative offline fallback: Friday afternoon through Saturday night.
    return (now.weekday() == 4 and now.hour >= 16) or (now.weekday() == 5 and now.hour < 21)


def load_shabbat_windows_from_cache(now: datetime) -> list[tuple[datetime, datetime]]:
    path = shabbat_cache_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = parse_hebcal_datetime(str(data.get("fetched_at", "")))
        if not fetched_at or (now - fetched_at).total_seconds() > SHABBAT_HEBCAL_CACHE_SECONDS:
            return []
        windows: list[tuple[datetime, datetime]] = []
        for item in data.get("windows", []):
            start = parse_hebcal_datetime(str(item.get("start", "")))
            end = parse_hebcal_datetime(str(item.get("end", "")))
            if start and end:
                windows.append((start, end))
        return windows
    except Exception:
        return []


def save_shabbat_windows_to_cache(windows: list[tuple[datetime, datetime]], now: datetime) -> None:
    try:
        payload = {
            "fetched_at": now.isoformat(),
            "windows": [{"start": start.isoformat(), "end": end.isoformat()} for start, end in windows],
        }
        path = shabbat_cache_path()
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(path)
    except Exception as exc:
        logging.warning("Shabbat mode: could not save Hebcal cache: %s", exc)


def fetch_shabbat_windows(now: datetime) -> list[tuple[datetime, datetime]]:
    start = (now.date() - timedelta(days=2)).isoformat()
    end = (now.date() + timedelta(days=9)).isoformat()
    url = (
        "https://www.hebcal.com/hebcal?"
        f"cfg=json&v=1&geonameid={urllib.parse.quote(SHABBAT_HEBCAL_GEOID)}"
        f"&maj=on&min=off&mod=off&nx=off&ss=on&mf=on&c=on&m={SHABBAT_HAVDALAH_MINUTES}"
        f"&start={urllib.parse.quote(start)}&end={urllib.parse.quote(end)}"
    )
    data = json.loads(http_get_once(url, timeout=SHABBAT_HEBCAL_TIMEOUT_SECONDS).decode("utf-8"))
    candles: list[datetime] = []
    havdalahs: list[datetime] = []
    for item in data.get("items", []):
        category = item.get("category")
        when = parse_hebcal_datetime(str(item.get("date", "")))
        if not when:
            continue
        if category == "candles":
            candles.append(when)
        elif category == "havdalah":
            havdalahs.append(when)

    windows: list[tuple[datetime, datetime]] = []
    for candle_time in sorted(candles):
        ending = next((havdalah for havdalah in sorted(havdalahs) if havdalah > candle_time), None)
        if ending:
            windows.append((candle_time, ending))
    return windows


def is_shabbat_now() -> bool:
    if not SHABBAT_MODE_ENABLED:
        return False
    now = datetime.now(ZoneInfo(SHABBAT_TIMEZONE))
    windows = load_shabbat_windows_from_cache(now)
    if not windows:
        try:
            windows = fetch_shabbat_windows(now)
            save_shabbat_windows_to_cache(windows, now)
            logging.info("Shabbat mode: Hebcal times refreshed")
        except Exception as exc:
            logging.warning("Shabbat mode: Hebcal unavailable, using fallback times: %s", exc)
            return fallback_shabbat_now(now)
    return any(start <= now <= end for start, end in windows)


def mark_existing_posts_seen(state: dict[str, list[str]]) -> None:
    logging.info("Shabbat mode: marking existing posts as seen without sending")
    all_posts = fetch_all_accounts()
    for username in ordered_accounts():
        seen = set(state.get(username, []))
        for post in all_posts.get(username, []):
            seen.add(post.post_id)
        state[username] = list(seen)[-500:]


def has_linkish_text(text: str) -> bool:
    return bool(URL_RE.search(text or "") or BARE_EXTERNAL_DOMAIN_RE.search(text or ""))


def is_podcast_or_longform_post(post: Post) -> bool:
    raw_text = html.unescape("\n".join([post.text or "", post.quoted_text or ""]))
    lowered = raw_text.lower()
    has_podcast_phrase = any(re.search(pattern, raw_text, re.IGNORECASE) for pattern in PODCAST_BLOCK_PATTERNS)
    has_podcast_domain = any(domain in lowered for domain in PODCAST_DOMAINS)
    has_youtube = "youtube.com" in lowered or "youtu.be" in lowered
    has_longform_youtube_hint = has_youtube and any(
        hint in lowered
        for hint in (
            "podcast",
            "full episode",
            "full show",
            "watch the full",
            "listen",
            "פודקאסט",
            "האזינו",
            "פרק מלא",
            "הפרק המלא",
        )
    )
    return (has_linkish_text(raw_text) and has_podcast_phrase) or has_podcast_domain or has_longform_youtube_hint


def is_link_only_or_details_post(post: Post) -> bool:
    raw_text = html.unescape("\n".join([post.text or "", post.quoted_text or ""]))
    if not has_linkish_text(raw_text) and not post.link:
        return False
    text = remove_external_links(raw_text)
    text = remove_weird_symbols(text)
    text = apply_handle_replacements(text)
    text = remove_credit_handles(text)
    text = convert_hashtags_to_text(text)
    text = re.sub(r"(?<!\w)@([A-Za-z0-9_]+)", "", text)
    text = re.sub(r"(?im)^\s*(?:video|watch video|וידאו|וידיאו)\s*$", "", text)
    text = re.sub(r"[👇⬇️🔽➡️🔗📌:;.,!?\-–—_()\[\]{}\"'׳״\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    generic_phrases = {
        "details",
        "the details",
        "more details",
        "full details",
        "all details",
        "read more",
        "full story",
        "here",
        "link",
        "פרטים",
        "הפרטים",
        "כל הפרטים",
        "לפרטים",
        "פרטים נוספים",
        "הפרטים המלאים",
        "הכתבה",
        "הכתבה המלאה",
        "לכתבה",
        "קישור",
        "בקישור",
        "כאן",
    }
    if not text:
        return True
    if text in generic_phrases:
        return True
    if len(text) <= 28 and any(phrase in text for phrase in generic_phrases):
        return True
    return False


def apply_phrase_replacements(text: str, replacements: dict[str, str]) -> str:
    for source, target in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        if re.fullmatch(r"[A-Za-z0-9 ._'’:-]+", source):
            pattern = r"(?<![A-Za-z0-9_])" + re.escape(source) + r"(?![A-Za-z0-9_])"
            text = re.sub(pattern, target, text, flags=re.IGNORECASE)
        else:
            text = text.replace(source, target)
    return text


def remove_external_links(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<a\s+[^>]*href=[\"'][^\"']+[\"'][^>]*>(.*?)</a>", r"\1", text, flags=re.I | re.S)
    text = URL_RE.sub("", text)
    text = BARE_EXTERNAL_DOMAIN_RE.sub("", text)
    text = re.sub(r"(?m)^\s*(?:🔗|link|לינק|קישור|כתבה|article)\s*:?.*$", "", text, flags=re.I)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" *\n+ *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def remove_credit_handles(text: str) -> str:
    text = text or ""
    text = re.sub(
        r"(?<!\w)@[A-Za-z0-9_]*(?:FC|CF|TV|News|Sport|Sports|Calcio|Official|Media)[A-Za-z0-9_]*\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"(?<!\w)@[A-Za-z0-9_]*[_\d][A-Za-z0-9_]*\b", "", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def apply_handle_replacements(text: str) -> str:
    for source, target in sorted(HANDLE_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = r"(?<![@A-Za-z0-9_])@?" + re.escape(source.lstrip("@")) + r"(?![A-Za-z0-9_])"
        text = re.sub(pattern, target, text, flags=re.IGNORECASE)
    return text


def convert_hashtags_to_text(text: str) -> str:
    return re.sub(r"(?<!\w)#([\w]+)", lambda m: m.group(1).replace("_", " "), text or "", flags=re.UNICODE)


def remove_weird_symbols(text: str) -> str:
    text = html.unescape(text or "")
    text = text.replace("\ufffd", "")
    text = re.sub(r"(?<![A-Za-zÀ-ÿ])(æ|Æ|œ|Œ|ð|Ð|þ|Þ)(?![A-Za-zÀ-ÿ])", "", text)
    text = re.sub(r"\s*\|\s*", " ", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" *\n+ *", "\n", text)
    return text.strip()


def remove_junk_tail_lines(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines()]
    while lines:
        line = lines[-1].strip()
        compact = re.sub(r"\s+", "", line)
        has_hebrew = bool(re.search(r"[א-ת]", line))
        latin = len(re.findall(r"[A-Za-z]", line))
        is_separator = bool(re.fullmatch(r"[-–—_=~`'\"׳״.,:;•…\s]+", line))
        is_handle_like = bool(re.fullmatch(r"@?[A-Za-z0-9_]{3,40}", line)) and ("_" in line or any(ch.isdigit() for ch in line))
        is_source_like = (not has_hebrew and latin >= 3 and len(line) <= 35 and ("_" in line or "@" in line))
        is_sky_tag = bool(re.search(r"(?i)\bsky[_\s-]?[A-Za-z0-9_]*\d+\b", line))
        is_hebrew_sky_tag = bool(re.search(r"סקיי.*\d{2,}", line))
        if not line or is_separator or is_handle_like or is_source_like or is_sky_tag or is_hebrew_sky_tag:
            lines.pop()
            continue
        if compact in {"_", "__", "-", "—", "–", "\"_", "_\"", "״_"}:
            lines.pop()
            continue
        break
    return "\n".join(lines).strip()


def remove_untranslated_tail_tokens(text: str) -> str:
    cleaned_lines: list[str] = []
    for line in (text or "").splitlines():
        line = re.sub(
            r"(?iu)\s*(?:ב-|ב)?(?:NBC|נבק|אן\.?בי\.?סי)\s*(?:&|ו|and)\s*(?:Peacock|פהאקוק|פיקוק)\s*([.!?])?\s*$",
            lambda match: match.group(1) or "",
            line,
        )
        line = re.sub(
            r"(?iu)\s*(?:on|ב-?|דרך)?\s*(?:NBC|נבק|Peacock|פהאקוק|פיקוק)\s*([.!?])?\s*$",
            lambda match: match.group(1) or "",
            line,
        )
        line = re.sub(r"(?i)\s*\[[A-Za-z0-9_. -]{3,40}\]\s*:?\s*\(\s*\)\s*$", "", line)
        line = re.sub(r"(?i)\s*\[[A-Za-z0-9_. -]{3,40}\]\s*$", "", line)
        line = re.sub(r"(?iu)[\wא-ת]*_[A-Za-z0-9_]*\d+[A-Za-z0-9_]*", "", line)
        line = re.sub(r"(?iu)[\wא-ת]*(?:FC|CF|TV|News|Sport|Sports|Calcio|Official|Media)_[A-Za-z0-9_]*", "", line)
        line = re.sub(
            r"(?i)\b[A-Za-z][A-Za-z0-9_]{3,40}\.(?:com|net|org|io|app|tv|news|sport|football)(?:-\d+)?\b",
            "",
            line,
        )
        line = re.sub(r"\s+[A-Za-z][A-Za-z0-9_]{3,40}(?=[\s).,;:!?\"'׳״]*$)", "", line)
        line = re.sub(r"[-–—]\s*([,.!?;:])", r"\1", line)
        line = re.sub(r"\s+([).,;:!?])", r"\1", line)
        line = re.sub(r"^[\s,.;:!?-]+", "", line)
        cleaned_lines.append(line.strip())
    return "\n".join(cleaned_lines).strip()


def clean_before_translation(text: str) -> str:
    text = remove_external_links(text)
    text = remove_weird_symbols(text)
    text = apply_handle_replacements(text)
    text = remove_credit_handles(text)
    text = convert_hashtags_to_text(text)
    text = re.sub(r"(?<!\w)@([A-Za-z0-9_]+)", r"\1", text)
    text = re.sub(r"(?im)^\s*(video|watch video|וידאו|וידיאו)\s*$", "", text)
    text = text.replace("&amp;", "&")
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def cache_path() -> Path:
    return Path(__file__).resolve().parent / TRANSLATION_CACHE_FILE


def load_translation_cache() -> dict[str, str]:
    path = cache_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(key): str(value) for key, value in data.items()}
    except Exception:
        return {}


def save_translation_cache(cache: dict[str, str]) -> None:
    try:
        trimmed = dict(list(cache.items())[-10000:])
        path = cache_path()
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(trimmed, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(path)
    except Exception as exc:
        logging.warning("Could not save translation cache: %s", exc)


TRANSLATION_CACHE = load_translation_cache()


def translation_cache_key(text: str) -> str:
    model = GEMINI_FAST_MODEL if GEMINI_API_KEYS else "free"
    return hashlib.sha256(f"{model}\n{text}".encode("utf-8")).hexdigest()


def google_translate(text: str) -> str:
    query = urllib.parse.urlencode({"client": "gtx", "sl": "auto", "tl": TARGET_LANGUAGE, "dt": "t", "q": text})
    data = json.loads(http_get(f"https://translate.googleapis.com/translate_a/single?{query}", timeout=8).decode("utf-8"))
    return "".join(part[0] for part in data[0] if part and part[0]).strip()


def mymemory_translate(text: str) -> str:
    query = urllib.parse.urlencode({"q": text, "langpair": f"auto|{TARGET_LANGUAGE}"})
    data = json.loads(http_get(f"https://api.mymemory.translated.net/get?{query}", timeout=8).decode("utf-8"))
    return html.unescape(data.get("responseData", {}).get("translatedText", "")).strip()


def gemini_translate(text: str) -> str:
    if not GEMINI_API_KEYS:
        raise RuntimeError("No Gemini API key configured")
    prompt = (
        "Rewrite this NBA / basketball news post as a clean Hebrew Telegram update.\n"
        "Use the full context and meaning. Do not translate word by word.\n"
        "Rules:\n"
        "- Return only the final Hebrew post text.\n"
        "- Keep only the actual news. Remove credits, source tags, TV/network tags, junk suffixes, tracking text and promo text.\n"
        "- Remove all URLs, website domains and link text.\n"
        "- For @handles: if it is a real player, team, reporter or outlet needed for the news, write it naturally in Hebrew; if it is only a source credit or junk tag, omit it.\n"
        "- For hashtags: turn meaningful basketball hashtags into normal Hebrew words; omit promotional/source hashtags.\n"
        "- Keep useful numbers, stats, years, dates, emojis and line breaks.\n"
        "- Do not leave random English words, malformed names, underscores, brackets or weird symbols at the end.\n"
        "- Use common Hebrew basketball terms: טרייד, בחירת דראפט, שחקן חופשי, פלייאוף, ריבאונדים, אסיסטים.\n"
        "- Do not explain anything.\n\n"
        f"POST:\n{text}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "topP": 0.8},
    }
    last_error: Exception | None = None
    for key in GEMINI_API_KEYS:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{urllib.parse.quote(GEMINI_FAST_MODEL)}:generateContent?key={urllib.parse.quote(key)}"
        )
        try:
            data = http_post_json(url, payload, timeout=25)
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            translated = "".join(part.get("text", "") for part in parts).strip()
            if translated:
                return translated
        except Exception as exc:
            last_error = exc
            continue
    raise RuntimeError(f"Gemini translation failed: {last_error}")


def latin_ratio(text: str) -> float:
    hebrew = len(re.findall(r"[א-ת]", text or ""))
    latin = len(re.findall(r"[A-Za-z]", text or ""))
    if hebrew + latin == 0:
        return 0.0
    return latin / (hebrew + latin)


def transliterate_word(word: str) -> str:
    lower = word.lower()
    special = [
        ("ch", "צ'"), ("sh", "ש"), ("th", "ת'"), ("ph", "פ"), ("ck", "ק"),
        ("oo", "ו"), ("ee", "י"), ("ou", "או"), ("ai", "יי"), ("ay", "יי"),
        ("ei", "יי"), ("ie", "י"),
    ]
    out = ""
    i = 0
    while i < len(lower):
        for src, dst in special:
            if lower.startswith(src, i):
                out += dst
                i += len(src)
                break
        else:
            out += HEBREW_LETTER.get(lower[i], lower[i])
            i += 1
    return out.strip("' -")


def transliterate_latin_names(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        phrase = match.group(0).strip()
        if phrase in LATIN_KEEP or len(phrase) <= 2:
            return phrase
        if phrase.lower() in {"http", "https", "www", "com"}:
            return ""
        words = re.split(r"[\s_-]+", phrase)
        return " ".join(transliterate_word(word) for word in words if word)

    return re.sub(r"\b[A-Z][A-Za-zÀ-ÿ'’-]*(?:[\s_-]+[A-Z][A-Za-zÀ-ÿ'’-]*)*\b", repl, text)


def final_hebrew_polish(text: str) -> str:
    text = remove_external_links(text)
    text = remove_weird_symbols(text)
    text = apply_handle_replacements(text)
    text = remove_credit_handles(text)
    text = convert_hashtags_to_text(text)
    for replacements in (TEAM_REPLACEMENTS, PLAYER_REPLACEMENTS, FOOTBALL_TERMS, HEBREW_FINAL_FIXES):
        text = apply_phrase_replacements(text, replacements)
    for english, hebrew in STAT_REPLACEMENTS.items():
        text = re.sub(rf"\b(\d+)\s*{re.escape(english)}\b", rf"\1 {hebrew}", text, flags=re.IGNORECASE)
        text = re.sub(rf"\b{re.escape(english)}\s*(\d+)\b", rf"\1 {hebrew}", text, flags=re.IGNORECASE)
    text = transliterate_latin_names(text)
    text = remove_external_links(text)
    text = re.sub(r"\b(\d+(?:\.\d+)?)\s+רחובות\b", r"\1 חסימות", text)
    text = re.sub(r"\bרחובות\s+(\d+(?:\.\d+)?)\b", r"\1 חסימות", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"([א-ת])\s+-\s+([א-ת])", r"\1-\2", text)
    text = re.sub(r"\b(\d+)\s*-\s*(\d+)\b", r"\1-\2", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" *\n+ *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = remove_untranslated_tail_tokens(text)
    text = remove_junk_tail_lines(text)
    return text.strip()


def translate_in_sentences(text: str) -> str:
    pieces = re.split(r"(?<=[.!?])\s+|\n+", text)
    translated: list[str] = []
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        try:
            translated.append(google_translate(piece))
        except Exception:
            translated.append(piece)
    return "\n\n".join(translated)


def translate_text(text: str) -> str:
    started = time.perf_counter()
    cleaned = clean_before_translation(text)
    if not cleaned:
        return ""
    prepared = apply_phrase_replacements(cleaned, FOOTBALL_TERMS)
    prepared = apply_phrase_replacements(prepared, TEAM_REPLACEMENTS)
    prepared = apply_phrase_replacements(prepared, PLAYER_REPLACEMENTS)
    key = translation_cache_key(prepared)
    if key in TRANSLATION_CACHE:
        return TRANSLATION_CACHE[key]

    providers = []
    if GEMINI_API_KEYS:
        providers.append(gemini_translate)
    providers.extend([google_translate, mymemory_translate])

    for source_text in (prepared, cleaned):
        for provider in providers:
            try:
                translated = provider(source_text)
                if provider is not gemini_translate and latin_ratio(translated) > 0.45:
                    translated = translate_in_sentences(source_text)
                polished = final_hebrew_polish(translated)
                if polished and (provider is gemini_translate or latin_ratio(polished) <= 0.30):
                    TRANSLATION_CACHE[key] = polished
                    return polished
            except Exception as exc:
                logging.warning("Translation failed with %s: %s", provider.__name__, exc)

    fallback = final_hebrew_polish(prepared)
    TRANSLATION_CACHE[key] = fallback
    return fallback


def translate_short_label(text: str) -> str:
    text = clean_before_translation(text)
    if not text:
        return ""
    text = apply_phrase_replacements(text, HANDLE_REPLACEMENTS)
    text = apply_phrase_replacements(text, TEAM_REPLACEMENTS)
    text = apply_phrase_replacements(text, PLAYER_REPLACEMENTS)
    if latin_ratio(text) <= 0.15:
        return final_hebrew_polish(text)
    try:
        translated = gemini_translate(text) if GEMINI_API_KEYS else google_translate(text)
        translated = final_hebrew_polish(translated)
    except Exception:
        translated = final_hebrew_polish(text)
    if latin_ratio(translated) > 0.20:
        return ""
    return translated


def normalize_identity(text: str) -> str:
    text = clean_before_translation(text)
    text = apply_phrase_replacements(text, HANDLE_REPLACEMENTS)
    text = apply_phrase_replacements(text, HEBREW_FINAL_FIXES)
    text = re.sub(r"שאמש", "שאמס", text)
    text = re.sub(r"[^A-Za-z0-9א-ת]+", "", text).lower()
    return text


def identities_for_account(username: str) -> set[str]:
    values = {
        username,
        ACCOUNT_DISPLAY_NAMES.get(username, ""),
        HANDLE_REPLACEMENTS.get(username, ""),
    }
    values.update(SELF_QUOTE_ALIASES.get(username, []))
    return {normalize_identity(value) for value in values if value}


def is_self_quote(post: Post) -> bool:
    if not post.quoted_text or not post.quoted_author:
        return False
    quoted = normalize_identity(post.quoted_author)
    if not quoted:
        return False
    for identity in identities_for_account(post.username):
        if not identity:
            continue
        if quoted == identity or quoted in identity or identity in quoted:
            return True
        if SequenceMatcher(None, quoted, identity).ratio() >= 0.78:
            return True
    return False


def translate_quoted_text(text: str) -> str:
    cleaned = clean_before_translation(text)
    if not cleaned:
        return ""
    translated = translate_text(cleaned)
    if not translated:
        return cleaned
    if latin_ratio(translated) > 0.45:
        return cleaned
    return translated


def translate_quoted_author(text: str) -> str:
    cleaned = clean_before_translation(text)
    if not cleaned:
        return ""
    translated = translate_short_label(cleaned)
    return translated or cleaned


def tidy_translated_text(text: str) -> str:
    text = final_hebrew_polish(html.unescape(text or "").strip())
    text = re.sub(r"(?im)^\s*(וידאו|וידיאו)\s*$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = remove_junk_tail_lines(text)
    return text.strip()


def has_meaningful_text(text: str) -> bool:
    cleaned = tidy_translated_text(text)
    cleaned = re.sub(r"[\s\"'׳״.,:;!?()\[\]{}\-–—_]+", "", cleaned)
    return bool(cleaned and cleaned not in {"עדכוןחדש", "newupdate", "update"})


def rtl(text: str) -> str:
    return "\n".join(f"{RTL_MARK}{line}" if line.strip() else line for line in text.splitlines())


def telegram_api(method: str, payload: dict[str, Any]) -> None:
    logging.info("Telegram step: calling %s", method)
    response = http_post_json(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}", payload)
    if not response.get("ok"):
        raise RuntimeError(f"Telegram error: {response}")
    logging.info("Telegram step: %s succeeded", method)


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


def build_message(
    post: Post,
    translated: str,
    quoted_translated: str = "",
    quoted_author_translated: str = "",
    include_video_link: bool = True,
) -> str:
    translated = tidy_translated_text(translated)
    quoted_translated = tidy_translated_text(quoted_translated)
    display_name = ACCOUNT_DISPLAY_NAMES.get(post.username, post.username)

    safe_account = html.escape(rtl(f"{display_name}:"))
    safe_body = html.escape(rtl(translated or "עדכון חדש"))
    safe_quoted_author = html.escape(rtl(quoted_author_translated))
    safe_quoted_body = html.escape(rtl(f'"{quoted_translated}"')) if quoted_translated else ""
    safe_link = html.escape(post.link)
    video_label = f"<b>{html.escape(rtl('📹 וידיאו מצורף'))}</b>"
    quote_label = f"<b>{html.escape(rtl('פוסט מצוטט:'))}</b>"
    post_link_label = f'<a href="{safe_link}">{html.escape(rtl("קישור לפוסט"))}</a>'

    parts = [f"<b>{safe_account}</b>", "", safe_body]

    if include_video_link and post.link and post.primary_has_video:
        parts.extend(["", "", video_label])

    if safe_quoted_body:
        parts.append("")
        if safe_quoted_author:
            parts.append(quote_label)
            parts.append(safe_quoted_author)
        parts.append(safe_quoted_body)
        if include_video_link and post.link and post.quoted_has_video:
            parts.extend(["", video_label])

    if post.link:
        parts.extend(["", "", post_link_label])

    return "\n".join(parts)


def send_post(post: Post) -> None:
    started = time.perf_counter()
    logging.info("Post step: preparing @%s %s", post.username, post.link)
    translated = translate_text(post.text)
    logging.info("Post step: main text translated")
    if is_self_quote(post):
        logging.info("Post step: self-quote detected, skipping quoted post")
        quoted_translated = ""
        quoted_author_translated = ""
    else:
        quoted_translated = translate_quoted_text(post.quoted_text) if post.quoted_text else ""
        quoted_author_translated = translate_quoted_author(post.quoted_author) if post.quoted_author else ""
        if post.quoted_text:
            logging.info("Post step: quoted post translated")
    if not has_meaningful_text(translated) and not has_meaningful_text(quoted_translated):
        logging.info("Post step: skipped because translated text is empty")
        return
    video_url = sendable_video_url(post) if SEND_VIDEO_FILES else ""
    if video_url:
        logging.info("Post step: sendable video found under %s MB", MAX_VIDEO_BYTES // 1024 // 1024)
    elif post.has_video:
        logging.info("Post step: video exists, but no sendable direct video URL was found")
    message = build_message(
        post,
        translated,
        quoted_translated,
        quoted_author_translated,
        include_video_link=not bool(video_url),
    )
    images = [] if post.has_video else post.image_urls[:MAX_IMAGES_PER_POST]

    if video_url:
        try:
            logging.info("Post step: sending video with caption")
            telegram_api(
                "sendVideo",
                {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "video": video_url,
                    "caption": trim_keep_ending(message, 1024),
                    "parse_mode": "HTML",
                    "supports_streaming": True,
                },
            )
            logging.info("Post step: video with caption sent")
            return
        except Exception as exc:
            logging.warning("Video send failed, falling back to text/link: %s", exc)
            message = build_message(
                post,
                translated,
                quoted_translated,
                quoted_author_translated,
                include_video_link=True,
            )
            images = []

    if images:
        logging.info("Post step: sending %s image(s) with caption", len(images))
        media: list[dict[str, Any]] = []
        for index, image_url in enumerate(images):
            item: dict[str, Any] = {"type": "photo", "media": image_url}
            if index == 0:
                item["caption"] = trim_keep_ending(message, 1024)
                item["parse_mode"] = "HTML"
            media.append(item)
        try:
            telegram_api("sendMediaGroup", {"chat_id": TELEGRAM_CHAT_ID, "media": media})
        except Exception as exc:
            logging.warning("Could not send images, falling back to text only: %s", exc)
        else:
            logging.info("Post step: image message sent")
            return

    logging.info("Post step: sending text message")
    telegram_api(
        "sendMessage",
        {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": trim(message, 4096),
            "disable_web_page_preview": True,
            "parse_mode": "HTML",
        },
    )
    logging.info("Post step: text message sent")


def send_video_after_message(video_url: str) -> None:
    if not (SEND_VIDEO_FILES and video_url):
        return
    try:
        telegram_api(
            "sendVideo",
            {
                "chat_id": TELEGRAM_CHAT_ID,
                "video": video_url,
                "supports_streaming": True,
            },
        )
    except Exception as exc:
        logging.warning("Post text was sent, but Telegram could not attach video: %s", exc)
        try:
            telegram_api(
                "sendMessage",
                {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": f"<b>{html.escape(rtl('וידיאו מצורף:'))}</b>\n{html.escape(video_url)}",
                    "disable_web_page_preview": False,
                    "parse_mode": "HTML",
                },
            )
        except Exception as link_exc:
            logging.warning("Video fallback link also failed: %s", link_exc)


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
    if not TELEGRAM_CHAT_ID:
        raise ValueError("Put your Telegram group chat ID in TELEGRAM_CHAT_ID")
    if not X_ACCOUNTS:
        raise ValueError("Add at least one X/Twitter account to X_ACCOUNTS")


def run_once(state: dict[str, list[str]], startup_cycle: bool = False) -> int:
    cycle_started = time.perf_counter()
    first_run = not any(state.values())
    sent = 0
    fetch_workers = min(current_max_parallel_account_checks(), max(1, len(X_ACCOUNTS)))
    send_executor = ThreadPoolExecutor(max_workers=current_max_parallel_post_sends())
    send_futures = []

    def send_task(item: tuple[str, Post]) -> tuple[str, str, str, bool]:
        username, post = item
        try:
            send_post(post)
            return username, post.post_id, post.link, True
        except Exception as exc:
            logging.error("Failed sending %s: %s", post.link, exc)
            return username, post.post_id, post.link, False

    try:
        with ThreadPoolExecutor(max_workers=fetch_workers) as fetch_executor:
            future_map = {fetch_executor.submit(fetch_posts_safely, username): username for username in ordered_accounts()}
            for future in as_completed(future_map):
                username, posts = future.result()
                seen = set(state.get(username, []))
                if not posts:
                    continue

                new_posts = [post for post in posts if post.post_id not in seen]
                if startup_cycle and SEND_LAST_POST_ON_EVERY_START:
                    new_posts = posts[:1]
                elif first_run and SEND_LAST_POST_ON_FIRST_RUN:
                    new_posts = posts[:1]
                elif first_run:
                    for post in posts:
                        seen.add(post.post_id)
                    state[username] = list(seen)[-500:]
                    continue

                for post in reversed(new_posts[:MAX_NEW_POSTS_PER_ACCOUNT_PER_CHECK]):
                    if is_link_only_or_details_post(post):
                        seen.add(post.post_id)
                        logging.info("Scan step: filtered link-only/details post %s", post.link)
                        continue
                    if is_podcast_or_longform_post(post):
                        seen.add(post.post_id)
                        logging.info("Scan step: filtered podcast/longform post %s", post.link)
                        continue
                    send_futures.append(send_executor.submit(send_task, (username, post)))
                    logging.info("Send step: queued %s", post.link)

                state[username] = list(seen)[-500:]

        for future in as_completed(send_futures):
            username, post_id, link, ok = future.result()
            if not ok:
                continue
            seen = set(state.get(username, []))
            seen.add(post_id)
            state[username] = list(seen)[-500:]
            sent += 1
            logging.info("Sent post from @%s: %s", username, link)
    finally:
        send_executor.shutdown(wait=True, cancel_futures=False)

    if sent:
        logging.info("Cycle sent %s post(s) in %.2fs", sent, time.perf_counter() - cycle_started)
    return sent


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    validate_settings()
    print(f"NBA bot is running. Accounts: {', '.join('@' + account for account in X_ACCOUNTS)}", flush=True)
    print(f"Checking every {CHECK_EVERY_SECONDS} seconds, night mode every {NIGHT_CHECK_EVERY_SECONDS} seconds.", flush=True)
    print("Gemini translation: " + ("ON" if GEMINI_API_KEYS else "OFF - using free fallback"), flush=True)

    if SEND_STARTUP_STATUS_MESSAGE:
        try:
            telegram_api(
                "sendMessage",
                {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": "בוט ה-NBA הופעל. בודק עדכונים...",
                    "disable_web_page_preview": True,
                },
            )
        except Exception as exc:
            logging.error("Startup Telegram test message failed: %s", exc)

    startup_cycle = True
    skipped_for_shabbat = False
    while True:
        cycle_started = time.time()
        try:
            if is_shabbat_now():
                if not skipped_for_shabbat:
                    logging.info("Shabbat mode: active. Bot will not scan, send, or save state.")
                skipped_for_shabbat = True
                time.sleep(SHABBAT_SLEEP_SECONDS)
                continue

            state = load_state()
            if skipped_for_shabbat:
                mark_existing_posts_seen(state)
                save_state(state)
                save_translation_cache(TRANSLATION_CACHE)
                skipped_for_shabbat = False
                startup_cycle = False
                logging.info("Shabbat mode: ended. Existing Shabbat posts were marked as seen without sending.")
                time.sleep(current_check_every_seconds())
                continue

            sent = run_once(state, startup_cycle=startup_cycle)
            startup_cycle = False
            save_state(state)
            save_translation_cache(TRANSLATION_CACHE)
            if sent:
                print(f"Sent {sent} new post(s).", flush=True)
        except Exception as exc:
            logging.error("Unexpected error. Bot will keep running: %s", exc)
        elapsed = time.time() - cycle_started
        time.sleep(max(0, current_check_every_seconds() - elapsed))


if __name__ == "__main__":
    main()

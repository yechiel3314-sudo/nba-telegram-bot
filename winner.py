#!/usr/bin/env python3
"""
Single-file X/Twitter to Telegram football news forwarder.

Run:
  python3 football_x_to_telegram.py

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
from threading import BoundedSemaphore, Lock, Thread
from typing import Any
from zoneinfo import ZoneInfo


# ====== SETTINGS ======

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "8480434397:AAF8ay6JxuYsf7ytVOLG73bVJiJQHq8CMx4",
)
TELEGRAM_CHAT_IDS = [
    "-1002272784260",
]

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
GEMINI_TRANSLATION_ATTEMPTS = 8
GEMINI_RETRY_WAIT_SECONDS = 32
GEMINI_COOLDOWN_SECONDS = 10 * 60
GEMINI_MAX_PARALLEL_TRANSLATIONS = 2

X_ACCOUNTS = [
    "FabrizioRomano",
    "David_Ornstein",
    "DiMarzio",
    "JacobsBen",
    "NicoSchira",
]

PRIORITY_X_ACCOUNTS = {
    "FabrizioRomano",
    "David_Ornstein",
    "DiMarzio",
    "JacobsBen",
    "NicoSchira",
}

ACCOUNT_DISPLAY_NAMES = {
    "FabrizioRomano": "פבריציו רומאנו",
    "David_Ornstein": "דיוויד אורנשטיין",
    "DiMarzio": "ג'אנלוקה די מארציו",
    "JacobsBen": "בן ג'ייקובס",
    "NicoSchira": "ניקולה סקירה",
    "lauriewhitwell": "לורי וויטוול - מנצ'סטר יונייטד",
    "SamLee": "סם לי - מנצ'סטר סיטי",
    "_pauljoyce": "פול ג'ויס - ליברפול",
    "Matt_Law_DT": "מאט לאו - צ'לסי",
    "SimonJones_DM": "סיימון ג'ונס - אנגליה",
    "MatteMoretto": "מתאו מורטו - ספרד",
    "ffpolo": "פרננדו פולו - ברצלונה",
    "gerardromero": "ג'ראד רומרו - ברצלונה",
    "AranchaMOBILE": "ארנצ'ה רודריגז - ריאל מדריד",
    "JLSanchez78": "חוסה לואיס סאנצ'ס - ריאל מדריד",
    "AlfredoPedulla": "אלפרדו פדולה - איטליה",
    "Plettigoal": "פלוריאן פלטנברג - גרמניה",
    "cfbayern": "כריסטיאן פאלק - גרמניה",
    "FabriceHawkins": "פבריס הוקינס - צרפת",
    "Tanziloic": "לואיק טנזי - צרפת",
    "MonfortCarlos": "קרלוס מונפור - ברצלונה",
    "Barca_Buzz": "בארסה באז - ברצלונה",
    "MadridXtra": "מדריד אקסטרה - ריאל מדריד",
    "iMiaSanMia": "מיה סן מיה - באיירן",
    "Santi_J_FM": "סנטי אאונה - פריז סן ז'רמן",
    "AndyMitten": "אנדי מיטן - מנצ'סטר יונייטד",
}

TARGET_LANGUAGE = "he"
CHECK_EVERY_SECONDS = 5
HTTP_RETRIES = 3
REQUEST_TIMEOUT_SECONDS = 10
FEED_REQUEST_TIMEOUT_SECONDS = 2
FEED_COLLECTION_TIMEOUT_SECONDS = 2.5
MAX_PARALLEL_ACCOUNT_CHECKS = 40
MAX_PARALLEL_FEED_CHECKS_PER_ACCOUNT = 8
MAX_NEW_POSTS_PER_ACCOUNT_PER_CHECK = 20
MAX_POST_AGE_SECONDS = 30 * 60
SEND_BACKLOG_FOR_NEW_ACCOUNTS = False
NIGHT_MODE_ENABLED = False
NIGHT_START_HOUR = 0
NIGHT_END_HOUR = 7
NIGHT_CHECK_EVERY_SECONDS = 20
NIGHT_MAX_PARALLEL_ACCOUNT_CHECKS = 16
NIGHT_MAX_PARALLEL_POST_SENDS = 4
SEND_LAST_POST_ON_FIRST_RUN = False
SEND_LAST_POST_ON_EVERY_START = False
SEND_STARTUP_STATUS_MESSAGE = False
CONTROL_CHAT_ID = "-1003924267158"
CONTROL_STATE_FILE = "football_control_state.json"
CONTROL_POLL_SECONDS = 2
CONTROL_RESUME_BACKLOG_SECONDS = 10 * 60
SHABBAT_MODE_ENABLED = True
SHABBAT_TIMEZONE = "Asia/Jerusalem"
SHABBAT_HEBCAL_GEOID = "281184"  # Jerusalem
SHABBAT_HAVDALAH_MINUTES = 50
SHABBAT_HEBCAL_CACHE_SECONDS = 6 * 60 * 60
SHABBAT_HEBCAL_TIMEOUT_SECONDS = 4
SHABBAT_SLEEP_SECONDS = 300
SHABBAT_CACHE_FILE = "football_shabbat_times_cache.json"
MAX_PARALLEL_POST_SENDS = 12
MAX_IMAGES_PER_POST = 4
MAX_VIDEO_BYTES = 50 * 1024 * 1024
SEND_VIDEO_FILES = True
STATE_FILE = "football_x_to_telegram_state.json"
TRANSLATION_CACHE_FILE = "football_translation_cache.json"
RTL_MARK = "\u200f"
SIGNATURE_LINK = "https://t.me/neto_sport"
SIGNATURE_TEXT = "נטו ספורט.📝"

FEED_TEMPLATES = [
    "https://rsshub.app/twitter/user/{username}",
    "https://rsshub.rssforever.com/twitter/user/{username}",
    "https://xcancel.com/{username}/rss",
    "https://twiiit.com/{username}/rss",
    "https://lightbrd.com/{username}/rss",
    "https://twitt.re/{username}/rss",
    "https://nitter.dashy.a3x.dn.nyx.im/{username}/rss",
    "https://nitter.pek.li/{username}/rss",
    "https://nitter.aishiteiru.moe/{username}/rss",
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

EMOJI_RE = re.compile(r"[\U0001F1E6-\U0001F1FF\U0001F300-\U0001FAFF\u2600-\u27BF]")
TAG_FLAG_RE = re.compile(r"\U0001F3F4[\U000E0061-\U000E007A]+\U000E007F")

COUNTRY_CODE_FLAGS = {
    "AR": "\U0001F1E6\U0001F1F7",
    "AT": "\U0001F1E6\U0001F1F9",
    "BE": "\U0001F1E7\U0001F1EA",
    "BR": "\U0001F1E7\U0001F1F7",
    "CH": "\U0001F1E8\U0001F1ED",
    "CL": "\U0001F1E8\U0001F1F1",
    "CM": "\U0001F1E8\U0001F1F2",
    "CO": "\U0001F1E8\U0001F1F4",
    "DE": "\U0001F1E9\U0001F1EA",
    "DK": "\U0001F1E9\U0001F1F0",
    "EC": "\U0001F1EA\U0001F1E8",
    "ES": "\U0001F1EA\U0001F1F8",
    "FR": "\U0001F1EB\U0001F1F7",
    "GB": "\U0001F1EC\U0001F1E7",
    "GE": "\U0001F1EC\U0001F1EA",
    "GH": "\U0001F1EC\U0001F1ED",
    "HR": "\U0001F1ED\U0001F1F7",
    "IL": "\U0001F1EE\U0001F1F1",
    "IT": "\U0001F1EE\U0001F1F9",
    "MA": "\U0001F1F2\U0001F1E6",
    "MX": "\U0001F1F2\U0001F1FD",
    "NG": "\U0001F1F3\U0001F1EC",
    "NL": "\U0001F1F3\U0001F1F1",
    "PT": "\U0001F1F5\U0001F1F9",
    "RS": "\U0001F1F7\U0001F1F8",
    "SN": "\U0001F1F8\U0001F1F3",
    "TR": "\U0001F1F9\U0001F1F7",
    "US": "\U0001F1FA\U0001F1F8",
    "UY": "\U0001F1FA\U0001F1FE",
}


COUNTRY_FLAG_ALIAS_PATTERNS = {
    # Gemini sometimes keeps ISO country codes as Hebrew/phonetic letters instead of emoji.
    # Add more aliases here if you ever see another code survive translation in text form.
    "TR": (
        r"(?<![א-תA-Za-z])טי\s*[-.־]?\s*אר(?![א-תA-Za-z])",
        r"(?<![א-תA-Za-z])טי\s*[-.־]?\s*ר(?![א-תA-Za-z])",
    ),
    "GE": (
        r"(?<![א-תA-Za-z])ג׳?י\s*[-.־]?\s*אי(?![א-תA-Za-z])",
        r"(?<![א-תA-Za-z])גי\s*[-.־]?\s*אי(?![א-תA-Za-z])",
    ),
}


def normalize_country_flags(text: str) -> str:
    """Convert standalone ISO country codes like TR/GE/FR into flag emojis.

    RSS mirrors and Gemini sometimes leave only the two-letter country marker
    instead of the flag. This runs before translation and again after translation,
    including support for hidden RTL marks and spaced codes like T R / T-R / T.R.
    """
    text = text or ""
    invisible = r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]*"
    separator = r"[\s\u00a0._/\-־]*"

    for code, flag in COUNTRY_CODE_FLAGS.items():
        first, second = re.escape(code[0]), re.escape(code[1])
        text = re.sub(
            rf"(?<![A-Za-z]){invisible}{first}{invisible}{separator}{invisible}{second}{invisible}(?![A-Za-z])",
            flag,
            text,
        )
        # Remove duplicate leftovers around the flag, for example: TR 🇹🇷 or 🇹🇷 TR.
        text = re.sub(
            rf"(?<![A-Za-z]){invisible}{first}{invisible}{separator}{invisible}{second}{invisible}\s*{re.escape(flag)}",
            flag,
            text,
        )
        text = re.sub(
            rf"{re.escape(flag)}\s*{invisible}{first}{invisible}{separator}{invisible}{second}{invisible}(?![A-Za-z])",
            flag,
            text,
        )
        text = re.sub(rf"{re.escape(flag)}(?:\s*{re.escape(flag)})+", flag, text)

    for code, patterns in COUNTRY_FLAG_ALIAS_PATTERNS.items():
        flag = COUNTRY_CODE_FLAGS.get(code)
        if not flag:
            continue
        for pattern in patterns:
            text = re.sub(pattern, flag, text, flags=re.IGNORECASE)
        text = re.sub(rf"{re.escape(flag)}(?:\s*{re.escape(flag)})+", flag, text)

    return text


def country_flags_in_text(text: str) -> list[str]:
    normalized = normalize_country_flags(text or "")
    flags: list[str] = []
    for flag in COUNTRY_CODE_FLAGS.values():
        if flag in normalized and flag not in flags:
            flags.append(flag)
    return flags


def preserve_original_country_flags(original: str, translated: str) -> str:
    translated = normalize_country_flags(translated or "")
    missing = [flag for flag in country_flags_in_text(original) if flag not in translated]
    if missing:
        translated = f"{' '.join(missing)} {translated}".strip()
    return normalize_country_flags(translated)


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
    "RMCsport": "RMC ספורט",
    "lequipe": "לאקיפ",
    "ActuFoot_": "אקטו פוט",
    "Barca_Buzz": "בארסה באז",
    "iMiaSanMia": "מיה סן מיה",
    "Santi_J_FM": "סנטי אאונה",
    "AndyMitten": "אנדי מיטן",
}

HANDLE_REPLACEMENTS.update(
    {
        "MadridXtra": "מדריד אקסטרה",
    }
)

SELF_QUOTE_ALIASES = {
    "FabrizioRomano": ["Fabrizio Romano", "פבריציו רומאנו"],
    "David_Ornstein": ["David Ornstein", "דיוויד אורנשטיין"],
    "DiMarzio": ["Gianluca Di Marzio", "Gianluca DiMarzio", "ג'אנלוקה די מארציו", "גיאנלוקה די מארציו"],
    "JacobsBen": ["Ben Jacobs", "בן ג'ייקובס", "בן גייקובס", "בן יעקבס"],
    "NicoSchira": ["Nicolò Schira", "Nicolo Schira", "Nico Schira", "ניקולה סקירה", "ניקולו סקירה", "ניקולה שירה", "ניקולו שירה", "ניקולה סקירה - כללי"],
    "lauriewhitwell": ["Laurie Whitwell", "לורי וויטוול"],
    "SamLee": ["Sam Lee", "סם לי"],
    "_pauljoyce": ["Paul Joyce", "פול ג'ויס"],
    "Matt_Law_DT": ["Matt Law", "מאט לאו"],
    "SimonJones_DM": ["Simon Jones", "סיימון ג'ונס"],
    "MatteMoretto": ["Matteo Moretto", "Matte Moretto", "מתאו מורטו", "מתאו מורטו - ספרד"],
    "ffpolo": ["Fernando Polo", "פרננדו פולו"],
    "gerardromero": ["Gerard Romero", "ג'ראד רומרו", "חרארד רומרו", "ז'ראר רומרו"],
    "AranchaMOBILE": ["Arancha Rodríguez", "Arancha Rodriguez", "ארנצ'ה רודריגז"],
    "JLSanchez78": ["José Luis Sánchez", "Jose Luis Sanchez", "חוסה לואיס סאנצ'ס"],
    "AlfredoPedulla": ["Alfredo Pedullà", "Alfredo Pedulla", "אלפרדו פדולה", "אלפרהדו פדולה"],
    "Plettigoal": ["Florian Plettenberg", "Florian Pletti", "פלוריאן פלטנברג", "פלוריאן פחלטנברג"],
    "cfbayern": ["Christian Falk", "כריסטיאן פאלק"],
    "FabriceHawkins": ["Fabrice Hawkins", "פבריס הוקינס"],
    "Tanziloic": ["Loïc Tanzi", "Loic Tanzi", "לואיק טנזי"],
    "MonfortCarlos": ["Carlos Monfort", "קרלוס מונפור"],
    "Barca_Buzz": ["Barca Buzz", "Barça Buzz", "בארסה באז"],
    "iMiaSanMia": ["Mia San Mia", "מיה סן מיה"],
    "Santi_J_FM": ["Santi Aouna", "סנטי אאונה"],
    "AndyMitten": ["Andy Mitten", "אנדי מיטן"],
}

SELF_QUOTE_ALIASES.update(
    {
        "MadridXtra": ["Madrid Xtra", "MadridXtra", "מדריד אקסטרה"],
    }
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

ENTITY_CONFLICT_GROUPS = [
    {
        "Real Madrid": "ריאל מדריד",
        "Real Sociedad": "ריאל סוסיאדד",
        "Real Betis": "בטיס",
    },
    {
        "Manchester United": "מנצ'סטר יונייטד",
        "Man United": "מנצ'סטר יונייטד",
        "Man Utd": "מנצ'סטר יונייטד",
        "Manchester City": "מנצ'סטר סיטי",
        "Man City": "מנצ'סטר סיטי",
    },
    {
        "AC Milan": "מילאן",
        "Milan": "מילאן",
        "Inter Milan": "אינטר",
        "Inter": "אינטר",
    },
    {
        "Bayern Munich": "באיירן מינכן",
        "Bayern": "באיירן",
        "Bayer Leverkusen": "באייר לברקוזן",
        "Leverkusen": "לברקוזן",
    },
]

PLAYER_REPLACEMENTS = {
    "Xabi Alonso": "צ'אבי אלונסו",
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
    "Ousmane Dembele": "אוסמן דמבלה",
    "Ousmane Dembélé": "אוסמן דמבלה",
    "Jose Mourinho": "ז'וזה מוריניו",
    "José Mourinho": "ז'וזה מוריניו",
    "Gabriel Jesus": "גבריאל ז'סוס",
    "Massimiliano Allegri": "מסימיליאנו אלגרי",
    "Antonio Conte": "אנטוניו קונטה",
    "Mauricio Pochettino": "מאוריסיו פוצ'טינו",
    "Pep Guardiola": "פפ גווארדיולה",
    "Khvicha Kvaratskhelia": "חביצ'ה קווארצחליה",
    "Kvaratskhelia": "קווארצחליה",
}

HEBREW_FINAL_FIXES = {
    "צ'לסי בוחנת את האפשרות למנות את צ'אבי אלונסו למאמנה הבא של ריאל סוסיאדד": "צ'לסי בוחנת את האפשרות למנות את צ'אבי אלונסו למאמנה הבא",
    "למאמנה הבא של ריאל סוסיאדד": "למאמנה הבא",
    "צאבי אלונסו": "צ'אבי אלונסו",
    "צ׳אבי אלונסו": "צ'אבי אלונסו",
    "קסאבי אלונסו": "צ'אבי אלונסו",
    "לקיפה": "לאקיפ",
    "ל'אקיפה": "לאקיפ",
    "ל'אקיפ": "לאקיפ",
    "ניקולה שירה": "ניקולה סקירה",
    "ניקולו שירה": "ניקולה סקירה",
    "ניקולו סקירה": "ניקולה סקירה",
    "ניקולבה סקירה": "ניקולה סקירה",
    "ג'וליאן אלווארז": "חוליאן אלבארס",
    "ג׳וליאן אלווארז": "חוליאן אלבארס",
    "ג'וליאן אלוורז": "חוליאן אלבארס",
    "ג׳וליאן אלוורז": "חוליאן אלבארס",
    "אוסמאנה דהמבéלé": "אוסמן דמבלה",
    "אוסמאנה דהמבלה": "אוסמן דמבלה",
    "אוסמן דמבל": "אוסמן דמבלה",
    "אוסמן דמבלהה": "אוסמן דמבלה",
    "דהמבéלé": "דמבלה",
    "דהמבלה": "דמבלה",
    "דהמבלהה": "דמבלה",
    "זוזה מורינייו": "ז'וזה מוריניו",
    "זוזה מוריניו": "ז'וזה מוריניו",
    "ז׳וזה מורינייו": "ז'וזה מוריניו",
    "ז׳וזה מוריניו": "ז'וזה מוריניו",
    "ז'וזה מורינייו": "ז'וזה מוריניו",
    "ז'וזה מאוריניו": "ז'וזה מוריניו",
    "ז׳וזה מאוריניו": "ז'וזה מוריניו",
    "מאוריניו": "מוריניו",
    "חוזה מוריניו": "ז'וזה מוריניו",
    "ברנארדו סילבה": "ברנרדו סילבה",
    "ברנרדו סילבא": "ברנרדו סילבה",
    "חרארד רומרו": "ג'ראד רומרו",
    "ז'ראר רומרו": "ג'ראד רומרו",
    "GE": "🇬🇪",
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

HEBREW_FINAL_FIXES.update(
    {
        "\u05d7\u05d1\u05e6'\u05d4": "\u05d7\u05d1\u05d9\u05e6'\u05d4 \u05e7\u05d5\u05d5\u05d0\u05e8\u05e6\u05d7\u05dc\u05d9\u05d4",
        "\u05d7\u05d1\u05d9\u05e6\u05d9\u05d4": "\u05d7\u05d1\u05d9\u05e6'\u05d4 \u05e7\u05d5\u05d5\u05d0\u05e8\u05e6\u05d7\u05dc\u05d9\u05d4",
        "\u05d7\u05d1\u05d9\u05e6\u05f3\u05d4": "\u05d7\u05d1\u05d9\u05e6'\u05d4 \u05e7\u05d5\u05d5\u05d0\u05e8\u05e6\u05d7\u05dc\u05d9\u05d4",
        "\u05e7\u05d5\u05d5\u05d0\u05e8\u05e6\u05f3\u05d7\u05dc\u05d9\u05d4": "\u05e7\u05d5\u05d5\u05d0\u05e8\u05e6\u05d7\u05dc\u05d9\u05d4",
        "GE": "\U0001F1EC\U0001F1EA",
    }
)

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

LATIN_KEEP = {"VAR", "UEFA", "FIFA", "PSG", "UCL", "UEL", "MLS", "RMC", "ESPN", "FC"}

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
    dedupe_ids: list[str]
    source_name: str


class TranslationUnavailable(Exception):
    pass


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


def http_post_json(
    url: str,
    payload: dict[str, Any],
    timeout: int = 30,
    max_attempts: int = HTTP_RETRIES,
    respect_retry_after: bool = True,
) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
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
            if exc.code == 429 and retry_after and respect_retry_after:
                time.sleep(retry_after + 1)
            elif attempt < max_attempts:
                time.sleep(1.5 * attempt)
        except Exception as exc:
            last_error = exc
            if attempt < max_attempts:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"POST failed after {max_attempts} attempts: {last_error}")


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


def canonical_post_id(username: str, guid: str, link: str, title: str) -> str:
    for value in (link, guid, title):
        match = re.search(r"/(?:status|statuses)/(\d+)", value or "", flags=re.IGNORECASE)
        if match:
            return f"{username}:status:{match.group(1)}"
    return f"{username}:{guid or link or title}"


def post_content_signature(username: str, text: str, quoted_text: str) -> str:
    value = html.unescape("\n".join([text or "", quoted_text or ""]))
    value = URL_RE.sub("", value)
    value = BARE_EXTERNAL_DOMAIN_RE.sub("", value)
    value = re.sub(r"(?<!\w)@([A-Za-z0-9_]+)", "", value)
    value = re.sub(r"(?<!\w)#([\w]+)", r"\1", value, flags=re.UNICODE)
    value = re.sub(r"[^A-Za-z0-9א-ת]+", "", value).lower()
    if len(value) < 18:
        return ""
    return f"{username}:text:{hashlib.sha1(value.encode('utf-8')).hexdigest()}"


def is_too_old_post(post: Post) -> bool:
    return bool(post.published_ts and time.time() - post.published_ts > MAX_POST_AGE_SECONDS)


def parse_timestamp(item: ET.Element) -> float:
    value = child_text(item, ("pubDate", "published", "updated", "dc:date"))
    if not value:
        return 0.0
    try:
        return parsedate_to_datetime(value).timestamp()
    except Exception:
        return 0.0


def feed_source_name(template: str) -> str:
    try:
        host = urllib.parse.urlparse(template).netloc.lower()
    except Exception:
        return "unknown"
    return host.removeprefix("www.")


def parse_posts(username: str, xml_bytes: bytes, source_name: str) -> list[Post]:
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
        post_id = canonical_post_id(username, guid, link, title)
        dedupe_ids = list(
            dict.fromkeys(
                item
                for item in [
                    post_id,
                    f"{username}:{guid}",
                    f"{username}:{link}",
                    post_content_signature(username, text, quoted_text),
                ]
                if item
            )
        )
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
                post_id=post_id,
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
                dedupe_ids=dedupe_ids,
                source_name=source_name,
            )
        )
    return posts


def fetch_feed(username: str, template: str) -> list[Post]:
    url = template.format(username=urllib.parse.quote(username))
    return parse_posts(username, http_get_feed(url), feed_source_name(template))


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
        pass
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


def control_state_path() -> Path:
    return Path(__file__).resolve().parent / CONTROL_STATE_FILE


def load_control_state() -> dict[str, Any]:
    path = control_state_path()
    if not path.exists():
        return {"paused": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"paused": False}
        data["paused"] = bool(data.get("paused", False))
        return data
    except Exception:
        return {"paused": False}


def save_control_state(paused: bool | None = None, **updates: Any) -> None:
    state = load_control_state()
    if paused is not None:
        state["paused"] = paused
    state.update(updates)
    path = control_state_path()
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)


def is_control_paused() -> bool:
    return bool(load_control_state().get("paused", False))


def control_reply_markup(paused: bool) -> dict[str, Any]:
    if paused:
        return {"inline_keyboard": [[{"text": "להפעיל את הבוט", "callback_data": "football_bot_on"}]]}
    return {"inline_keyboard": [[{"text": "לכבות את הבוט", "callback_data": "football_bot_off"}]]}


def send_control_panel(paused: bool, action_done: str = "") -> None:
    if not CONTROL_CHAT_ID:
        return
    status = "כבוי" if paused else "פעיל"
    text = action_done or f"לוח שליטה בבוט הכדורגל. מצב נוכחי: {status}."
    state = load_control_state()
    message_id = state.get("control_message_id")
    payload = {
        "chat_id": CONTROL_CHAT_ID,
        "text": text,
        "reply_markup": control_reply_markup(paused),
    }
    if message_id:
        try:
            telegram_api("editMessageText", {**payload, "message_id": int(message_id)})
            return
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                return
            logging.warning("Control panel edit failed, sending one new panel: %s", exc)
    response = telegram_api("sendMessage", payload)
    new_message_id = response.get("result", {}).get("message_id")
    if new_message_id:
        save_control_state(paused, control_message_id=new_message_id)


def answer_control_callback(callback_id: str, text: str = "") -> None:
    telegram_api("answerCallbackQuery", {"callback_query_id": callback_id, "text": text, "show_alert": False})


def process_control_update(update: dict[str, Any]) -> None:
    callback = update.get("callback_query")
    if not callback:
        return
    callback_id = str(callback.get("id", ""))
    message = callback.get("message", {}) or {}
    chat = message.get("chat", {}) or {}
    chat_id = str(chat.get("id", ""))
    data = str(callback.get("data", ""))
    if CONTROL_CHAT_ID and chat_id != CONTROL_CHAT_ID:
        if callback_id:
            answer_control_callback(callback_id, "אין הרשאה לערוץ הזה")
        return
    if data == "football_bot_off":
        save_control_state(True)
        if callback_id:
            answer_control_callback(callback_id, "הבוט כובה")
        send_control_panel(True, "הפעולה בוצעה בהצלחה: הבוט כובה.")
    elif data == "football_bot_on":
        save_control_state(False, resume_min_ts=time.time() - CONTROL_RESUME_BACKLOG_SECONDS)
        if callback_id:
            answer_control_callback(callback_id, "הבוט הופעל")
        send_control_panel(False, "\u05d4\u05e4\u05e2\u05d5\u05dc\u05d4 \u05d1\u05d5\u05e6\u05e2\u05d4 \u05d1\u05d4\u05e6\u05dc\u05d7\u05d4: \u05d4\u05d1\u05d5\u05d8 \u05d4\u05d5\u05e4\u05e2\u05dc.")


def is_getupdates_conflict(error: Exception) -> bool:
    error_text = str(error).lower()
    return "409" in error_text and "getupdates" in error_text


def control_loop() -> None:
    if not CONTROL_CHAT_ID:
        return
    offset = 0
    try:
        send_control_panel(is_control_paused())
    except Exception as exc:
        logging.warning("Control panel startup failed: %s", exc)
    while True:
        try:
            response = telegram_api(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 20,
                    "allowed_updates": ["callback_query"],
                },
            )
            for update in response.get("result", []):
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                process_control_update(update)
        except Exception as exc:
            if is_getupdates_conflict(exc):
                logging.warning(
                    "כפתורי השליטה כבויים בעותק הזה: טלגרם מזהה עוד עותק של הבוט שמאזין לכפתורים. הסריקה והשליחה לערוצים ממשיכות כרגיל."
                )
                return
            logging.warning("Control panel polling failed: %s", exc)
            time.sleep(CONTROL_POLL_SECONDS)


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
            logging.info("מצב שבת: זמני שבת עודכנו")
        except Exception as exc:
            logging.warning("Shabbat mode: Hebcal unavailable, using fallback times: %s", exc)
            return fallback_shabbat_now(now)
    return any(start <= now <= end for start, end in windows)


def mark_existing_posts_seen(state: dict[str, list[str]]) -> None:
    logging.info("מצב שבת: מסמן פוסטים קיימים כנצפו בלי לשלוח")
    all_posts = fetch_all_accounts()
    for username in ordered_accounts():
        seen = set(state.get(username, []))
        for post in all_posts.get(username, []):
            seen.update(post.dedupe_ids)
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


def is_interesting_quote_post(cleaned: str) -> bool:
    senior_voice = re.search(
        r"\b(president|chairman|owner|ceo|director|sporting director|manager|coach|agent)\b|"
        r"נשיא|יו\"ר|בעלים|מנכ\"ל|מנהל מקצועי|מאמן|סוכן",
        cleaned,
        re.IGNORECASE,
    )
    important_subject = re.search(
        r"\b(Vinicius|Mbappe|Bellingham|Yamal|Salah|Haaland|Real Madrid|Barcelona|Man United|Manchester United|"
        r"contract|renewal|future|stay|leave|transfer|sign|club|fans)\b|"
        r"ויניסיוס|אמבפה|בלינגהאם|ימאל|סלאח|הולאנד|ריאל מדריד|ברצלונה|מנצ'סטר יונייטד|"
        r"חוזה|חידוש|עתיד|יישאר|יעזוב|העברה|חתימה|מועדון|אוהדים|שחקן",
        cleaned,
        re.IGNORECASE,
    )
    quoted = re.search(r"[\"“”׳״].{4,}[\"“”׳״]", cleaned)
    return bool(quoted and senior_voice and important_subject)


def is_stats_only_post(cleaned: str) -> bool:
    has_stats = re.search(
        r"\b(stats|statistics|goals|assists|appearances|apps|minutes|rebounds|blocks|steals|points|per game)\b|"
        r"סטטיסטיקה|שערים|בישולים|הופעות|דקות|נקודות|ריבאונדים|חסימות|חטיפות",
        cleaned,
        re.IGNORECASE,
    )
    has_news_context = re.search(
        r"\bbreaking|exclusive|official|contract|renewal|transfer|deal|sign|bid|injury|record\b|"
        r"רשמי|בלעדי|חוזה|חידוש|העברה|עסקה|חתם|הצעה|פציעה|שיא",
        cleaned,
        re.IGNORECASE,
    )
    return bool(has_stats and not has_news_context)


def filtered_post_text_preview(post: Post, limit: int = 260) -> str:
    raw_text = html.unescape("\n".join([post.text or "", post.quoted_text or ""]))
    cleaned = clean_for_ai_translation(raw_text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return trim(cleaned, limit) if cleaned else "(טקסט ריק)"


def is_non_news_social_post(post: Post) -> bool:
    raw_text = html.unescape("\n".join([post.text or "", post.quoted_text or ""]))
    cleaned = clean_for_ai_translation(raw_text)
    lowered = cleaned.lower()
    if not cleaned:
        return True

    news_patterns = (
        r"\bbreaking\b",
        r"\bexclusive\b",
        r"\bdeal\b",
        r"\bagreement\b",
        r"\bsigns?\b",
        r"\bjoins?\b",
        r"\bmedical\b",
        r"\bcontract\b",
        r"\bbid\b",
        r"\bclause\b",
        r"\bloan\b",
        r"\btransfer\b",
        r"\bappointed\b",
        r"\bsacked\b",
        r"\binjury\b",
        r"\bsuspended\b",
        r"\bconfirmed\b",
        r"\bofficial\b",
        r"\bcalled\s+up\b",
        r"\bsquad\b",
        r"\bnational\s+team\b",
        r"הושג|סוכם|חתם|יחתום|מצטרף|יעבור|העברה|השאלה|חוזה|רשמי|בלעדי|פציעה|מונה|פוטר",
    )
    if any(re.search(pattern, cleaned, re.IGNORECASE) for pattern in news_patterns):
        return False
    if is_interesting_quote_post(cleaned):
        return False
    if is_stats_only_post(cleaned):
        return True
    if re.search(r"[\"“”׳״].{4,}[\"“”׳״]", cleaned):
        return True

    social_patterns = (
        r"\binstagram\b",
        r"\bstory\b",
        r"\breaction\b",
        r"\bquote\b",
        r"\bcaption\b",
        r"\bmessage\b",
        r"\binterview\b",
        r"\btold\b",
        r"\bsays?\b",
        r"\basked\b",
        r"\bspeaking\b",
        r"\bon\s+[A-Z][A-Za-zÀ-ÿ'’-]+(?:\s+[A-Z][A-Za-zÀ-ÿ'’-]+){0,3}\s*:",
        r"\bcongrat",
        r"\brespect\b",
        r"\bclass\b",
        r"\blegend\b",
        r"\bunderstand me\b",
        r"\byou cannot understand\b",
        r"vous ne pouvez pas comprendre",
        r"אי אפשר להבין|לא יכול להבין|סטורי|אינסטגרם|ברכה|מחווה|תגובה|ציטוט|מסר|אגדה|כבוד|בראיון|אמר|אומר|נשאל|דיבר על|מדבר על",
    )
    if any(re.search(pattern, cleaned, re.IGNORECASE) for pattern in social_patterns):
        return True

    words = re.findall(r"[A-Za-zא-ת0-9]+", cleaned)
    if post.image_urls and len(words) <= 14 and not post.video_urls:
        return True

    return False



# ====== SMART FILTERS: FLAGS, WOMEN/WNBA, DUPLICATE NEWS ======
RECENT_NEWS_STATE_KEY = "__recent_news_events__"
RECENT_NEWS_WINDOW_SECONDS = 2 * 60 * 60

SOURCE_PRIORITY = {
    "FabrizioRomano": 100,
    "ShamsCharania": 100,
    "David_Ornstein": 95,
    "DiMarzio": 90,
    "JacobsBen": 80,
    "NicoSchira": 75,
    "TheDunkCentral": 70,
    "NBACentral": 70,
    "LegionHoops": 65,
    "UnderdogNBA": 60,
}

WOMEN_SPORT_BLOCK_PATTERNS = (
    r"\bwomen(?:'s)?\b",
    r"\bwomens\b",
    r"\bfemale\b",
    r"\bgirls?\b",
    r"\bWSL\b",
    r"\bUWCL\b",
    r"\bNWSL\b",
    r"\bLiga\s+F\b",
    r"\bBarclays\s+Women",
    r"\bLionesses\b",
    r"\bUSWNT\b",
    r"\bMatildas\b",
    r"\bFrauen\b",
    r"\bFemen[íi]\b",
    r"\bF[ée]minine\b",
    r"\bD1\s+Arkema\b",
    r"\bWNBA\b",
    r"\bCaitlin\s+Clark\b",
    r"\bAngel\s+Reese\b",
    r"\bA'ja\s+Wilson\b",
    r"\bBreanna\s+Stewart\b",
    r"\bSabrina\s+Ionescu\b",
    r"כדורגל\s+נשים",
    r"נשים",
    r"שחקנית",
    r"שחקניות",
    r"מאמנת",
    r"ליגת\s+הנשים",
    r"נבחרת\s+הנשים",
    r"WNBA",
)

NEWS_DUP_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "from", "as", "by", "at", "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "he", "she", "they", "we", "you", "his", "her", "their", "our", "your",
    "according", "sources", "source", "reported", "report", "reports", "exclusive", "breaking", "official", "confirmed", "understand", "now", "today",
    "לפי", "מקורות", "דיווח", "דיווחים", "רשמי", "בלעדי", "היום", "כעת", "לאחר", "כפי", "כך", "כי", "של", "את", "עם", "על", "אל", "הוא", "היא", "הם", "הן", "זה", "זו", "הזה", "הזו",
}

NEWS_DUP_ACTION_WORDS = {
    "leave", "leaves", "leaving", "left", "exit", "exits", "depart", "departs", "free", "agent", "contract", "extend", "extension", "sign", "signs", "signed", "join", "joins", "joined",
    "transfer", "trade", "traded", "waive", "waived", "injury", "injured", "out", "sacked", "appointed", "agreed", "agreement", "deal", "announce", "announced", "confirmed",
    "עוזב", "יעזוב", "עזב", "שוחרר", "חופשי", "חוזה", "חתם", "יחתום", "מצטרף", "עבר", "יעבור", "העברה", "טרייד", "פציעה", "נפצע", "לא", "ישחק", "מונה", "פוטר", "סוכם", "אישרה", "אישר", "הודיעה", "פורסם",
}


def strip_country_code_leftovers_near_flags(text: str) -> str:
    """Keep the flag emoji and remove its duplicated ISO letters around it."""
    text = text or ""
    invisible = r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]*"
    separator = r"[\s\u00a0._/\-־]*"
    if "COUNTRY_CODE_FLAGS" not in globals():
        return text
    for code, flag in COUNTRY_CODE_FLAGS.items():
        first, second = re.escape(code[0]), re.escape(code[1])
        code_pattern = rf"{invisible}{first}{invisible}{separator}{invisible}{second}{invisible}"
        text = re.sub(rf"(?<![A-Za-z]){code_pattern}\s*{re.escape(flag)}", flag, text)
        text = re.sub(rf"{re.escape(flag)}\s*{code_pattern}(?![A-Za-z])", flag, text)
        text = re.sub(rf"{re.escape(flag)}(?:\s*{re.escape(flag)})+", flag, text)
    return text


def is_women_or_wnba_post(post: Post) -> bool:
    raw_text = html.unescape("\n".join([post.text or "", post.quoted_text or ""]))
    cleaned = remove_external_links(raw_text)
    return any(re.search(pattern, cleaned, re.IGNORECASE) for pattern in WOMEN_SPORT_BLOCK_PATTERNS)


def _news_duplicate_clean_text(post: Post) -> str:
    text = html.unescape("\n".join([post.text or "", post.quoted_text or ""]))
    text = normalize_country_flags(text) if "normalize_country_flags" in globals() else text
    text = remove_external_links(text)
    text = convert_hashtags_to_text(text)
    text = apply_handle_replacements(text)
    text = apply_phrase_replacements(text, TEAM_REPLACEMENTS)
    text = apply_phrase_replacements(text, PLAYER_REPLACEMENTS)
    text = re.sub(r"(?<!\w)@[A-Za-z0-9_]+", " ", text)
    text = re.sub(r"[🚨✅🔴⚪🟢🔵🟡⚫⭐️📌📍🗣🔥💣🏆🥇📈✍️]", " ", text)
    text = re.sub(r"[^A-Za-z0-9א-ת'׳\- ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def _news_duplicate_tokens(text: str) -> set[str]:
    raw_tokens = re.findall(r"[A-Za-zא-ת][A-Za-zא-ת'׳\-]{2,}|\d+", text or "")
    tokens: set[str] = set()
    for token in raw_tokens:
        token = token.strip("-'׳").lower()
        if len(token) < 3 or token in NEWS_DUP_STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def news_event_signature(post: Post) -> dict[str, Any]:
    text = _news_duplicate_clean_text(post)
    tokens = _news_duplicate_tokens(text)
    action_tokens = tokens & NEWS_DUP_ACTION_WORDS
    entity_tokens: set[str] = set()
    for source, target in {**TEAM_REPLACEMENTS, **PLAYER_REPLACEMENTS, **HANDLE_REPLACEMENTS}.items():
        for value in (source, target):
            if value and re.search(r"(?<!\w)" + re.escape(value.lower()) + r"(?!\w)", text):
                entity_tokens.update(_news_duplicate_tokens(value.lower()))
    # Add repeated proper-name style tokens from the normalized text as a fallback.
    for token in tokens:
        if len(token) >= 5 and token not in NEWS_DUP_ACTION_WORDS:
            entity_tokens.add(token)
    return {
        "text": text,
        "tokens": sorted(tokens),
        "entities": sorted(entity_tokens),
        "actions": sorted(action_tokens),
    }


def _event_similarity(current: dict[str, Any], previous: dict[str, Any]) -> float:
    current_tokens = set(current.get("tokens", []))
    previous_tokens = set(previous.get("tokens", []))
    if not current_tokens or not previous_tokens:
        return 0.0
    token_jaccard = len(current_tokens & previous_tokens) / max(1, len(current_tokens | previous_tokens))
    current_entities = set(current.get("entities", []))
    previous_entities = set(previous.get("entities", []))
    entity_overlap = len(current_entities & previous_entities)
    current_actions = set(current.get("actions", []))
    previous_actions = set(previous.get("actions", []))
    action_overlap = len(current_actions & previous_actions)
    sequence_score = SequenceMatcher(None, " ".join(sorted(current_tokens)), " ".join(sorted(previous_tokens))).ratio()
    score = max(token_jaccard, sequence_score * 0.75)
    if entity_overlap >= 2 and (action_overlap >= 1 or token_jaccard >= 0.28):
        score = max(score, 0.82)
    elif entity_overlap >= 3 and token_jaccard >= 0.22:
        score = max(score, 0.78)
    return score


def cleanup_recent_news_events(state: dict[str, Any], now: float | None = None) -> list[dict[str, Any]]:
    now = now or time.time()
    recent_raw = state.get(RECENT_NEWS_STATE_KEY, [])
    if not isinstance(recent_raw, list):
        recent_raw = []
    recent: list[dict[str, Any]] = []
    for item in recent_raw:
        if isinstance(item, dict) and now - float(item.get("ts", 0) or 0) <= RECENT_NEWS_WINDOW_SECONDS:
            recent.append(item)
    state[RECENT_NEWS_STATE_KEY] = recent[-250:]
    return state[RECENT_NEWS_STATE_KEY]


def find_recent_duplicate_event(post: Post, state: dict[str, Any]) -> dict[str, Any] | None:
    current = news_event_signature(post)
    for item in reversed(cleanup_recent_news_events(state)):
        previous = item.get("signature", {}) if isinstance(item, dict) else {}
        if not isinstance(previous, dict):
            continue
        if _event_similarity(current, previous) >= 0.78:
            return item
    return None


def remember_recent_news_event(post: Post, state: dict[str, Any]) -> None:
    recent = cleanup_recent_news_events(state)
    recent.append(
        {
            "ts": time.time(),
            "username": post.username,
            "priority": SOURCE_PRIORITY.get(post.username, 0),
            "link": post.link,
            "signature": news_event_signature(post),
        }
    )
    state[RECENT_NEWS_STATE_KEY] = recent[-250:]


def sort_candidate_posts_for_priority(candidates: list[tuple[str, Post, float]]) -> list[tuple[str, Post, float]]:
    return sorted(
        candidates,
        key=lambda item: (
            -SOURCE_PRIORITY.get(item[0], 0),
            -(item[1].published_ts or 0),
        ),
    )

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
    text = re.sub(r"(?im)^\s*(?:presented|sponsored|brought to you)\s+by\s+.+$", "", text)
    text = re.sub(r"(?iu)\s+(?:presented|sponsored|brought to you)\s+by\s+[A-Za-z0-9 ._-]+[.!?]?\s*$", "", text)
    text = re.sub(r"(?iu)\s+(?:מוצג על ידי|בחסות|פרזנטד ביי)\s+[A-Za-zא-ת0-9 ._-]+[.!?]?\s*$", "", text)
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


def remove_israel_time_additions(text: str) -> str:
    text = re.sub(r"\s*\([^)]*שעון ישראל[^)]*\)", "", text or "")
    text = re.sub(r"\s*,?\s*(?:בשעה\s*)?\d{1,2}:\d{2}\s*שעון ישראל", "", text)
    text = re.sub(r"\s*שעון ישראל", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def final_visual_cleanup(text: str) -> str:
    text = normalize_country_flags(text or "")
    invisible = r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]*"
    georgia_flag = "\U0001F1EC\U0001F1EA"
    for code, flag in COUNTRY_CODE_FLAGS.items():
        text = re.sub(rf"(?<![A-Za-z]){invisible}{code[0]}{invisible}[\s._-]*{invisible}{code[1]}{invisible}(?![A-Za-z])", flag, text)
    text = re.sub(rf"(?<![A-Za-z]){invisible}G{invisible}[\s._-]*{invisible}E{invisible}(?![A-Za-z])", georgia_flag, text)
    text = re.sub(rf"(?i)(?:\bGeorgia\b|\bGeorgian\b|גאורגיה|גיאורגיה|גרוזיה)\s*(?:flag|דגל)?\s*[:：-]?\s*{invisible}GE{invisible}\b", georgia_flag, text)
    text = re.sub(rf"{georgia_flag}(?:\s*GE\b)+", georgia_flag, text)
    text = re.sub(rf"(?:\bGE\s*)+{georgia_flag}", georgia_flag, text)
    text = re.sub(rf"{georgia_flag}(?:\s*{georgia_flag})+", georgia_flag, text)
    text = re.sub(rf"{georgia_flag}(?:\s*[\U0001F535\U0001F534\u26aa\u26ab]){{1,6}}", georgia_flag, text)
    text = re.sub(rf"(?:[\U0001F535\U0001F534\u26aa\u26ab]\s*){{1,6}}{georgia_flag}", georgia_flag, text)
    text = re.sub(r"\U0001F3F4(?![\U000E0061-\U000E007A])\ufe0f?", "", text)
    text = re.sub(r"\b(?:חבצ'ה|חביציה|חביצ׳ה|חביצה)\b", "חביצ'ה קווארצחליה", text)
    text = re.sub(r"\b(?:קווארה|קווארא|קווארצ׳חליה|קווארצחלייה)\b", "קווארצחליה", text)
    link_markers = r"(?:\U0001F447|\u2b07\ufe0f?|\U0001F53D|\u2198\ufe0f?|\u2935\ufe0f?|\u2193)"
    text = re.sub(rf"(?m)^\s*(?:{link_markers}\s*)+$", "", text)
    text = re.sub(rf"\s*(?:{link_markers}\s*)+(?=$|\n)", "", text)
    text = re.sub(rf"(?m)^\s*(?:{link_markers}\s*)+", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" *\n+ *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return strip_country_code_leftovers_near_flags(text).strip()


def clean_before_translation(text: str) -> str:
    text = normalize_country_flags(text)
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


def clean_for_ai_translation(text: str) -> str:
    text = normalize_country_flags(text)
    text = remove_external_links(text)
    text = remove_weird_symbols(text)
    text = convert_hashtags_to_text(text)
    text = re.sub(r"(?im)^\s*(video|watch video|וידאו|וידיאו)\s*$", "", text)
    text = text.replace("&amp;", "&")
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_emojis(text: str, limit: int = 6) -> list[str]:
    emojis: list[str] = []
    text = text or ""
    for emoji in TAG_FLAG_RE.findall(text):
        if emoji not in emojis:
            emojis.append(emoji)
        if len(emojis) >= limit:
            return emojis
    text_without_tag_flags = TAG_FLAG_RE.sub("", text)
    for emoji in EMOJI_RE.findall(text_without_tag_flags):
        if emoji == "\U0001F3F4":
            continue
        if emoji not in emojis:
            emojis.append(emoji)
        if len(emojis) >= limit:
            break
    return emojis


def preserve_original_emojis(original: str, translated: str) -> str:
    if not translated:
        return translated
    missing = [emoji for emoji in extract_emojis(original) if emoji not in translated]
    if not missing:
        return translated
    return f"{' '.join(missing)} {translated}".strip()


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
GEMINI_FAILURE_LOGGED = False
GEMINI_DISABLED_UNTIL = 0.0
GEMINI_COOLDOWN_IS_QUOTA = False
GEMINI_KEY_COOLDOWNS: dict[str, float] = {}
GEMINI_NEXT_KEY_INDEX = 0
GEMINI_KEY_LOCK = Lock()
GEMINI_TRANSLATION_SEMAPHORE = BoundedSemaphore(GEMINI_MAX_PARALLEL_TRANSLATIONS)


def translation_cache_key(text: str) -> str:
    model = GEMINI_FAST_MODEL if GEMINI_API_KEYS else "free"
    return hashlib.sha256(f"{model}\n{text}".encode("utf-8")).hexdigest()


def gemini_error_summary(error: Exception | None) -> str:
    text = str(error or "")
    lowered = text.lower()
    if "quota" in lowered or "429" in lowered or "resource_exhausted" in lowered:
        return "מכסת ג'מיני נגמרה או שיש הגבלת קצב זמנית"
    if "403" in lowered or "api key" in lowered or "permission" in lowered:
        return "בעיה בהרשאת מפתח Gemini"
    if "timeout" in lowered or "timed out" in lowered:
        return "זמן התגובה של ג'מיני נגמר"
    return "שגיאת ג'מיני זמנית"


def is_gemini_quota_error(error: Exception | None) -> bool:
    lowered = str(error or "").lower()
    return "quota" in lowered or "429" in lowered or "resource_exhausted" in lowered


def gemini_key_label(index: int) -> str:
    return f"מפתח {index + 1}/{len(GEMINI_API_KEYS)}"


def gemini_key_order() -> list[tuple[int, str]]:
    global GEMINI_NEXT_KEY_INDEX
    if not GEMINI_API_KEYS:
        return []
    with GEMINI_KEY_LOCK:
        start = GEMINI_NEXT_KEY_INDEX % len(GEMINI_API_KEYS)
        GEMINI_NEXT_KEY_INDEX = (GEMINI_NEXT_KEY_INDEX + 1) % len(GEMINI_API_KEYS)
    now = time.time()
    ordered = [(index, GEMINI_API_KEYS[index]) for index in range(len(GEMINI_API_KEYS))]
    rotated = ordered[start:] + ordered[:start]
    active = [(index, key) for index, key in rotated if GEMINI_KEY_COOLDOWNS.get(key, 0.0) <= now]
    return active or rotated


def cool_down_gemini_key(key: str, error: Exception | None) -> None:
    cooldown = GEMINI_COOLDOWN_SECONDS if is_gemini_quota_error(error) else 60
    GEMINI_KEY_COOLDOWNS[key] = time.time() + cooldown


def log_gemini_unavailable(error: Exception | None) -> None:
    global GEMINI_FAILURE_LOGGED, GEMINI_DISABLED_UNTIL, GEMINI_COOLDOWN_IS_QUOTA
    GEMINI_DISABLED_UNTIL = time.time() + GEMINI_COOLDOWN_SECONDS
    GEMINI_COOLDOWN_IS_QUOTA = is_gemini_quota_error(error)
    if GEMINI_FAILURE_LOGGED:
        return
    GEMINI_FAILURE_LOGGED = True
    logging.warning("⚠️ ג'מיני לא זמין כרגע. אם זו מכסה, הפוסט יישלח בגיבוי; אחרת הבוט ינסה שוב בהמשך. סיבה: %s", gemini_error_summary(error))


def mark_gemini_available() -> None:
    global GEMINI_FAILURE_LOGGED, GEMINI_DISABLED_UNTIL, GEMINI_COOLDOWN_IS_QUOTA
    if GEMINI_FAILURE_LOGGED:
        logging.info("✅ ג'מיני חזר לעבוד")
    GEMINI_FAILURE_LOGGED = False
    GEMINI_DISABLED_UNTIL = 0.0
    GEMINI_COOLDOWN_IS_QUOTA = False


def relevant_name_glossary(text: str) -> str:
    lowered = (text or "").lower()
    lines: list[str] = []
    for replacements in (HANDLE_REPLACEMENTS, TEAM_REPLACEMENTS, PLAYER_REPLACEMENTS):
        for source, target in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
            clean_source = source.lstrip("@")
            if clean_source.lower() in lowered or target in text:
                lines.append(f"- {source} = {target}")
            if len(lines) >= 35:
                return "\n".join(dict.fromkeys(lines))
    return "\n".join(dict.fromkeys(lines))


def google_translate(text: str) -> str:
    query = urllib.parse.urlencode({"client": "gtx", "sl": "auto", "tl": TARGET_LANGUAGE, "dt": "t", "q": text})
    data = json.loads(http_get(f"https://translate.googleapis.com/translate_a/single?{query}", timeout=8).decode("utf-8"))
    return "".join(part[0] for part in data[0] if part and part[0]).strip()


def mymemory_translate(text: str) -> str:
    query = urllib.parse.urlencode({"q": text, "langpair": f"auto|{TARGET_LANGUAGE}"})
    data = json.loads(http_get(f"https://api.mymemory.translated.net/get?{query}", timeout=8).decode("utf-8"))
    return html.unescape(data.get("responseData", {}).get("translatedText", "")).strip()


def gemini_translate(text: str, respect_global_cooldown: bool = True) -> str:
    if not GEMINI_API_KEYS:
        raise RuntimeError("No Gemini API key configured")
    if respect_global_cooldown and time.time() < GEMINI_DISABLED_UNTIL:
        if GEMINI_COOLDOWN_IS_QUOTA:
            raise RuntimeError("Gemini quota cooldown")
        raise RuntimeError("Gemini is in temporary cooldown")
    glossary = relevant_name_glossary(text)
    glossary_block = f"\nKnown names glossary. Use these exact Hebrew names when relevant:\n{glossary}\n" if glossary else ""
    prompt = (
        "You are a senior Hebrew sports-news editor.\n"
        "Rewrite this X/Twitter football post as a polished Hebrew Telegram news update.\n"
        "Use the full context and meaning. Do not translate word by word and do not preserve awkward original order.\n"
        "Rules:\n"
        "- Return only the final Hebrew post text, ready to publish.\n"
        "- First decide if this is a real football news update. Send only reports with concrete news: transfer, contract, injury, squad, appointment, dismissal, official announcement, negotiation, bid, match-relevant update, or a verified factual development.\n"
        "- If it is only a social/atmosphere post, quote, interview sentence, player/coach reaction, meme, congratulation, reaction, Instagram/story screenshot, personal message, vague caption, tribute, joke, opinion or image with no concrete news update, return an empty string.\n"
        "- Interview quotes such as 'X on Y: ...', 'X said...', 'X told...' are usually not news.\n"
        "- Keep an interview/quote only when it is genuinely newsworthy or highly relevant: club president/owner/coach/agent speaking about a star player, contract renewal, future at the club, transfer, injury, official decision, squad call-up, bid, club direction or a major sporting development.\n"
        "- Remove ordinary statistics-only posts unless they contain a real record, official achievement or current news angle.\n"
        "- Write 1-3 natural Hebrew news sentences unless the original genuinely needs more.\n"
        "- Keep only the actual news. Remove credits, source tags, TV/network tags, junk suffixes, tracking text and promo text.\n"
        "- Remove all URLs, website domains and link text.\n"
        "- For @handles: if it is a real player, club, journalist or outlet needed for the news, write it naturally in Hebrew; if it is only a source credit or junk tag, omit it.\n"
        "- For hashtags: turn meaningful football hashtags into normal Hebrew words; omit promotional/source hashtags.\n"
        "- Before returning, verify every player, coach and club name against football context. Fix malformed transliterations and accents. Do not invent names.\n"
        "- For famous players with nicknames or partial names, expand to the correct common full Hebrew name when the identity is clear. Example: Khvicha/Kvaratskhelia should be חביצ'ה קווארצחליה, not a shortened broken name.\n"
        "- If a name is uncertain, keep the clean original name instead of producing broken Hebrew.\n"
        "- Never replace a club/team with a different club/team that is not explicitly in the original post. If Real Madrid appears, do not change it to Real Sociedad; if a club is not named, do not invent one.\n"
        "- Preserve the original news facts exactly: clubs, teams, player names, destinations, scores, dates and competitions must match the source post.\n"
        "- Preserve tense and time exactly. Do not turn past into future, future into past, or change any year/date/time such as 2026 into another year.\n"
        "- Treat facts as locked data: names, clubs, years, numbers, scorelines and dates may be translated but never corrected, guessed or rewritten into different facts.\n"
        "- If the post mentions a role such as 'next manager/coach' without naming the club in that phrase, do not add a club name by assumption.\n"
        "- Convert important club/player @handles into natural Hebrew names. Remove handles only when they are just credits or promotion.\n"
        "- Remove sponsor lines such as 'presented by', 'sponsored by', broadcasts, TV/network credits and app promotions.\n"
        "- Do not convert times to Israel time and never add the words 'שעון ישראל'. Keep original time-zone wording only if it is essential.\n"
        "- If the post is mostly a video caption, write one clean Hebrew sentence that explains the actual clip.\n"
        "- Use common Hebrew football names and terms. Prefer natural sports Hebrew over literal translation.\n"
        "- Translate foreign-language headlines and outlet names into clean Hebrew. For example, L'Équipe/LEquipe should be written as לאקיפ, not as broken mixed text.\n"
        "- Keep useful numbers, fees, years, dates, emojis and line breaks.\n"
        "- If GE is used as a country/flag marker, output the Georgia flag emoji 🇬🇪, not the letters GE.\n"
        "- If a two-letter country code is used as a flag marker, output the correct flag emoji instead of the letters. Preserve real flag emojis from the source and never replace a flag with a generic black flag.\n"
        "- Remove down arrows or pointing-down emojis when they only pointed to a removed link or quoted post.\n"
        "- Never leave raw @handles, random English words, malformed names, underscores, brackets or weird symbols at the end.\n"
        "- If the post contains only a vague teaser/link/promo and no real news, return an empty string.\n"
        "- Do not explain anything.\n"
        f"{glossary_block}\n"
        f"POST:\n{text}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "topP": 0.8},
    }
    last_error: Exception | None = None
    for index, key in gemini_key_order():
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{urllib.parse.quote(GEMINI_FAST_MODEL)}:generateContent?key={urllib.parse.quote(key)}"
        )
        try:
            data = http_post_json(url, payload, timeout=8, max_attempts=1, respect_retry_after=False)
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            translated = "".join(part.get("text", "") for part in parts).strip()
            if translated:
                GEMINI_KEY_COOLDOWNS.pop(key, None)
                mark_gemini_available()
                return translated
        except Exception as exc:
            last_error = exc
            cool_down_gemini_key(key, exc)
            logging.warning("⚠️ ג'מיני נכשל עם %s, מנסה מפתח הבא. סיבה: %s", gemini_key_label(index), gemini_error_summary(exc))
            continue
    log_gemini_unavailable(last_error)
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
    text = normalize_country_flags(text)
    for english, hebrew in STAT_REPLACEMENTS.items():
        text = re.sub(rf"\b(\d+)\s*{re.escape(english)}\b", rf"\1 {hebrew}", text, flags=re.IGNORECASE)
        text = re.sub(rf"\b{re.escape(english)}\s*(\d+)\b", rf"\1 {hebrew}", text, flags=re.IGNORECASE)
    text = transliterate_latin_names(text)
    text = remove_external_links(text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"([א-ת])\s+-\s+([א-ת])", r"\1-\2", text)
    text = re.sub(r"\b(\d+)\s*-\s*(\d+)\b", r"\1-\2", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" *\n+ *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = remove_untranslated_tail_tokens(text)
    text = remove_junk_tail_lines(text)
    text = remove_israel_time_additions(text)
    text = final_visual_cleanup(text)
    return text.strip()


def translation_contradicts_source(original: str, translated: str) -> bool:
    original_norm = original or ""
    translated_norm = translated or ""
    sensitive_pairs = (
        ("Real Madrid", "ריאל מדריד", "Real Sociedad", "ריאל סוסיאדד"),
        ("Real Sociedad", "ריאל סוסיאדד", "Real Madrid", "ריאל מדריד"),
        ("Barcelona", "ברצלונה", "Real Madrid", "ריאל מדריד"),
        ("Real Madrid", "ריאל מדריד", "Barcelona", "ברצלונה"),
    )
    for source_en, source_he, wrong_en, wrong_he in sensitive_pairs:
        source_in_original = source_en.lower() in original_norm.lower() or source_he in original_norm
        wrong_in_original = wrong_en.lower() in original_norm.lower() or wrong_he in original_norm
        wrong_in_translation = wrong_he in translated_norm or wrong_en.lower() in translated_norm.lower()
        if source_in_original and not wrong_in_original and wrong_in_translation:
            return True
    return False


def translation_changes_locked_numbers(original: str, translated: str) -> bool:
    original_years = set(re.findall(r"\b(?:19|20)\d{2}\b", original or ""))
    translated_years = set(re.findall(r"\b(?:19|20)\d{2}\b", translated or ""))
    if translated_years - original_years:
        return True

    original_scores = set(re.findall(r"\b\d+\s*[-:]\s*\d+\b", original or ""))
    translated_scores = set(re.findall(r"\b\d+\s*[-:]\s*\d+\b", translated or ""))
    if translated_scores - original_scores:
        return True

    return False


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


def untranslated_fallback_text(text: str) -> str:
    text = clean_before_translation(text)
    text = remove_untranslated_tail_tokens(text)
    text = remove_junk_tail_lines(text)
    text = remove_israel_time_additions(text)
    return text.strip()


def translate_text(text: str) -> str:
    started = time.perf_counter()
    ai_text = clean_for_ai_translation(text)
    cleaned = clean_before_translation(text)
    if not ai_text and not cleaned:
        return ""
    prepared = apply_phrase_replacements(cleaned, FOOTBALL_TERMS)
    prepared = apply_phrase_replacements(prepared, TEAM_REPLACEMENTS)
    prepared = apply_phrase_replacements(prepared, PLAYER_REPLACEMENTS)
    gemini_key = translation_cache_key(ai_text or prepared)
    fallback_key = hashlib.sha256(f"fallback\n{prepared}".encode("utf-8")).hexdigest()
    if GEMINI_API_KEYS and gemini_key in TRANSLATION_CACHE:
        return final_visual_cleanup(preserve_original_country_flags(ai_text or text, preserve_original_emojis(ai_text or text, TRANSLATION_CACHE[gemini_key])))
    if not GEMINI_API_KEYS and fallback_key in TRANSLATION_CACHE:
        return final_visual_cleanup(preserve_original_country_flags(ai_text or text, preserve_original_emojis(ai_text or text, TRANSLATION_CACHE[fallback_key])))

    if GEMINI_API_KEYS and ai_text:
        last_error: Exception | None = None
        for attempt in range(1, GEMINI_TRANSLATION_ATTEMPTS + 1):
            try:
                with GEMINI_TRANSLATION_SEMAPHORE:
                    polished = final_hebrew_polish(gemini_translate(ai_text, respect_global_cooldown=False))
                polished = final_visual_cleanup(preserve_original_country_flags(ai_text, preserve_original_emojis(ai_text, polished)))
                if translation_contradicts_source(ai_text, polished):
                    raise RuntimeError("Gemini translation contradicted source names")
                if translation_changes_locked_numbers(ai_text, polished):
                    raise RuntimeError("Gemini translation changed locked numbers or years")
                if polished:
                    TRANSLATION_CACHE[gemini_key] = polished
                    return polished
            except Exception as exc:
                last_error = exc
                if attempt < GEMINI_TRANSLATION_ATTEMPTS:
                    logging.warning(
                        "⚠️ ג'מיני נכשל זמנית בתרגום, ממתין %s שניות ומנסה שוב (%s/%s). סיבה: %s",
                        GEMINI_RETRY_WAIT_SECONDS,
                        attempt,
                        GEMINI_TRANSLATION_ATTEMPTS,
                        gemini_error_summary(exc),
                    )
                    time.sleep(GEMINI_RETRY_WAIT_SECONDS)
        logging.error("⛔ ג'מיני נכשל אחרי %s ניסיונות. הפוסט לא יישלח בלי תרגום ויישאר לניסיון הבא.", GEMINI_TRANSLATION_ATTEMPTS)
        raise TranslationUnavailable("Gemini translation failed after all attempts")

    if fallback_key in TRANSLATION_CACHE:
        return final_visual_cleanup(preserve_original_country_flags(ai_text or text, preserve_original_emojis(ai_text or text, TRANSLATION_CACHE[fallback_key])))

    if not GEMINI_API_KEYS:
        logging.error("⛔ אין מפתח ג'מיני מוגדר. הפוסט לא יישלח בלי תרגום ג'מיני.")
        raise TranslationUnavailable("No Gemini API key configured")

    for source_text in (prepared, cleaned):
        for provider in (google_translate, mymemory_translate):
            try:
                translated = provider(source_text)
                if latin_ratio(translated) > 0.45:
                    translated = translate_in_sentences(source_text)
                polished = final_hebrew_polish(translated)
                polished = final_visual_cleanup(preserve_original_country_flags(source_text, preserve_original_emojis(source_text, polished)))
                if polished and latin_ratio(polished) <= 0.30:
                    TRANSLATION_CACHE[fallback_key] = polished
                    return polished
            except Exception:
                continue

    fallback = final_hebrew_polish(prepared)
    fallback = final_visual_cleanup(preserve_original_emojis(ai_text or text, fallback))
    TRANSLATION_CACHE[fallback_key] = fallback
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
    # If translation clearly failed, keep the original quote in English/its source language.
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
    text = final_hebrew_polish(normalize_country_flags(html.unescape(text or "").strip()))
    text = re.sub(r"(?im)^\s*(וידאו|וידיאו)\s*$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = remove_junk_tail_lines(text)
    text = final_visual_cleanup(text)
    return text.strip()


def has_meaningful_text(text: str) -> bool:
    cleaned = tidy_translated_text(text)
    cleaned = re.sub(r"[\s\"'׳״.,:;!?()\[\]{}\-–—_]+", "", cleaned)
    return bool(cleaned and cleaned not in {"עדכוןחדש", "newupdate", "update"})


def rtl(text: str) -> str:
    return "\n".join(f"{RTL_MARK}{line}" if line.strip() else line for line in text.splitlines())


def telegram_api(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = http_post_json(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}", payload)
    if not response.get("ok"):
        raise RuntimeError(f"Telegram error: {response}")
    return response


def telegram_broadcast(method: str, payload: dict[str, Any]) -> None:
    sent_count = 0
    errors: list[str] = []
    for chat_id in TELEGRAM_CHAT_IDS:
        chat_payload = dict(payload)
        chat_payload["chat_id"] = chat_id
        try:
            telegram_api(method, chat_payload)
            sent_count += 1
            logging.info("טלגרם: %s נשלח בהצלחה לערוץ %s", method, chat_id)
        except Exception as exc:
            errors.append(f"{chat_id}: {exc}")
            logging.error("טלגרם: %s נכשל לערוץ %s, ממשיך לערוצים האחרים: %s", method, chat_id, exc)
    if sent_count == 0:
        raise RuntimeError("Telegram broadcast failed for all chats: " + " | ".join(errors))


def telegram_broadcast_with_text_fallback(method: str, payload: dict[str, Any], fallback_text: str) -> None:
    sent_count = 0
    errors: list[str] = []
    for chat_id in TELEGRAM_CHAT_IDS:
        chat_payload = dict(payload)
        chat_payload["chat_id"] = chat_id
        try:
            telegram_api(method, chat_payload)
            sent_count += 1
            logging.info("טלגרם: %s נשלח בהצלחה לערוץ %s", method, chat_id)
            continue
        except Exception as exc:
            errors.append(f"{chat_id} {method}: {exc}")
            logging.error("טלגרם: %s נכשל לערוץ %s. מנסה לשלוח טקסט רגיל לאותו ערוץ: %s", method, chat_id, exc)

        try:
            telegram_api(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": trim(fallback_text, 4096),
                    "disable_web_page_preview": True,
                    "parse_mode": "HTML",
                },
            )
            sent_count += 1
            logging.info("טלגרם: fallback טקסט נשלח בהצלחה לערוץ %s", chat_id)
        except Exception as fallback_exc:
            errors.append(f"{chat_id} fallback: {fallback_exc}")
            logging.error(
                "טלגרם: גם fallback טקסט נכשל לערוץ %s. אם זה הערוץ %s, צריך לבדוק שהבוט אדמין עם הרשאה לפרסם הודעות: %s",
                chat_id,
                chat_id,
                fallback_exc,
            )
            if "need administrator rights" in str(fallback_exc):
                logging.error(
                    "בדיקת הרשאות: טלגרם אומר שהבוט לא יכול לפרסם בערוץ %s. צריך לפתוח בערוץ: Administrators -> הבוט -> להפעיל Post Messages/פרסום הודעות.",
                    chat_id,
                )

    if sent_count == 0:
        raise RuntimeError("Telegram broadcast failed for all chats: " + " | ".join(errors))


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
    video_label = f"<b>{html.escape(rtl('📹 וידיאו מצורף'))}</b>"
    quote_label = f"<b>{html.escape(rtl('פוסט מצוטט:'))}</b>"
    signature = f'<a href="{html.escape(SIGNATURE_LINK)}">{html.escape(rtl(SIGNATURE_TEXT))}</a>'

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

    parts.extend(["", signature])

    return "\n".join(parts)


def send_post(post: Post) -> dict[str, Any]:
    started = time.perf_counter()
    timings: dict[str, Any] = {"sent": False, "mode": "skipped"}
    translation_started = time.perf_counter()
    translated = translate_text(post.text)
    if is_self_quote(post):
        quoted_translated = ""
        quoted_author_translated = ""
    else:
        quoted_translated = translate_quoted_text(post.quoted_text) if post.quoted_text else ""
        quoted_author_translated = translate_quoted_author(post.quoted_author) if post.quoted_author else ""
    timings["translation_seconds"] = time.perf_counter() - translation_started

    if not has_meaningful_text(translated) and not has_meaningful_text(quoted_translated):
        timings["total_seconds"] = time.perf_counter() - started
        timings["mode"] = "no_news"
        return timings

    video_started = time.perf_counter()
    video_url = sendable_video_url(post) if SEND_VIDEO_FILES else ""
    timings["video_lookup_seconds"] = time.perf_counter() - video_started

    prepare_started = time.perf_counter()
    message = build_message(
        post,
        translated,
        quoted_translated,
        quoted_author_translated,
        include_video_link=not bool(video_url),
    )
    images = [] if post.has_video else post.image_urls[:MAX_IMAGES_PER_POST]
    timings["prepare_seconds"] = time.perf_counter() - prepare_started

    if video_url:
        try:
            send_started = time.perf_counter()
            telegram_broadcast_with_text_fallback(
                "sendVideo",
                {
                    "video": video_url,
                    "caption": trim_keep_ending(message, 1024),
                    "parse_mode": "HTML",
                    "supports_streaming": True,
                },
                message,
            )
            timings["send_seconds"] = time.perf_counter() - send_started
            timings["total_seconds"] = time.perf_counter() - started
            timings["sent"] = True
            timings["mode"] = "וידיאו"
            return timings
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
        media: list[dict[str, Any]] = []
        for index, image_url in enumerate(images):
            item: dict[str, Any] = {"type": "photo", "media": image_url}
            if index == 0:
                item["caption"] = trim_keep_ending(message, 1024)
                item["parse_mode"] = "HTML"
            media.append(item)
        try:
            send_started = time.perf_counter()
            telegram_broadcast_with_text_fallback("sendMediaGroup", {"media": media}, message)
        except Exception as exc:
            logging.warning("Could not send images, falling back to text only: %s", exc)
        else:
            timings["send_seconds"] = time.perf_counter() - send_started
            timings["total_seconds"] = time.perf_counter() - started
            timings["sent"] = True
            timings["mode"] = f"{len(images)} תמונה/ות"
            return timings

    send_started = time.perf_counter()
    telegram_broadcast(
        "sendMessage",
        {
            "text": trim(message, 4096),
            "disable_web_page_preview": True,
            "parse_mode": "HTML",
        },
    )
    timings["send_seconds"] = time.perf_counter() - send_started
    timings["total_seconds"] = time.perf_counter() - started
    timings["sent"] = True
    timings["mode"] = "טקסט"
    return timings


def send_video_after_message(video_url: str) -> None:
    if not (SEND_VIDEO_FILES and video_url):
        return
    try:
        telegram_broadcast(
            "sendVideo",
            {
                "video": video_url,
                "supports_streaming": True,
            },
        )
    except Exception as exc:
        logging.warning("Post text was sent, but Telegram could not attach video: %s", exc)
        try:
            telegram_broadcast(
                "sendMessage",
                {
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
    if not TELEGRAM_CHAT_IDS:
        raise ValueError("Put at least one Telegram group chat ID in TELEGRAM_CHAT_IDS")
    if not X_ACCOUNTS:
        raise ValueError("Add at least one X/Twitter account to X_ACCOUNTS")


def run_once(state: dict[str, list[str]], startup_cycle: bool = False, min_published_ts: float = 0.0) -> int:
    cycle_started = time.perf_counter()
    first_run = not any(state.values())
    sent = 0
    fetch_workers = min(current_max_parallel_account_checks(), max(1, len(X_ACCOUNTS)))
    send_executor = ThreadPoolExecutor(max_workers=current_max_parallel_post_sends())
    send_futures = []
    queued_ids: set[str] = set()
    global_candidate_posts: list[tuple[str, Post, float]] = []

    def send_task(item: tuple[str, Post, float]) -> tuple[str, list[str], str, bool, dict[str, Any]]:
        username, post, found_seconds = item
        try:
            result = send_post(post)
            result["found_seconds"] = found_seconds
            result["post_age_seconds"] = max(0.0, time.time() - post.published_ts) if post.published_ts else 0.0
            result["source_name"] = post.source_name
            return username, post.dedupe_ids, post.link, True, result
        except Exception as exc:
            logging.error("Failed sending %s: %s", post.link, exc)
            return username, post.dedupe_ids, post.link, False, {}

    try:
        with ThreadPoolExecutor(max_workers=fetch_workers) as fetch_executor:
            future_map = {fetch_executor.submit(fetch_posts_safely, username): username for username in ordered_accounts()}
            for future in as_completed(future_map):
                username, posts = future.result()
                seen = set(state.get(username, []))
                if not posts:
                    continue

                if not first_run and username not in state and not SEND_BACKLOG_FOR_NEW_ACCOUNTS:
                    for post in posts:
                        seen.update(post.dedupe_ids)
                    state[username] = list(seen)[-500:]
                    continue

                new_posts = [post for post in posts if not any(post_id in seen for post_id in post.dedupe_ids)]
                if startup_cycle and SEND_LAST_POST_ON_EVERY_START:
                    new_posts = posts[:1]
                elif first_run and SEND_LAST_POST_ON_FIRST_RUN:
                    new_posts = posts[:1]
                elif first_run:
                    for post in posts:
                        seen.update(post.dedupe_ids)
                    state[username] = list(seen)[-500:]
                    continue

                candidate_posts: list[tuple[str, Post, float]] = []
                for post in reversed(new_posts[:MAX_NEW_POSTS_PER_ACCOUNT_PER_CHECK]):
                    if min_published_ts and post.published_ts and post.published_ts < min_published_ts:
                        seen.update(post.dedupe_ids)
                        logging.info("דילוג: הבוט הופעל מחדש, ופוסט ישן מ-10 דקות לא נשלח: %s", post.link)
                        continue
                    if is_too_old_post(post) and not (startup_cycle and SEND_LAST_POST_ON_EVERY_START):
                        seen.update(post.dedupe_ids)
                        logging.info("דילוג: פוסט ישן מדי מ-@%s לא נשלח: %s", username, post.link)
                        continue
                    if any(post_id in queued_ids for post_id in post.dedupe_ids):
                        logging.info("דילוג: כפילות באותו סבב מ-@%s לא נשלחה: %s", username, post.link)
                        continue
                    if is_women_or_wnba_post(post):
                        seen.update(post.dedupe_ids)
                        logging.info("דילוג מסנן: נשים/WNBA מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_link_only_or_details_post(post):
                        seen.update(post.dedupe_ids)
                        logging.info("דילוג מסנן: קישור/פרטים בלי דיווח מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_podcast_or_longform_post(post):
                        seen.update(post.dedupe_ids)
                        logging.info("דילוג מסנן: פודקאסט/תוכן ארוך מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_non_news_social_post(post):
                        seen.update(post.dedupe_ids)
                        logging.info("דילוג מסנן: פוסט לא חדשותי/סטטיסטיקה בלבד מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        logging.info("דילוג: פוסט חברתי/אווירה בלי דיווח חדשותי מ-@%s לא נשלח: %s", username, post.link)
                        continue
                    duplicate_event = find_recent_duplicate_event(post, state)
                    if duplicate_event:
                        seen.update(post.dedupe_ids)
                        logging.info("דילוג כפילות חכמה: אותו אירוע כבר נשלח בשעתיים האחרונות מ-@%s. הנוכחי מ-@%s לא נשלח: %s", duplicate_event.get("username", "unknown"), username, post.link)
                        continue
                    candidate_posts.append((username, post, time.perf_counter() - cycle_started))

                global_candidate_posts.extend(candidate_posts)

                state[username] = list(seen)[-500:]

        for candidate in sort_candidate_posts_for_priority(global_candidate_posts):
            username, post, _ = candidate
            seen = set(state.get(username, []))
            duplicate_event = find_recent_duplicate_event(post, state)
            if duplicate_event:
                seen.update(post.dedupe_ids)
                state[username] = list(seen)[-500:]
                logging.info("דילוג כפילות חכמה באותו סבב: אותו אירוע כבר נבחר ממקור עדיף/קודם. @%s לא נשלח: %s", username, post.link)
                continue
            remember_recent_news_event(post, state)
            send_futures.append(send_executor.submit(send_task, candidate))
            queued_ids.update(post.dedupe_ids)

        for future in as_completed(send_futures):
            username, post_ids, link, ok, result = future.result()
            if not ok:
                continue
            if result.get("sent"):
                seen = set(state.get(username, []))
                seen.update(post_ids)
                state[username] = list(seen)[-500:]
                sent += 1
                logging.info("✅ נשלח פוסט מ-@%s | מקור: %s", username, result.get("source_name", "unknown"))
                logging.info(
                    "זמנים: גיל %.0fs | מציאה %.2fs | בינה %.2fs | וידיאו %.2fs | הכנה %.2fs | שליחה %.2fs | סה״כ %.2fs",
                    result.get("post_age_seconds", 0.0),
                    result.get("found_seconds", 0.0),
                    result.get("translation_seconds", 0.0),
                    result.get("video_lookup_seconds", 0.0),
                    result.get("prepare_seconds", 0.0),
                    result.get("send_seconds", 0.0),
                    result.get("total_seconds", 0.0),
                )
            elif result.get("mode") == "no_news":
                seen = set(state.get(username, []))
                seen.update(post_ids)
                state[username] = list(seen)[-500:]
                logging.info("דילוג: ג'מיני זיהה שאין עדכון חדשותי, הפוסט סומן כנראה: %s", link)
            else:
                logging.warning("⏳ פוסט מ-@%s לא נשלח ולכן לא סומן כנראה, יישאר לניסיון הבא: %s", username, link)
    finally:
        send_executor.shutdown(wait=True, cancel_futures=False)

    return sent


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    validate_settings()
    print(f"Football bot is running. Accounts: {', '.join('@' + account for account in X_ACCOUNTS)}", flush=True)
    print(f"Checking every {CHECK_EVERY_SECONDS} seconds.", flush=True)
    print("Gemini translation: " + ("ON" if GEMINI_API_KEYS else "OFF - using free fallback"), flush=True)
    if CONTROL_CHAT_ID:
        Thread(target=control_loop, daemon=True).start()

    if SEND_STARTUP_STATUS_MESSAGE:
        try:
            telegram_broadcast(
                "sendMessage",
                {
                    "text": "בוט הכדורגל הופעל. בודק עדכונים...",
                    "disable_web_page_preview": True,
                },
            )
        except Exception as exc:
            logging.error("Startup Telegram test message failed: %s", exc)

    startup_cycle = True
    skipped_for_shabbat = False
    paused_logged = False
    while True:
        cycle_started = time.time()
        try:
            control_state = load_control_state()
            if bool(control_state.get("paused", False)):
                if not paused_logged:
                    logging.info("בוט הכדורגל כבוי מלוח השליטה. לא סורק ולא שולח.")
                    paused_logged = True
                time.sleep(current_check_every_seconds())
                continue
            paused_logged = False

            if is_shabbat_now():
                if not skipped_for_shabbat:
                    logging.info("מצב שבת פעיל: הבוט לא סורק, לא שולח ולא שומר מצב")
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
                logging.info("מצב שבת הסתיים: פוסטים משבת סומנו כנצפו בלי שליחה")
                time.sleep(current_check_every_seconds())
                continue

            resume_min_ts = float(control_state.get("resume_min_ts", 0.0) or 0.0)
            sent = run_once(state, startup_cycle=startup_cycle, min_published_ts=resume_min_ts)
            startup_cycle = False
            save_state(state)
            if resume_min_ts:
                save_control_state(False, resume_min_ts=0.0)
            save_translation_cache(TRANSLATION_CACHE)
            if sent:
                print(f"Sent {sent} new post(s).", flush=True)
        except Exception as exc:
            logging.error("Unexpected error. Bot will keep running: %s", exc)
        elapsed = time.time() - cycle_started
        time.sleep(max(0, current_check_every_seconds() - elapsed))


if __name__ == "__main__":
    main()

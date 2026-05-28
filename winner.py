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
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ====== SETTINGS ======

# You asked to include these values in the new football bot.
# You can still override the token safely with an environment variable:
# export TELEGRAM_BOT_TOKEN="your_token"
TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "8480434397:AAF8ay6JxuYsf7ytVOLG73bVJiJQHq8CMx4",
)
TELEGRAM_CHAT_ID = "-1003869452843"

# X/Twitter usernames for the requested football sources.
# If one account changes handle later, update only this list + display name below.
X_ACCOUNTS = [
    # 🌍 כללי
    "FabrizioRomano",
    "David_Ornstein",
    "DiMarzio",
    "JacobsBen",

    # 🏴 אנגליה
    "lauriewhitwell",
    "SamLee",
    "_pauljoyce",
    "Matt_Law_DT",

    # 🇪🇸 ספרד
    "MatteMoretto",
    "ffpolo",
    "gerardromero",
    "AranchaMOBILE",
    "JLSanchez78",

    # 🇮🇹 איטליה
    "AlfredoPedulla",
    "86_longo",

    # 🇩🇪 גרמניה
    "Plettigoal",
    "cfbayern",

    # 🇫🇷 צרפת
    "FabriceHawkins",
    "Tanziloic",
]

ACCOUNT_DISPLAY_NAMES = {
    # 🌍 כללי
    "FabrizioRomano": "פבריציו רומאנו - כללי",
    "David_Ornstein": "דיוויד אורנשטיין - כללי",
    "DiMarzio": "ג׳אנלוקה די מארציו - כללי",
    "JacobsBen": "בן ג׳ייקובס - כללי",

    # 🏴 אנגליה
    "lauriewhitwell": "לורי וויטוול - מנצ׳סטר יונייטד",
    "SamLee": "סם לי - מנצ׳סטר סיטי",
    "_pauljoyce": "פול ג׳ויס - ליברפול",
    "Matt_Law_DT": "מאט לאו - צ׳לסי",

    # 🇪🇸 ספרד
    "MatteMoretto": "מתאו מורטו - ספרד",
    "ffpolo": "פרננדו פולו - ברצלונה",
    "gerardromero": "חרארד רומרו - ברצלונה",
    "AranchaMOBILE": "ארנצ׳ה רודריגז - ריאל מדריד",
    "JLSanchez78": "חוסה לואיס סאנצ׳ז - ריאל מדריד",

    # 🇮🇹 איטליה
    "AlfredoPedulla": "אלפרדו פדולה - איטליה",
    "86_longo": "דניאלה לונגו - מילאן",

    # 🇩🇪 גרמניה
    "Plettigoal": "פלוריאן פלטנברג - גרמניה",
    "cfbayern": "כריסטיאן פאלק - גרמניה",

    # 🇫🇷 צרפת
    "FabriceHawkins": "פבריס הוקינס - צרפת",
    "Tanziloic": "לואיק טנזי - צרפת",
}

TARGET_LANGUAGE = "he"
CHECK_EVERY_SECONDS = 60
HTTP_RETRIES = 3
RETRY_SLEEP_SECONDS = 4
MAX_NEW_POSTS_PER_ACCOUNT_PER_CHECK = 3
SEND_LAST_POST_ON_FIRST_RUN = True
# This forces a visible startup test every time the script starts.
# It sends the latest post from each account even if a state file already exists.
SEND_LAST_POST_ON_EVERY_START = True
# Sends a simple Telegram message immediately on startup so you know the bot can reach Telegram.
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


# ====== FOOTBALL TRANSLATION SETTINGS ======

TRANSLATION_PROVIDERS = ["google", "mymemory"]

FOOTBALL_TERMS = {
    # reporting / transfer language
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
    "new contract": "חוזה חדש",
    "contract extension": "הארכת חוזה",
    "loan deal": "עסקת השאלה",
    "loan move": "מעבר בהשאלה",
    "permanent move": "מעבר קבוע",
    "option to buy": "אופציית רכישה",
    "obligation to buy": "חובת רכישה",
    "release clause": "סעיף שחרור",
    "buyout clause": "סעיף שחרור",
    "sell-on clause": "סעיף אחוזים ממכירה עתידית",
    "add-ons": "בונוסים",
    "fixed fee": "סכום קבוע",
    "transfer fee": "דמי העברה",
    "free transfer": "העברה חופשית",
    "free agent": "שחקן חופשי",
    "out of contract": "מסיים חוזה",
    "final details": "הפרטים האחרונים",
    "final stages": "בשלבים האחרונים",
    "advanced talks": "שיחות מתקדמות",
    "negotiations ongoing": "המשא ומתן נמשך",
    "talks ongoing": "השיחות נמשכות",
    "deal collapsing": "העסקה בדרך לקריסה",
    "deal off": "העסקה ירדה מהפרק",
    "green light": "אור ירוק",
    "approved the move": "אישר את המעבר",
    "set to join": "צפוי להצטרף",
    "set to sign": "צפוי לחתום",
    "close to joining": "קרוב להצטרף",
    "close to signing": "קרוב לחתימה",
    "joins": "מצטרף ל",
    "signs for": "חותם ב",
    "will sign": "יחתום",
    "has signed": "חתם",
    "agreed to join": "סיכם על הצטרפותו ל",
    "agreed deal": "סיכם על עסקה",
    "proposal submitted": "הוגשה הצעה",
    "bid submitted": "הוגשה הצעה",
    "opening bid": "הצעה ראשונית",
    "formal bid": "הצעה רשמית",
    "improved bid": "הצעה משופרת",
    "bid rejected": "ההצעה נדחתה",
    "bid accepted": "ההצעה התקבלה",
    "club-to-club agreement": "סיכום בין המועדונים",
    "waiting for documents": "ממתינים למסמכים",
    "documents signed": "המסמכים נחתמו",
    "announcement soon": "הודעה רשמית בקרוב",
    "official soon": "רשמי בקרוב",
    "done deal": "עסקה סגורה",

    # football words
    "manager": "מאמן",
    "head coach": "מאמן ראשי",
    "sporting director": "מנהל מקצועי",
    "director of football": "מנהל מקצועי",
    "goalkeeper": "שוער",
    "centre back": "בלם",
    "center back": "בלם",
    "left back": "מגן שמאלי",
    "right back": "מגן ימני",
    "full back": "מגן",
    "wing back": "ווינג בק",
    "midfielder": "קשר",
    "defensive midfielder": "קשר אחורי",
    "attacking midfielder": "קשר התקפי",
    "winger": "שחקן כנף",
    "striker": "חלוץ",
    "forward": "חלוץ",
    "number 9": "חלוץ 9",
    "injury": "פציעה",
    "injured": "פצוע",
    "suspended": "מושעה",
    "available": "זמין למשחק",
    "not available": "לא זמין למשחק",
    "matchday squad": "סגל המשחק",
    "starting XI": "ההרכב הפותח",
    "line-up": "הרכב",
    "lineup": "הרכב",
    "clean sheet": "שער נקי",
    "equaliser": "שער שוויון",
    "equalizer": "שער שוויון",
    "stoppage time": "תוספת הזמן",
    "extra time": "הארכה",
    "penalty shootout": "דו-קרב פנדלים",
    "VAR": "VAR",
    "Champions League": "ליגת האלופות",
    "Europa League": "הליגה האירופית",
    "Conference League": "הקונפרנס ליג",
    "Premier League": "הפרמייר ליג",
    "La Liga": "לה ליגה",
    "Serie A": "סרייה א׳",
    "Bundesliga": "בונדסליגה",
    "Ligue 1": "ליגה 1",
}

# Full club names only where possible, to avoid ruining normal words.
TEAM_REPLACEMENTS = {
    # England
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

    # Spain
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
    "Betis": "בטיס",
    "Real Betis": "בטיס",

    # Italy
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

    # Germany
    "Bayern Munich": "באיירן מינכן",
    "Bayern": "באיירן",
    "Borussia Dortmund": "בורוסיה דורטמונד",
    "Dortmund": "דורטמונד",
    "Bayer Leverkusen": "באייר לברקוזן",
    "Leverkusen": "לברקוזן",
    "RB Leipzig": "לייפציג",
    "Leipzig": "לייפציג",
    "Eintracht Frankfurt": "איינטרכט פרנקפורט",

    # France
    "Paris Saint-Germain": "פריז סן ז׳רמן",
    "PSG": "פ.ס.ז׳",
    "Marseille": "מארסיי",
    "Lyon": "ליון",
    "Monaco": "מונאקו",
    "Nice": "ניס",
    "Lille": "ליל",
    "Rennes": "רן",
}

HEBREW_FINAL_FIXES = {
    "כאן אנחנו הולכים": "הנה זה קורה",
    "הנה אנחנו הולכים": "הנה זה קורה",
    "לפי הבנתי": "לפי המידע",
    "מבין ש": "לפי המידע, ",
    "על פי מקורות": "לפי מקורות",
    "מקורות אומרים": "לפי מקורות",
    "מקורות מספרים": "לפי מקורות",
    "הסכם מילולי": "סיכום בעל פה",
    "הסכם מלא": "סיכום מלא",
    "תנאים אישיים מוסכמים": "סוכמו התנאים האישיים",
    "בדיקות רפואיות הוזמנו": "נקבעו בדיקות רפואיות",
    "בדיקה רפואית": "בדיקות רפואיות",
    "השאלה": "השאלה",
    "עסקת הלוואה": "עסקת השאלה",
    "מעבר הלוואה": "מעבר בהשאלה",
    "אופציה לקנות": "אופציית רכישה",
    "חובה לקנות": "חובת רכישה",
    "תשלום העברה": "דמי העברה",
    "העברה חינם": "העברה חופשית",
    "סוכן חופשי": "שחקן חופשי",
    "הצעה פורמלית": "הצעה רשמית",
    "הצעה משופרת": "הצעה משופרת",
    "הצעה נדחתה": "ההצעה נדחתה",
    "הצעה התקבלה": "ההצעה התקבלה",
    "הכרזה בקרוב": "הודעה רשמית בקרוב",
    "רשמי בקרוב": "רשמי בקרוב",
    "עסקה נעשתה": "עסקה סגורה",
    "מאמן ראש": "מאמן ראשי",
    "מנהל ספורטיבי": "מנהל מקצועי",
    "מנהל כדורגל": "מנהל מקצועי",
    "קו-אפ": "הרכב",
    "גיליון נקי": "שער נקי",
    "זמן עצירה": "תוספת הזמן",
    "זמן נוסף": "הארכה",
    "יריות עונשין": "דו-קרב פנדלים",
    "פנדל שוטאאוט": "דו-קרב פנדלים",
    "ליגת האלופות של אופא": "ליגת האלופות",
    "ליגה ראשונה": "הפרמייר ליג",
    "סדרה א": "סרייה א׳",
    "סרי א": "סרייה א׳",
    "ליגה 1": "ליגה 1",
    "טוויט": "פוסט",
    "ציוץ": "פוסט",
    "ציוצים": "פוסטים",
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


def http_get(url: str, timeout: int = 25) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 football-x-to-telegram/1.0",
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
    for match in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', raw_html or "", re.I):
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
    for match in re.findall(r'https?://[^\s"\'<>]+', raw_html or "", re.I):
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
            logging.info("Checking %s via %s", username, url)
            posts = parse_posts(username, http_get(url))
            if posts:
                logging.info("Found %s posts for %s", len(posts), username)
                return posts
            logging.warning("Feed returned no posts: %s", url)
        except Exception as exc:
            logging.warning("Feed failed for %s: %s", url, exc)
    logging.error("All feed sources failed or returned empty for %s", username)
    return []


def apply_phrase_replacements(text: str, replacements: dict[str, str]) -> str:
    for source, target in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        # If the source has only Latin chars/numbers/spaces, use English word boundaries.
        if re.fullmatch(r"[A-Za-z0-9 ._'’:-]+", source):
            pattern = r"(?<![A-Za-z0-9_])" + re.escape(source) + r"(?![A-Za-z0-9_])"
            text = re.sub(pattern, target, text, flags=re.IGNORECASE)
        else:
            text = text.replace(source, target)
    return text


def apply_team_replacements(text: str) -> str:
    return apply_phrase_replacements(text, TEAM_REPLACEMENTS)


def normalize_stats(text: str) -> str:
    for english, hebrew in STAT_REPLACEMENTS.items():
        text = re.sub(rf"\b(\d+)\s*{re.escape(english)}\b", rf"\1 {hebrew}", text, flags=re.IGNORECASE)
        text = re.sub(rf"\b{re.escape(english)}\s*(\d+)\b", rf"\1 {hebrew}", text, flags=re.IGNORECASE)
    return text


def clean_before_translation(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"(?<!\w)#([A-Za-z0-9_]+)", r"\1", text)
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
    translated = "".join(part[0] for part in data[0] if part and part[0]).strip()
    return translated


def mymemory_translate(text: str) -> str:
    query = urllib.parse.urlencode({"q": text, "langpair": f"auto|{TARGET_LANGUAGE}"})
    url = f"https://api.mymemory.translated.net/get?{query}"
    data = json.loads(http_get(url, timeout=20).decode("utf-8"))
    translated = data.get("responseData", {}).get("translatedText", "")
    return html.unescape(translated).strip()


def looks_untranslated(original: str, translated: str) -> bool:
    if not translated:
        return True
    original_clean = re.sub(r"\s+", " ", original).strip().lower()
    translated_clean = re.sub(r"\s+", " ", translated).strip().lower()
    if original_clean == translated_clean:
        return True
    hebrew_chars = len(re.findall(r"[א-ת]", translated))
    latin_chars = len(re.findall(r"[A-Za-z]", translated))
    # Allow names/clubs in English, but reject mostly-English paragraphs.
    return latin_chars > 25 and latin_chars > hebrew_chars * 2


def pre_translate_football_terms(text: str) -> str:
    text = normalize_stats(text)
    text = apply_phrase_replacements(text, FOOTBALL_TERMS)
    text = apply_team_replacements(text)
    return text


def final_hebrew_polish(text: str) -> str:
    text = html.unescape(text or "")
    text = apply_team_replacements(text)
    text = apply_phrase_replacements(text, HEBREW_FINAL_FIXES)
    text = normalize_stats(text)

    # Common style fixes.
    text = text.replace("X / טוויטר", "X")
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
    prepared = pre_translate_football_terms(cleaned)
    last_error: Exception | None = None

    for provider in TRANSLATION_PROVIDERS:
        try:
            if provider == "google":
                translated = google_translate(prepared)
            elif provider == "mymemory":
                translated = mymemory_translate(prepared)
            else:
                continue

            if looks_untranslated(prepared, translated):
                raise RuntimeError("Translation appears untranslated or mostly English")

            return final_hebrew_polish(translated)
        except Exception as exc:
            last_error = exc
            logging.warning("Translation provider failed (%s): %s", provider, exc)

    logging.error("All translation providers failed: %s", last_error)
    # Last-resort fallback: send cleaned/pre-polished text rather than crashing.
    return final_hebrew_polish(prepared)


def remove_inline_links(text: str) -> str:
    return clean_before_translation(text)


def tidy_translated_text(text: str) -> str:
    text = html.unescape(text or "").strip()
    text = remove_inline_links(text)
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
    logging.info("Calling Telegram API method %s", method)
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    response = http_post_json(url, payload)
    if not response.get("ok"):
        raise RuntimeError(f"Telegram error: {response}")
    logging.info("Telegram API method %s succeeded", method)


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
    safe_quoted_author = html.escape(rtl(post.quoted_author or "פוסט מצוטט"))
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
    logging.info("Preparing post from @%s: %s", post.username, post.link)
    translated = translate_text(post.text)
    quoted_translated = translate_text(post.quoted_text) if post.quoted_text else ""
    message = build_message(post, translated, quoted_translated)

    images = post.image_urls[:MAX_IMAGES_PER_POST]
    if images and SEND_IMAGES_AFTER_TEXT:
        logging.info("Sending text first, then %s image(s). Videos are ignored.", len(images))
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
        logging.info("Post has %s image(s). Sending images, videos are ignored.", len(images))
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
    else:
        logging.info("Post has no sendable images. Sending text only.")

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
        logging.info("No state file yet. This looks like the first run.")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        logging.info("Loaded state from %s", STATE_FILE)
        return {key: list(value) for key, value in data.items()}
    except Exception:
        logging.warning("Could not read state file. Starting fresh.")
        return {}


def save_state(state: dict[str, list[str]]) -> None:
    path = state_path()
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)
    logging.info("Saved state to %s", STATE_FILE)


def validate_settings() -> None:
    if not TELEGRAM_BOT_TOKEN or "PASTE" in TELEGRAM_BOT_TOKEN:
        raise ValueError("Put your Telegram bot token in TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID or "PUT_" in str(TELEGRAM_CHAT_ID) or "PASTE" in str(TELEGRAM_CHAT_ID):
        raise ValueError("Put your Telegram group chat ID in TELEGRAM_CHAT_ID")
    if not X_ACCOUNTS:
        raise ValueError("Add at least one X/Twitter account to X_ACCOUNTS")


def run_once(state: dict[str, list[str]], startup_cycle: bool = False) -> int:
    first_run = not any(state.values())
    sent = 0

    for username in X_ACCOUNTS:
        logging.info("Starting account check: @%s", username)
        seen = set(state.get(username, []))
        posts = fetch_posts(username)
        if not posts:
            logging.warning("No posts available for @%s in this cycle", username)
            continue

        new_posts = [post for post in posts if post.post_id not in seen]

        if startup_cycle and SEND_LAST_POST_ON_EVERY_START:
            latest_post = posts[0]
            logging.warning("Startup mode: sending latest post for @%s", username)
            try:
                send_post(latest_post)
                seen.add(latest_post.post_id)
                sent += 1
                logging.warning("Startup latest post sent for @%s", username)
            except Exception as exc:
                logging.error("Failed sending startup latest post for @%s: %s", username, exc)
            for post in posts:
                seen.add(post.post_id)
            state[username] = list(seen)[-300:]
            continue

        if first_run and SEND_LAST_POST_ON_FIRST_RUN:
            latest_post = posts[0]
            if latest_post.post_id not in seen:
                logging.info("First run: sending latest post for @%s as a startup test", username)
                try:
                    send_post(latest_post)
                    seen.add(latest_post.post_id)
                    sent += 1
                    logging.info("Startup test post sent for @%s", username)
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
            logging.info("First run: marked existing posts as seen for @%s", username)
            continue

        logging.info("Found %s new post(s) for @%s", len(new_posts), username)
        for post in reversed(new_posts[:MAX_NEW_POSTS_PER_ACCOUNT_PER_CHECK]):
            try:
                send_post(post)
                seen.add(post.post_id)
                sent += 1
                logging.info("Sent %s", post.link)
                time.sleep(1)
            except Exception as exc:
                logging.error("Failed sending %s: %s", post.link, exc)

        state[username] = list(seen)[-300:]
        logging.info("Finished account check: @%s", username)

    return sent


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    validate_settings()
    print(f"Football bot is running. Accounts: {', '.join('@' + account for account in X_ACCOUNTS)}", flush=True)
    print(f"Checking every {CHECK_EVERY_SECONDS} seconds.", flush=True)

    if SEND_STARTUP_STATUS_MESSAGE:
        try:
            telegram_api(
                "sendMessage",
                {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": "✅ בוט הכדורגל הופעל. עכשיו בודק פוסטים אחרונים...",
                    "disable_web_page_preview": True,
                },
            )
            print("Startup Telegram test message sent.", flush=True)
        except Exception as exc:
            logging.error("Startup Telegram test message failed: %s", exc)

    startup_cycle = True
    while True:
        try:
            state = load_state()
            sent = run_once(state, startup_cycle=startup_cycle)
            startup_cycle = False
            save_state(state)
            if sent:
                print(f"Sent {sent} new post(s).", flush=True)
        except Exception as exc:
            logging.error("Unexpected error. Bot will keep running: %s", exc)
        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()

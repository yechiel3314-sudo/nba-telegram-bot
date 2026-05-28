#!/usr/bin/env python3
"""
Single-file X/Twitter to Telegram forwarder.

Server run:
  python3 x_to_telegram_single.py

No X API key is needed. This uses public RSS-style mirrors, so availability
depends on those mirrors. Telegram bot token is required.
"""

from __future__ import annotations

import html
import json
import logging
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


# ====== EDIT THESE SETTINGS ======

TELEGRAM_BOT_TOKEN = "8795392686:AAFElKo3sML_dqA9YaVz2iArTUoYGcGgBuI"
TELEGRAM_CHAT_ID = "-1003918247986"

X_ACCOUNTS = [
    "NBA",
    "ShamsCharania",
    "highkin",
    "NBACentral",
    "UnderdogNBA",
    "LegionHoops",
]

TARGET_LANGUAGE = "he"
TRANSLATION_MODE = "sports_polished_free"
CHECK_EVERY_SECONDS = 60
HTTP_RETRIES = 3
RETRY_SLEEP_SECONDS = 4
MAX_NEW_POSTS_PER_ACCOUNT_PER_CHECK = 3
SEND_LAST_POST_ON_FIRST_RUN = False
MAX_IMAGES_PER_POST = 4
STATE_FILE = "x_to_telegram_state.json"
SEND_IMAGES_AFTER_TEXT = False

ACCOUNT_DISPLAY_NAMES = {
    "NBA": "NBA",
    "ShamsCharania": "שאמס צ׳רניה",
    "highkin": "שון הייקין - פורטלנד",
    "NBACentral": "NBA סנטרל",
    "UnderdogNBA": "אנדרדוג NBA",
    "LegionHoops": "לג׳יון הופס",
}

RTL_MARK = "\u200f"

TRANSLATION_REPLACEMENTS = {
    "דראפט ה-NBA": "דראפט ה-NBA",
    "סוכן חופשי": "שחקן חופשי",
    "סוכנות חופשית": "שוק השחקנים החופשיים",
    "פוסט-סיזן": "פלייאוף",
    "לאחר העונה": "פלייאוף",
    "מחוץ לעונה": "הפגרה",
    "בחירת דראפט": "בחירת דראפט",
    "בחירה בסיבוב הראשון": "בחירת סיבוב ראשון",
    "בחירה בסיבוב השני": "בחירת סיבוב שני",
    "קו אחורי": "קו גארדים",
    "מגרש ביתי": "בית",
    "ניצחון שלישי ברציפות": "ניצחון שלישי ברציפות",
    "הטרייד": "הטרייד",
    "חוזה מקסימום": "חוזה מקסימום",
    "מקורות אומרים": "לפי מקורות",
    "דיווח": "דיווח",
    "טוויט": "פוסט",
    "ציוץ": "פוסט",
    "נמסר": "דווח",
    "על פי מקורות": "לפי מקורות",
    "בלייזרים": "בלייזרס",
    "פורטלנד טרייל בלייזרים": "פורטלנד טרייל בלייזרס",
    "טרייל בלייזרים": "טרייל בלייזרס",
    "לייקרס": "לייקרס",
    "סלטיקס": "סלטיקס",
    "נאגטס": "נאגטס",
    "טימברוולבס": "טימברוולבס",
    "ווריורס": "ווריורס",
    "ת'אנדר": "ת'אנדר",
    "מאבריקס": "מאבריקס",
    "קליפרס": "קליפרס",
    "סאנס": "סאנס",
    "באקס": "באקס",
    "ניקס": "ניקס",
    "נטס": "נטס",
    "היט": "היט",
    "פייסרס": "פייסרס",
    "קאבס": "קאבס",
    "קינגס": "קינגס",
    "פליקנס": "פליקנס",
    "גריזליס": "גריזליס",
    "הוקס": "הוקס",
    "ראפטורס": "ראפטורס",
    "רוקטס": "רוקטס",
    "ספרס": "ספרס",
    "שאמס חרניה": "שאמס צ׳רניה",
    "שמס חרניה": "שאמס צ׳רניה",
    "שאמס צ'רניה": "שאמס צ׳רניה",
    "שון הייקין": "שון הייקין",
    "השמש": "סאנס",
}

SPORTS_PHRASES = {
    "has agreed to": "סיכם על",
    "have agreed to": "סיכמו על",
    "is signing": "יחתום",
    "are signing": "יחתמו",
    "is expected to": "צפוי",
    "are expected to": "צפויים",
    "league sources tell": "לפי מקורות בליגה",
    "sources tell": "לפי מקורות",
    "per sources": "לפי מקורות",
    "sources said": "לפי מקורות",
    "free agent": "השחקן החופשי",
    "free agency": "שוק השחקנים החופשיים",
    "trade deadline": "דדליין הטריידים",
    "first-round pick": "בחירת סיבוב ראשון",
    "second-round pick": "בחירת סיבוב שני",
    "two-way contract": "חוזה דו-כיווני",
    "training camp": "מחנה האימונים",
    "regular season": "העונה הסדירה",
    "postseason": "הפלייאוף",
    "playoffs": "הפלייאוף",
    "finals": "הגמר",
    "game winner": "סל ניצחון",
    "career-high": "שיא קריירה",
    "season-high": "שיא עונתי",
    "home court": "הבית",
    "on the season": "העונה",
    "behind big performances from": "בזכות הופעות גדולות של",
    "went off": "התפוצץ",
    "3rd straight W": "ניצחון שלישי ברציפות",
    "third straight W": "ניצחון שלישי ברציפות",
    "agrees to": "מסכים ל",
    "lands with": "חותם אצל",
    "returns to": "חוזר ל",
    "plans to sign": "צפוי לחתום",
    "will sign": "יחתום",
    "will return": "יחזור",
    "has been traded": "עבר בטרייד",
    "is being traded": "עובר בטרייד",
    "has requested a trade": "ביקש טרייד",
    "extension": "הארכת חוזה",
    "max contract": "חוזה מקסימום",
    "rookie scale extension": "הארכת חוזה רוקי",
    "waived": "שוחרר",
    "buyout": "בייאאוט",
    "injury report": "דוח פציעות",
    "breaking": "דיווח דרמטי",
    "questionable": "בספק",
    "probable": "ככל הנראה ישחק",
    "out": "בחוץ",
    "available": "זמין למשחק",
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
    "sign-and-trade": "חתימה והעברה",
    "two-way": "דו-כיווני",
    "double-double": "דאבל-דאבל",
    "triple-double": "טריפל-דאבל",
    "clutch": "קלאץ׳",
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
    "LA Clippers": "לוס אנג׳לס קליפרס",
    "Los Angeles Clippers": "לוס אנג׳לס קליפרס",
    "Los Angeles Lakers": "לוס אנג׳לס לייקרס",
    "Memphis Grizzlies": "ממפיס גריזליס",
    "Miami Heat": "מיאמי היט",
    "Milwaukee Bucks": "מילווקי באקס",
    "Minnesota Timberwolves": "מינסוטה טימברוולבס",
    "New Orleans Pelicans": "ניו אורלינס פליקנס",
    "New York Knicks": "ניו יורק ניקס",
    "Oklahoma City Thunder": "אוקלהומה סיטי ת׳אנדר",
    "Orlando Magic": "אורלנדו מג׳יק",
    "Philadelphia 76ers": "פילדלפיה 76׳רס",
    "Phoenix Suns": "פיניקס סאנס",
    "Portland Trail Blazers": "פורטלנד טרייל בלייזרס",
    "Sacramento Kings": "סקרמנטו קינגס",
    "San Antonio Spurs": "סן אנטוניו ספרס",
    "Toronto Raptors": "טורונטו ראפטורס",
    "Utah Jazz": "יוטה ג׳אז",
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
    "Pelicans": "פליקנס",
    "Knicks": "ניקס",
    "Thunder": "ת׳אנדר",
    "Magic": "מג׳יק",
    "76ers": "76׳רס",
    "Sixers": "סיקסרס",
    "Suns": "סאנס",
    "Blazers": "בלייזרס",
    "Trail Blazers": "טרייל בלייזרס",
    "Kings": "קינגס",
    "Spurs": "ספרס",
    "Raptors": "ראפטורס",
    "Jazz": "ג׳אז",
    "Wizards": "וויזארדס",
    "לוחמים": "ווריורס",
    "הלוחמים": "הווריורס",
    "רשתות": "נטס",
    "הרשתות": "הנטס",
    "שמשות": "סאנס",
    "השמשות": "הסאנס",
    "קסם": "מג׳יק",
    "הקסם": "המג׳יק",
    "חלוצים": "בלייזרס",
    "שבילים": "בלייזרס",
    "קוצצים": "קליפרס",
    "הקוצצים": "הקליפרס",
    "אשף": "וויזארדס",
    "אשפים": "וויזארדס",
}

FEED_TEMPLATES = [
    "https://rsshub.app/twitter/user/{username}",
    "https://rsshub.rssforever.com/twitter/user/{username}",
    "https://nitter.net/{username}/rss",
]

# ====== END SETTINGS ======


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
VIDEO_EXTENSIONS = (".mp4", ".mov", ".m3u8", ".webm", ".avi", ".mkv")


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
            "User-Agent": "Mozilla/5.0 x-to-telegram-single/1.0",
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
        if not url:
            continue
        if mime.startswith("image/") or medium == "image" or is_image_url(url):
            images.append(url)

    unique: list[str] = []
    for url in images:
        if url not in unique:
            unique.append(url)
    return unique


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
        if not url:
            continue
        if mime.startswith("video/") or medium == "video" or is_video_url(url):
            videos.append(url)

    unique: list[str] = []
    for url in videos:
        if url not in unique:
            unique.append(url)
    return unique


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

        # RSS mirrors sometimes append the quoted/linked post as plain text.
        # A quoted post often starts with "Display Name (@username)".
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
    items = [
        element
        for element in root.iter()
        if strip_namespace(element.tag) in ("item", "entry")
    ]

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


def polish_translation(text: str) -> str:
    text = text or ""
    text = normalize_stat_abbreviations(text)
    text = apply_team_replacements(text)
    for source, target in TRANSLATION_REPLACEMENTS.items():
        text = text.replace(source, target)

    text = text.replace("N.B.A", "NBA").replace("W.N.B.A", "WNBA")
    text = text.replace("אי.אס.פי.אן", "ESPN").replace("E.S.P.N", "ESPN")
    extra_replacements = {
        "Pistons": "פיסטונס",
        "Bulls": "בולס",
        "Hornets": "הורנטס",
        "Magic": "מג'יק",
        "Wizards": "וויזארדס",
        "Jazz": "ג'אז",
    }
    for source, target in extra_replacements.items():
        text = text.replace(source, target)
    text = text.replace("שאמס צ'רניה", "שאמס צ׳רניה")
    text = text.replace("שאמס חרניה", "שאמס צ׳רניה")
    text = text.replace("שמס חרניה", "שאמס צ׳רניה")
    text = text.replace("טוויט", "פוסט")
    text = text.replace("ציוץ", "פוסט")
    text = text.replace("על פי מקורות", "לפי מקורות")
    text = text.replace("מדווח ESPN", "מדווח ב-ESPN")
    text = text.replace("ESPN מדווח", "מדווח ב-ESPN")
    text = text.replace("NBA Insider", "כתב ה-NBA")
    text = text.replace("NBA insider", "כתב ה-NBA")
    text = text.replace("W ", "ניצחון ")
    text = re.sub(r"\b(\d+)\s*-\s*(\d+)\b", r"\1-\2", text)
    text = re.sub(r"([A-Za-z][A-Za-z .'-]+):\s*(\d+)\s+נקודות", r"\2 נקודות של \1", text)
    text = re.sub(r"(\d+)-(\d+)\s+בעונה", r"\1-\2 העונה", text)
    text = text.replace("העונה בעונה", "העונה")
    text = text.replace(" מאחורי ", " בזכות ")
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"\bNBA\b", "NBA", text)
    text = re.sub(r"\bWNBA\b", "WNBA", text)
    text = re.sub(r"\bESPN\b", "ESPN", text)
    text = re.sub(r"\bMVP\b", "MVP", text)
    text = text.replace("נקודותים", "נקודות")
    text = text.replace("ריבאונדיםים", "ריבאונדים")
    text = text.replace("אסיסטיםים", "אסיסטים")
    text = text.replace("חטיפותים", "חטיפות")
    text = text.replace("חסימותים", "חסימות")
    text = text.replace("דקותים", "דקות")
    text = text.replace("נקודות נקודות", "נקודות")
    text = text.replace("ריבאונדים ריבאונדים", "ריבאונדים")
    text = text.replace("אסיסטים אסיסטים", "אסיסטים")
    text = text.replace("חטיפות חטיפות", "חטיפות")
    text = text.replace("חסימות חסימות", "חסימות")
    text = text.replace("דקות דקות", "דקות")
    text = re.sub(r"\s*-\s*ESPN", " - ESPN", text)
    text = re.sub(r"\s*-\s*MVP", " - MVP", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = text.replace("\n ", "\n").replace(" \n", "\n")
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"([א-ת])\s+-\s+([א-ת])", r"\1-\2", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def apply_team_replacements(text: str) -> str:
    for source, target in sorted(TEAM_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True):
        text = re.sub(re.escape(source), target, text, flags=re.IGNORECASE)
    return text


def translate_sports_phrase(text: str) -> str:
    working = text
    working = normalize_stat_abbreviations(working)
    for source, target in sorted(SPORTS_PHRASES.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = r"\b" + re.escape(source) + r"\b" if source.isalnum() else re.escape(source)
        working = re.sub(pattern, target, working, flags=re.IGNORECASE)
    working = re.sub(r"\b(\d+)[ -]point game\b", r"משחק של \1 נקודות", working, flags=re.IGNORECASE)
    working = re.sub(r"\b(\d+)[ -]game winning streak\b", r"רצף של \1 ניצחונות", working, flags=re.IGNORECASE)
    working = re.sub(r"\b(\d+)[ -]rebound game\b", r"משחק של \1 ריבאונדים", working, flags=re.IGNORECASE)
    working = re.sub(r"\b(\d+)[ -]assist game\b", r"משחק של \1 אסיסטים", working, flags=re.IGNORECASE)
    working = re.sub(r"\b(\d+)\s*points\b", r"\1 נקודות", working, flags=re.IGNORECASE)
    working = re.sub(r"\b(\d+)\s*rebounds\b", r"\1 ריבאונדים", working, flags=re.IGNORECASE)
    working = re.sub(r"\b(\d+)\s*assists\b", r"\1 אסיסטים", working, flags=re.IGNORECASE)
    working = re.sub(r"\b(\d+)\s*steals\b", r"\1 חטיפות", working, flags=re.IGNORECASE)
    working = re.sub(r"\b(\d+)\s*blocks\b", r"\1 חסימות", working, flags=re.IGNORECASE)
    working = re.sub(r"\b(\d+)\s*minutes\b", r"\1 דקות", working, flags=re.IGNORECASE)
    return working


def normalize_stat_abbreviations(text: str) -> str:
    stats = {
        "PTS": "נקודות",
        "REB": "ריבאונדים",
        "AST": "אסיסטים",
        "STL": "חטיפות",
        "BLK": "חסימות",
        "MIN": "דקות",
    }
    for abbr, hebrew in stats.items():
        text = re.sub(rf"\b(\d+)\s*{abbr}\b", rf"\1 {hebrew}", text, flags=re.IGNORECASE)
        text = re.sub(rf"\b{abbr}\s*(\d+)\b", rf"\1 {hebrew}", text, flags=re.IGNORECASE)
    for abbr, hebrew in stats.items():
        text = re.sub(rf"\b{abbr}\b", hebrew, text, flags=re.IGNORECASE)
    return text


def rewrite_hebrew_sports_style(text: str) -> str:
    text = text or ""
    text = fix_english_leftovers(text)
    text = apply_team_replacements(text)

    replacements = [
        (r"מאחורי הופעות גדולות של", "בזכות הופעות גדולות של"),
        (r"עובר ל־?(\d+)-(\d+)", r"עולה ל-\1-\2"),
        (r"עברה ל־?(\d+)-(\d+)", r"עולה ל-\1-\2"),
        (r"עבר ל־?(\d+)-(\d+)", r"עולה ל-\1-\2"),
        (r"על העונה", "העונה"),
        (r"בבית המשפט הביתי", "בבית"),
        (r"במגרש הביתי", "בבית"),
        (r"מגרש ביתי", "בית"),
        (r"מגרש הבית", "הבית"),
        (r"מאחורי", "בזכות"),
        (r"בחירה מספר", "בחירה מס׳"),
        (r"הסיבוב הראשון", "סיבוב ראשון"),
        (r"הסיבוב השני", "סיבוב שני"),
        (r"סוכן חופשי", "שחקן חופשי"),
        (r"סוכנות חופשית", "שוק השחקנים החופשיים"),
        (r"לאחר העונה", "פלייאוף"),
        (r"פוסט עונה", "פלייאוף"),
        (r"משחק המנצח", "סל הניצחון"),
        (r"המשחק המנצח", "סל הניצחון"),
        (r"הליגה אומרת", "לפי הליגה"),
        (r"מקורות ליגה אומרים", "לפי מקורות בליגה"),
        (r"מקורות אומרים", "לפי מקורות"),
        (r"הוא אמור", "הוא צפוי"),
        (r"אמור ל", "צפוי ל"),
        (r"היא אמורה", "היא צפויה"),
        (r"הם אמורים", "הם צפויים"),
        (r"20-כדור", "20 נקודות"),
        (r"20 בול", "20 נקודות"),
        (r"3 ברציפות", "ניצחון שלישי ברציפות"),
        (r"W 3 ברציפות", "ניצחון שלישי ברציפות"),
        (r"W שלישי ברציפות", "ניצחון שלישי ברציפות"),
        (r"קו הגארדים", "קו גארדים"),
        (r"יהיה בחוץ", "לא ישחק"),
        (r"נשלל", "לא ישחק"),
        (r"זמין", "זמין למשחק"),
        (r"חוזר אל", "חוזר ל"),
        (r"נחת עם", "חתם אצל"),
        (r"הרחבה", "הארכת חוזה"),
        (r"הרחבת חוזה", "הארכת חוזה"),
        (r"ויתרו עליו", "שוחרר"),
        (r"שובר:", "דיווח דרמטי:"),
        (r"יום ליום", "יום-יומי"),
        (r"יום-יום", "יום-יומי"),
        (r"הרכב הפותח", "החמישייה הפותחת"),
        (r"מאמן ראשי", "המאמן הראשי"),
        (r"תקרת משכורת", "תקרת השכר"),
        (r"מס יוקרה", "מס המותרות"),
        (r"אפשרות שחקן", "אופציית שחקן"),
        (r"אפשרות קבוצה", "אופציית קבוצה"),
        (r"מקצף זמזם", "סל עם הבאזר"),
        (r"בזמזם", "עם הבאזר"),
        (r"שעון יריות", "שעון הזריקות"),
        (r"שעות נוספות", "הארכה"),
    ]
    for source, target in replacements:
        text = re.sub(source, target, text)

    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"([א-ת])\s+!", r"\1!", text)
    text = re.sub(r"(?<=[.!?])\s+(?=[א-תA-Z0-9])", "\n\n", text)
    text = re.sub(r"\b(\d+)\s*-\s*(\d+)\b", r"\1-\2", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fix_english_leftovers(text: str) -> str:
    text = text or ""
    english_fixes = {
        "Minnesota moves to": "מינסוטה עולה ל",
        "behind big performances from": "בזכות הופעות גדולות של",
        "third straight dub": "ניצחון שלישי ברציפות",
        "3rd straight W": "ניצחון שלישי ברציפות",
        "We LOVE to see it": "כיף לראות את זה",
        "for you and your teammate": "לך ולחברה שלך לקבוצה",
        "20-ball": "20 נקודות",
        "ball-20": "20 נקודות",
        "on home court": "בבית",
        "went off": "התפוצצו",
        "in their third straight": "בניצחון השלישי ברציפות שלהן",
        "for the minnesotalynx": "של מינסוטה לינקס",
        "minnesotalynx": "מינסוטה לינקס",
        "reports": "מדווח",
        "sources": "מקורות",
    }
    for source, target in sorted(english_fixes.items(), key=lambda item: len(item[0]), reverse=True):
        text = re.sub(re.escape(source), target, text, flags=re.IGNORECASE)
    return text


def translate_chunk(text: str) -> str:
    query = urllib.parse.urlencode(
        {
            "client": "gtx",
            "sl": "auto",
            "tl": TARGET_LANGUAGE,
            "dt": "t",
            "q": text,
        }
    )
    url = f"https://translate.googleapis.com/translate_a/single?{query}"
    data = json.loads(http_get(url, timeout=20).decode("utf-8"))
    return "".join(part[0] for part in data[0] if part and part[0]).strip()


def translate_text(text: str) -> str:
    if not text:
        return ""
    logging.info("Translating post text")
    try:
        translated = translate_chunk(text)
        translated = polish_translation(translated)
        translated = rewrite_hebrew_sports_style(translated)
        logging.info("Translation finished")
        return translated
    except Exception as exc:
        logging.warning("Translation failed, sending original text: %s", exc)
        return text


def clean_before_translation(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text or "")
    text = text.replace("&amp;", "&")
    text = re.sub(r"(?<!\w)#[A-Za-z0-9_]+", "", text)
    text = re.sub(r"(?<!\w)@([A-Za-z0-9_]+)", r"\1", text)
    text = re.sub(r"(?im)^\s*(video|watch video|וידאו|וידיאו)\s*$", "", text)
    text = re.sub(r"(?m)^\s*[-–—]\s*$", "", text)
    text = text.replace("NBA", " NBA ")
    text = text.replace("WNBA", " WNBA ")
    text = text.replace("ESPN", " ESPN ")
    text = text.replace("MVP", " MVP ")
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def remove_inline_links(text: str) -> str:
    return clean_before_translation(text)


def tidy_translated_text(text: str) -> str:
    text = html.unescape(text or "").strip()
    text = remove_inline_links(text)
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)

    text = re.sub(r"(?<=[.!?])\s+(?=[א-תA-Z0-9])", "\n\n", text)
    text = re.sub(r"(?im)^\s*(וידאו|וידיאו)\s*$", "", text)
    text = re.sub(r"(?im)(?:\n|^)\s*(וידאו|וידיאו)\s*$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def rtl(text: str) -> str:
    return "\n".join(f"{RTL_MARK}{line}" if line.strip() else line for line in text.splitlines())


def has_video_hint(post: Post, translated: str) -> bool:
    return bool(post.has_video or post.video_urls)


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

    parts = [
        f"<b>{safe_account}</b>",
        "",
        safe_body,
    ]

    if post.link and post.primary_has_video:
        parts.extend(["", "", video_label, safe_link])

    if safe_quoted_body:
        parts.extend(
            [
                "",
                f"<b>{html.escape(rtl('פוסט מצוטט:'))}</b>",
                safe_quoted_author,
                safe_quoted_body,
            ]
        )
        if post.link and post.quoted_has_video:
            parts.extend(["", video_label, safe_link])

    if post.link:
        parts.extend(["", "", post_link_label, safe_link])
    return "\n".join(parts)


def send_post(post: Post) -> None:
    logging.info("Preparing post from @%s: %s", post.username, post.link)
    translated = translate_text(clean_before_translation(post.text))
    quoted_translated = translate_text(clean_before_translation(post.quoted_text)) if post.quoted_text else ""
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
        media = []
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


def load_state() -> dict[str, list[str]]:
    path = Path(STATE_FILE)
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
    path = Path(STATE_FILE)
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


def run_once(state: dict[str, list[str]]) -> int:
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
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    validate_settings()
    print(f"Bot is running. Accounts: {', '.join('@' + account for account in X_ACCOUNTS)}", flush=True)
    print(f"Checking every {CHECK_EVERY_SECONDS} seconds.", flush=True)

    while True:
        try:
            state = load_state()
            sent = run_once(state)
            save_state(state)
            if sent:
                print(f"Sent {sent} new post(s).", flush=True)
        except Exception as exc:
            logging.error("Unexpected error. Bot will keep running: %s", exc)
        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()

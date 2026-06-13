#!/usr/bin/env python3
"""
Single-file X/Twitter to Telegram football news forwarder.

Run:
  python3 football_x_to_telegram.py

What this version does:
- Scans all accounts in parallel with a server-credit-saving cadence.
- Checks several public RSS mirrors for each account and merges the results.
- Sends photos together with the Telegram message caption.
- Does not upload videos by default, to avoid extra video lookup requests.
- Removes all links from the post body. Only the final X post link is kept.
- Uses Gemini translation if you add GEMINI_API_KEY or GEMINI_API_KEYS.
- If Gemini translation is unavailable, the post is not sent.

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
import unicodedata
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

BOT_BUILD_ID = "football-rss-gemini-loader-reset-2026-06-11-1805"

# Telegram secrets are intentionally NOT hardcoded in this file.
# Set these in Railway -> Variables.
def required_env_any(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    raise RuntimeError("Missing required Railway variable. Add one of: " + ", ".join(names))


def required_env_list_any(*names: str) -> list[str]:
    raw_value = required_env_any(*names)
    values = [item.strip() for item in re.split(r"[,\n]+", raw_value) if item.strip()]
    if not values:
        raise RuntimeError("Telegram target chat variable exists but is empty: " + ", ".join(names))
    return values


# Same main bot token can be shared by several Neto Sport bots/services.
TELEGRAM_BOT_TOKEN = required_env_any(
    "NETO_SPORT_SHARED_MAIN_TELEGRAM_BOT_API_TOKEN_PRIVATE",
    "NETO_SPORT_FOOTBALL_NEWS_BOT_TELEGRAM_API_TOKEN_PRIVATE",
)
TELEGRAM_CHAT_IDS = required_env_list_any("NETO_SPORT_FOOTBALL_NEWS_TARGET_TELEGRAM_CHAT_IDS_PRIVATE")

# Optional AI translation. Put this in Railway Variables:
# GEMINI_API_KEY=your_key
# Or several keys separated by commas/new lines:
# GEMINI_API_KEYS=key1,key2,key3
# Or separate variables:
# GEMINI_API_KEY_1=key1 ... GEMINI_API_KEY_9=key9
def configured_gemini_api_keys() -> list[str]:
    raw_values: list[str] = []
    for name in (
        "GEMINI_API_KEYS",
        "GEMINI_API_KEY",
        "GEMINI_KEYS",
        "GOOGLE_GEMINI_API_KEYS",
        "GOOGLE_GEMINI_API_KEY",
        "GOOGLE_API_KEYS",
        "GOOGLE_API_KEY",
    ):
        value = os.environ.get(name, "").strip()
        if value:
            raw_values.append(value)
    for index in range(1, 21):
        for name in (
            f"GEMINI_API_KEY_{index}",
            f"GEMINI_API_KEYS_{index}",
            f"GOOGLE_GEMINI_API_KEY_{index}",
            f"GOOGLE_API_KEY_{index}",
        ):
            value = os.environ.get(name, "").strip()
            if value:
                raw_values.append(value)

    # This intentionally matches the last working loader behavior:
    # every non-empty comma/new-line/semicolon separated value is a key.
    keys: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        for part in re.split(r"[,\n\r;]+", raw_value):
            key = part.strip().strip('"').strip("'")
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
    return keys


def emergency_gemini_api_keys_from_any_env() -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for name, raw_value in os.environ.items():
        upper = name.upper()
        if "GEMINI" not in upper and upper not in {"GOOGLE_API_KEY", "GOOGLE_API_KEYS"}:
            continue
        for part in re.split(r"[,\n\r;]+", raw_value or ""):
            key = part.strip().strip('"').strip("'").strip()
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
    return keys


GEMINI_API_KEYS = configured_gemini_api_keys()


def refresh_gemini_api_keys_from_env() -> None:
    global GEMINI_API_KEYS
    GEMINI_API_KEYS = configured_gemini_api_keys()
    if not GEMINI_API_KEYS:
        GEMINI_API_KEYS = emergency_gemini_api_keys_from_any_env()


def gemini_env_parts_count() -> int:
    count = 0
    for name, value in os.environ.items():
        upper = name.upper()
        if "GEMINI" in upper or upper in {"GOOGLE_API_KEY", "GOOGLE_API_KEYS"}:
            count += len([part for part in re.split(r"[,\n\r;]+", value or "") if part.strip().strip('"').strip("'")])
    return count


def gemini_env_debug_summary() -> str:
    interesting: list[str] = []
    normal_loadable_count = len(configured_gemini_api_keys())
    emergency_loadable_count = len(emergency_gemini_api_keys_from_any_env())
    for name, value in sorted(os.environ.items()):
        upper = name.upper()
        if "GEMINI" in upper or upper in {"GOOGLE_API_KEY", "GOOGLE_API_KEYS"}:
            raw = value or ""
            split_count = len([part for part in re.split(r"[,\n\r;]+", raw) if part.strip().strip('"').strip("'")])
            token_count = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9._\-]{15,}", raw))
            ai_google_count = len(re.findall(r"AIza[0-9A-Za-z_\-]{20,}", raw))
            interesting.append(f"{name}: length={len(raw)}, split_parts={split_count}, normal_loader={normal_loadable_count}, emergency_loader={emergency_loadable_count}, active_keys={len(GEMINI_API_KEYS)}, token_patterns={token_count}, google_key_patterns={ai_google_count}")
    if not interesting:
        return "לא נמצאו בכלל משתני סביבה עם GEMINI/GOOGLE_API_KEY בזמן הריצה"
    return "; ".join(interesting[:30])


GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
GEMINI_FAST_MODEL = os.environ.get("GEMINI_FAST_MODEL", GEMINI_MODEL)
# Local key/cooldown checks do not call Gemini and do not use credits.
# Real network attempts below DO use one Gemini request each.
GEMINI_TRANSLATION_ATTEMPTS = int(os.environ.get("GEMINI_TRANSLATION_ATTEMPTS", "1"))
GEMINI_MAX_REAL_TRANSLATION_REQUESTS = int(os.environ.get("GEMINI_MAX_REAL_TRANSLATION_REQUESTS", "9"))
GEMINI_RETRY_WAIT_SECONDS = int(os.environ.get("GEMINI_RETRY_WAIT_SECONDS", "8"))
GEMINI_COOLDOWN_SECONDS = 10 * 60
GEMINI_MAX_PARALLEL_TRANSLATIONS = 2
TRANSLATE_QUOTED_POSTS = os.environ.get("TRANSLATE_QUOTED_POSTS", "0") == "1"
TRANSLATE_QUOTED_POSTS_IF_MAIN_TOO_SHORT = os.environ.get("TRANSLATE_QUOTED_POSTS_IF_MAIN_TOO_SHORT", "0") != "0"
MIN_MAIN_TEXT_CHARS_FOR_SKIP_QUOTE = int(os.environ.get("MIN_MAIN_TEXT_CHARS_FOR_SKIP_QUOTE", "45"))
# How many keys may be checked locally for cooldown/availability. This is free.
GEMINI_LOCAL_KEY_SWEEP_SIZE = int(os.environ.get("GEMINI_LOCAL_KEY_SWEEP_SIZE", "9"))
# How many keys may be tried with a real Gemini network request per single AI operation.
# Keep this low to avoid burning quota during outages.
GEMINI_MAX_KEYS_PER_OPERATION = int(os.environ.get("GEMINI_MAX_KEYS_PER_OPERATION", str(GEMINI_LOCAL_KEY_SWEEP_SIZE)))
# Credit-safe mode: do NOT spend Gemini on uncertain affiliation/filter checks.
# Gemini is used only after all local deterministic filters already approved a post for publishing.
AI_AFFILIATION_FALLBACK_ENABLED = os.environ.get("AI_AFFILIATION_FALLBACK_ENABLED", "0") == "1"

X_ACCOUNTS = [
    "FabrizioRomano",
    "David_Ornstein",
    "DiMarzio",
    "JacobsBen",
    "NicoSchira",
    "ffpolo",
    "AranchaMOBILE",
]

OPTIONAL_CONTROLLED_ACCOUNTS = [
    "Plettigoal",
    "MatteMoretto",
    "FabriceHawkins",
    "gerardromero",
    "MonfortCarlos",
    "JLSanchez78",
    "jfelixdiaz",
]

OPTIONAL_CONTROLLED_ACCOUNT_LABELS = {
    "Plettigoal": "פלוריאן פלטנברג",
    "MatteMoretto": "מתאו מורטו",
    "FabriceHawkins": "פבריס הוקינס",
    "gerardromero": "ג'ראד רומרו",
    "MonfortCarlos": "קרלוס מונפור",
    "JLSanchez78": "חוסה לואיס סאנצ'ס",
    "jfelixdiaz": "חוסה פליקס דיאס",
}

CONTROLLED_BASE_ACCOUNT_LABELS = {
    "FabrizioRomano": "פבריציו רומאנו",
    "David_Ornstein": "דיוויד אורנשטיין",
    "DiMarzio": "ג'אנלוקה די מארציו",
    "JacobsBen": "בן ג'ייקובס",
    "NicoSchira": "ניקולו שירה",
    "ffpolo": "פרננדו פולו",
    "AranchaMOBILE": "ארנצ'ה רודריגס",
}

PRIORITY_X_ACCOUNTS = {
    "FabrizioRomano",
    "David_Ornstein",
    "DiMarzio",
    "JacobsBen",
    "NicoSchira",
    "ffpolo",
    "AranchaMOBILE",
    "MatteMoretto",
    "FabriceHawkins",
    "gerardromero",
    "MonfortCarlos",
    "JLSanchez78",
    "jfelixdiaz",
    "Plettigoal",
}

ACCOUNT_DISPLAY_NAMES = {
    "FabrizioRomano": "פבריציו רומאנו",
    "David_Ornstein": "דיוויד אורנשטיין",
    "DiMarzio": "ג'אנלוקה די מארציו",
    "JacobsBen": "בן ג'ייקובס",
    "NicoSchira": "ניקולו שירה",
    "lauriewhitwell": "לורי וויטוול",
    "SamLee": "סם לי",
    "_pauljoyce": "פול ג'ויס",
    "Matt_Law_DT": "מאט לאו",
    "SimonJones_DM": "סיימון ג'ונס",
    "MatteMoretto": "מתאו מורטו",
    "ffpolo": "פרננדו פולו",
    "gerardromero": "ג'ראד רומרו",
    "AranchaMOBILE": "ארנצ'ה רודריגס",
    "JLSanchez78": "חוסה לואיס סאנצ'ס",
    "AlfredoPedulla": "אלפרדו פדולה",
    "Plettigoal": "פלוריאן פלטנברג",
    "cfbayern": "כריסטיאן פאלק",
    "FabriceHawkins": "פבריס הוקינס",
    "Tanziloic": "לואיק טנזי",
    "MonfortCarlos": "קרלוס מונפור",
    "jfelixdiaz": "חוסה פליקס דיאס",
    "Barca_Buzz": "בארסה באז",
    "MadridXtra": "מדריד אקסטרה",
    "iMiaSanMia": "מיה סן מיה",
    "Santi_J_FM": "סנטי אאונה",
    "AndyMitten": "אנדי מיטן",
}

TARGET_LANGUAGE = "he"
CHECK_EVERY_SECONDS = 15
HEARTBEAT_LOG_SECONDS = 5 * 60  # לוג חיים כל 5 דקות
HTTP_RETRIES = 3
REQUEST_TIMEOUT_SECONDS = 10
FEED_REQUEST_TIMEOUT_SECONDS = float(os.environ.get("FEED_REQUEST_TIMEOUT_SECONDS", "5"))
FEED_HTTP_RETRIES = int(os.environ.get("FEED_HTTP_RETRIES", "2"))
FEED_COLLECTION_TIMEOUT_SECONDS = float(os.environ.get("FEED_COLLECTION_TIMEOUT_SECONDS", "7"))
MAX_PARALLEL_ACCOUNT_CHECKS = int(os.environ.get("MAX_PARALLEL_ACCOUNT_CHECKS", "3"))
MAX_PARALLEL_FEED_CHECKS_PER_ACCOUNT = int(os.environ.get("MAX_PARALLEL_FEED_CHECKS_PER_ACCOUNT", "2"))
MAX_NEW_POSTS_PER_ACCOUNT_PER_CHECK = 20
MAX_POSTS_SENT_PER_CYCLE = 4
MAX_POST_AGE_SECONDS = 30 * 60
SEND_BACKLOG_FOR_NEW_ACCOUNTS = False
NIGHT_MODE_ENABLED = False
NIGHT_START_HOUR = 0
NIGHT_END_HOUR = 7
NIGHT_CHECK_EVERY_SECONDS = 20
NIGHT_MAX_PARALLEL_ACCOUNT_CHECKS = int(os.environ.get("NIGHT_MAX_PARALLEL_ACCOUNT_CHECKS", "3"))
NIGHT_MAX_PARALLEL_POST_SENDS = 4
SEND_LAST_POST_ON_FIRST_RUN = False
SEND_LAST_POST_ON_EVERY_START = False
FORCE_SEND_LATEST_FABRIZIO_ON_STARTUP = (
    os.environ.get(
        "FORCE_SEND_LATEST_FABRIZIO_ON_STARTUP",
        os.environ.get("SEND_FABRIZIO_LAST_MATCHING_POST_ON_STARTUP", "0"),
    )
    == "1"
)
FORCE_SEND_LATEST_FABRIZIO_EVERY_STARTUP = os.environ.get("FORCE_SEND_LATEST_FABRIZIO_EVERY_STARTUP", "0") == "1"
FORCED_FABRIZIO_STARTUP_STATE_KEY = "__forced_fabrizio_startup_posts__"
SEND_STARTUP_STATUS_MESSAGE = False
CONTROL_CHAT_ID = required_env_any(
    "NETO_SPORT_FOOTBALL_NEWS_CONTROL_TELEGRAM_CHAT_ID_PRIVATE",
    "NETO_SPORT_FOOTBALL_NEWS_TELEGRAM_CONTROL_CHAT_ID",
    "CONTROL_CHAT_ID",
)
CONTROL_STATE_FILE = "football_control_state.json"
CONTROL_POLL_SECONDS = 2
CONTROL_RESUME_BACKLOG_SECONDS = 10 * 60
CONTROL_SEND_PANEL_ON_STARTUP = True  # שולח כפתורי שליטה חדשים בכל הרצה של הבוט
CONTROL_CREATE_PANEL_IF_MISSING = os.environ.get("CONTROL_CREATE_PANEL_IF_MISSING", "0") == "1"
CONTROL_DELETE_WEBHOOK_ON_STARTUP = os.environ.get("CONTROL_DELETE_WEBHOOK_ON_STARTUP", "1") == "1"
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
SEND_VIDEO_FILES = os.environ.get("SEND_VIDEO_FILES", "0") == "1"
STATE_FILE = "football_x_to_telegram_state.json"
AI_DECISION_CACHE_FILE = os.environ.get("AI_DECISION_CACHE_FILE", "football_ai_decision_cache.json")
TRANSLATION_CACHE_FILE = "football_translation_cache.json"
RTL_MARK = "\u200f"
SIGNATURE_LINK = "https://t.me/neto_sport"
SIGNATURE_TEXT = "נטו ספורט.📝"

FEED_TEMPLATES = [
    "https://nitter.net/{username}/rss",
    "https://twiiit.com/{username}/rss",
    "https://lightbrd.com/{username}/rss",
    "https://rsshub.rssforever.com/twitter/user/{username}",
    "https://rsshub.app/twitter/user/{username}",
]
MAX_FEED_TEMPLATES_PER_ACCOUNT = int(os.environ.get("MAX_FEED_TEMPLATES_PER_ACCOUNT", "5"))
RSS_PRIMARY_SOURCE_COUNT = int(os.environ.get("RSS_PRIMARY_SOURCE_COUNT", "3"))
RSS_ENABLE_FALLBACK = os.environ.get("RSS_ENABLE_FALLBACK", "1") == "1"
RSS_FALLBACK_SOURCE_COUNT = int(os.environ.get("RSS_FALLBACK_SOURCE_COUNT", "2"))
LOGGED_FEED_ISSUE_KEYS: set[str] = set()
FEED_ISSUE_LOG_EVERY_SECONDS = int(os.environ.get("FEED_ISSUE_LOG_EVERY_SECONDS", str(10 * 60)))
FEED_ISSUE_LAST_LOGGED_AT: dict[str, float] = {}
FEED_SOURCE_MAX_PARALLEL = int(os.environ.get("FEED_SOURCE_MAX_PARALLEL", "2"))
FEED_SOURCE_SEMAPHORES: dict[str, BoundedSemaphore] = {}
FEED_SOURCE_SEMAPHORES_LOCK = Lock()

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
VIDEO_EXTENSIONS = (".mp4", ".mov", ".m3u8", ".webm", ".avi", ".mkv")

BARE_EXTERNAL_DOMAIN_RE = re.compile(
    r"(?<!@)\b(?:[A-Za-z0-9-]+\.)+(?:com|co\.uk|net|org|io|app|fr|it|es|de|co|uk|news|sport|football|tv|video)(?:/[^\s]*)?",
    re.IGNORECASE,
)

URL_RE = re.compile(
    r"https?://[^\s<>()\"']+|www\.[^\s<>()\"']+|(?<!@)\b(?:t\.co|x\.com|twitter\.com)/\S+",
    re.IGNORECASE,
)

EMOJI_RE = re.compile(r"[\U0001F1E6-\U0001F1FF\U0001F300-\U0001FAFF\u2600-\u27BF]")
TAG_FLAG_RE = re.compile(r"\U0001F3F4[\U000E0061-\U000E007A]+\U000E007F")
ARABIC_TEXT_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+")

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
    # This list catches normal, spaced and translated-looking country-code leftovers.
    # The flag emoji itself is preserved; only the extra letters are converted/removed.
    "TR": (r"(?<![א-תA-Za-z])טי\s*[-.־]?\s*אר(?![א-תA-Za-z])", r"(?<![א-תA-Za-z])טי\s*[-.־]?\s*ר(?![א-תA-Za-z])"),
    "GE": (r"(?<![א-תA-Za-z])ג׳?י\s*[-.־]?\s*אי(?![א-תA-Za-z])", r"(?<![א-תA-Za-z])גי\s*[-.־]?\s*אי(?![א-תA-Za-z])"),
    "IT": (r"(?<![א-תA-Za-z])אי\s*[-.־]?\s*טי(?![א-תA-Za-z])", r"(?<![א-תA-Za-z])איי\s*[-.־]?\s*טי(?![א-תA-Za-z])"),
    "ES": (r"(?<![א-תA-Za-z])אי\s*[-.־]?\s*אס(?![א-תA-Za-z])", r"(?<![א-תA-Za-z])איי\s*[-.־]?\s*אס(?![א-תA-Za-z])"),
    "FR": (r"(?<![א-תA-Za-z])אף\s*[-.־]?\s*אר(?![א-תA-Za-z])",),
    "DE": (r"(?<![א-תA-Za-z])די\s*[-.־]?\s*אי(?![א-תA-Za-z])", r"(?<![א-תA-Za-z])דה\s*[-.־]?\s*אי(?![א-תA-Za-z])"),
    "PT": (r"(?<![א-תA-Za-z])פי\s*[-.־]?\s*טי(?![א-תA-Za-z])",),
    "NL": (r"(?<![א-תA-Za-z])אן\s*[-.־]?\s*אל(?![א-תA-Za-z])", r"(?<![א-תA-Za-z])אנ\s*[-.־]?\s*אל(?![א-תA-Za-z])"),
    "BE": (r"(?<![א-תA-Za-z])בי\s*[-.־]?\s*אי(?![א-תA-Za-z])",),
    "BR": (r"(?<![א-תA-Za-z])בי\s*[-.־]?\s*אר(?![א-תA-Za-z])",),
    "AR": (r"(?<![א-תA-Za-z])איי?\s*[-.־]?\s*אר(?![א-תA-Za-z])",),
    "GB": (r"(?<![א-תA-Za-z])ג׳?י\s*[-.־]?\s*בי(?![א-תA-Za-z])",),
    "US": (r"(?<![א-תA-Za-z])יו\s*[-.־]?\s*אס(?![א-תA-Za-z])",),
    "MA": (r"(?<![א-תA-Za-z])אם\s*[-.־]?\s*איי?(?![א-תA-Za-z])",),
    "SN": (r"(?<![א-תA-Za-z])אס\s*[-.־]?\s*אן(?![א-תA-Za-z])",),
    "NG": (r"(?<![א-תA-Za-z])אן\s*[-.־]?\s*ג׳?י(?![א-תA-Za-z])",),
}


def normalize_country_flags(text: str) -> str:
    """Convert standalone ISO country codes like TR/GE/FR into flag emojis.

    RSS mirrors and Gemini sometimes leave only the two-letter country marker
    instead of the flag. This runs before translation and again after translation,
    including support for hidden RTL marks and spaced codes like T R / T-R / T.R.
    """
    text = unicodedata.normalize("NFKC", text or "")
    # NFKC converts styled/full-width Latin letters such as 𝐓𝐑 / ＴＲ into normal TR,
    # so the next regexes can remove/convert them while keeping the flag emoji.
    invisible = r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]*"
    separator = r"[\s\u00a0._/\-־]*"

    for code, flag in COUNTRY_CODE_FLAGS.items():
        first, second = re.escape(code[0]), re.escape(code[1])
        first_regional = chr(0x1F1E6 + ord(code[0]) - ord("A"))
        second_regional = chr(0x1F1E6 + ord(code[1]) - ord("A"))
        text = re.sub(rf"{re.escape(first_regional)}\s+{re.escape(second_regional)}", flag, text)
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
        text = re.sub(rf"{re.escape(flag)}\s*([🚨⚠️🔴🟡🟢]+)\s*{re.escape(flag)}", rf"{flag} \1", text)
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
    # Strong Hebrew/transliterated podcast spellings and common RSS/Gemini distortions.
    r"פוד\s*קאסט",
    r"פודקסט",
    r"פודקאסטים",
    r"פודקראסט",
    r"פוד\s*קראסט",
    r"פרקקאסט",
    r"פרקאסט",
    r"פוד\s+חדש",
    r"פודק\s+חדש",
    r"פרק\s+של\s+הפודקאסט",
    r"בפוד",
    r"בפודקאסט",
    r"בפודקסט",
    r"בפודקראסט",
    r"on\s+the\s+pod(?:cast)?\b",
    r"new\s+pod(?:cast)?\b",
    r"pod(?:cast)?\s+episode",
    r"\bin\s+case\s+you\s+missed\b",
    r"\bICYMI\b",
    r"\bexclusive\s+with\b",
    r"\binterview\s+with\b",
    r"\bfull\s+interview\b",
    r"\bahead\s+of\s+(?:the\s+)?(?:world\s+cup|euro|euros|copa\s+america|afcon)\s+campaign\b",
    r"\blive\s+(?:show|stream|broadcast|watchalong)\b",
    r"\bwatch\s+live\b",
    r"\bbroadcast\b",
    r"\bstreaming\b",
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
    "NicoSchira": "ניקולו שירה",
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
    "jfelixdiaz": "חוסה פליקס דיאס",
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
        "ellarguero": "אל לרגרו",
    }
)

ATTRIBUTION_HANDLE_REPLACEMENTS = {
    "ellarguero": "אל לרגרו",
    "ElLarguero": "אל לרגרו",
    "partidazocope": "פרטידאסו קופה",
    "COPE": "קופה",
    "diarioas": "אס",
    "marca": "מארקה",
    "relevo": "רלבו",
    "TheAthleticFC": "דה אתלטיק",
    "SkySports": "סקיי ספורטס",
    "SkySportDE": "סקיי ספורט גרמניה",
}

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
    "AranchaMOBILE": ["Arancha Rodríguez", "Arancha Rodriguez", "ארנצ'ה רודריגס", "ארנצ'ה רודריגז"],
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
    "breakthrough": "התפתחות משמעותית",
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
    "in the running": "בין המועמדים",
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
    "Brighton & Hove Albion": "ברייטון",
    "Brighton and Hove Albion": "ברייטון",
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
    "Como": "קומו",
    "COMO": "קומו",
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



# Extra club abbreviations / aliases. These help both filtering and Hebrew output.
# Important: FCB can mean Barcelona or Bayern, so it is handled mainly by the allow-list matcher,
# while more explicit forms such as FC Bayern / Barça are preferred for translation.
TEAM_REPLACEMENTS.update(
    {
        "MUFC": "מנצ'סטר יונייטד",
        "MCFC": "מנצ'סטר סיטי",
        "LFC": "ליברפול",
        "CFC": "צ'לסי",
        "AFC": "ארסנל",
        "THFC": "טוטנהאם",
        "NUFC": "ניוקאסל",
        "AVFC": "אסטון וילה",
        "WHUFC": "ווסטהאם",
        "BHAFC": "ברייטון",
        "EFC": "אברטון",
        "BVB": "בורוסיה דורטמונד",
        "B04": "באייר לברקוזן",
        "RBL": "רד בול לייפציג",
        "SGE": "איינטרכט פרנקפורט",
        "FC Bayern": "באיירן מינכן",
        "FCBayern": "באיירן מינכן",
        "RMA": "ריאל מדריד",
        "Atleti": "אתלטיקו מדריד",
        "ATM": "אתלטיקו מדריד",
        "Athletic Bilbao": "אתלטיק בילבאו",
        "Real Sociedad": "ריאל סוסיאדד",
        "La Real": "ריאל סוסיאדד",
        "Villarreal CF": "ויאריאל",
        "ACM": "מילאן",
        "A.C. Milan": "מילאן",
        "Internazionale": "אינטר",
        "Inter Miami CF": "אינטר מיאמי",
        "OM": "מארסיי",
        "Olympique Marseille": "מארסיי",
        "Olympique Lyon": "ליון",
        "OL": "ליון",
        "LOSC": "ליל",
        "RC Lens": "לאנס",
        "RCL": "לאנס",
        "AS Monaco": "מונאקו",
        "ASM": "מונאקו",
        "SL Benfica": "בנפיקה",
        "Benfica Lisbon": "בנפיקה ליסבון",
        "Sporting CP": "ספורטינג ליסבון",
        "Sporting Lisbon": "ספורטינג ליסבון",
        "PSV Eindhoven": "פ.ס.וו איינדהובן",
        "PSV": "פ.ס.וו",
        "CR Flamengo": "פלמנגו",
        "Flamengo": "פלמנגו",
        "Palmeiras": "פלמייראס",
        "Sao Paulo": "סאו פאולו",
        "São Paulo": "סאו פאולו",
        "Boca Juniors": "בוקה ג'וניורס",
        "River Plate": "ריבר פלייט",
        "Al Nassr": "אל-נאסר",
        "Al-Nassr": "אל-נאסר",
        "Al Hilal": "אל-הילאל",
        "Al-Hilal": "אל-הילאל",
        "Al Ahli": "אל-אהלי",
        "Al-Ahli": "אל-אהלי",
        "Galatasaray": "גלאטסראיי",
        "Fenerbahce": "פנרבחצ'ה",
        "Fenerbahçe": "פנרבחצ'ה",
        "Club Brugge": "קלאב ברוז'",
        "Red Star Belgrade": "הכוכב האדום",
        "Crvena Zvezda": "הכוכב האדום",
        "Botafogo": "בוטאפוגו",
    }
)

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

PLAYER_REPLACEMENTS.update(
    {
        "Ruben Amorim": "רובן אמורים",
        "Rúben Amorim": "רובן אמורים",
        "Amorim": "אמורים",
        "Matthias Jaissle": "מתיאס יאייסלה",
        "Jaissle": "יאייסלה",
        "Alvaro Arbeloa": "אלווארו ארבלואה",
        "Álvaro Arbeloa": "אלווארו ארבלואה",
        "Arbeloa": "ארבלואה",
    }
)

HEBREW_FINAL_FIXES = {
    "צ'לסי בוחנת את האפשרות למנות את צ'אבי אלונסו למאמנה הבא של ריאל סוסיאדד": "צ'לסי בוחנת את האפשרות למנות את צ'אבי אלונסו למאמנה הבא",
    "למאמנה הבא של ריאל סוסיאדד": "למאמנה הבא",
    "צאבי אלונסו": "צ'אבי אלונסו",
    "צ׳אבי אלונסו": "צ'אבי אלונסו",
    "קסאבי אלונסו": "צ'אבי אלונסו",
    "לקיפה": "לאקיפ",
    "ל'אקיפה": "לאקיפ",
    "ל'אקיפ": "לאקיפ",
    "ניקולה שירה": "ניקולו שירה",
    "ניקולו שירה": "ניקולו שירה",
    "ניקולו סקירה": "ניקולו שירה",
    "ניקולה סקירה": "ניקולו שירה",
    "ניקולבה סקירה": "ניקולו שירה",
    "ק.ו.מ.": "קומו",
    "ק ו מ": "קומו",
    "ק. ו. מ.": "קומו",
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
    last_error: Exception | None = None
    for attempt in range(1, max(1, FEED_HTTP_RETRIES) + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            if attempt < max(1, FEED_HTTP_RETRIES):
                time.sleep(0.4)
    raise RuntimeError(f"RSS GET failed: {url}. Last error: {last_error}")


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


def feed_source_semaphore(source_name: str) -> BoundedSemaphore:
    with FEED_SOURCE_SEMAPHORES_LOCK:
        semaphore = FEED_SOURCE_SEMAPHORES.get(source_name)
        if semaphore is None:
            semaphore = BoundedSemaphore(max(1, FEED_SOURCE_MAX_PARALLEL))
            FEED_SOURCE_SEMAPHORES[source_name] = semaphore
        return semaphore


def sanitize_rss_xml(xml_bytes: bytes) -> bytes:
    text = xml_bytes.decode("utf-8", errors="replace").lstrip("\ufeff")
    first_xml = min((pos for pos in (text.find("<?xml"), text.find("<rss"), text.find("<feed")) if pos >= 0), default=-1)
    if first_xml > 0:
        text = text[first_xml:]
    # Some RSS mirrors occasionally emit XML-invalid control characters.
    # Removing them is free and avoids a noisy ParseError loop. They can also
    # leave bare ampersands in tweet text, which breaks XML parsing even though
    # the rest of the feed is usable.
    text = re.sub(r"[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD]", "", text)
    text = re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#[0-9]+|#x[0-9A-Fa-f]+);)", "&amp;", text)
    text = text.lstrip()
    return text.encode("utf-8")


def parse_posts(username: str, xml_bytes: bytes, source_name: str) -> list[Post]:
    try:
        root = ET.fromstring(xml_bytes.lstrip())
    except ET.ParseError as first_exc:
        try:
            root = ET.fromstring(sanitize_rss_xml(xml_bytes))
        except ET.ParseError as second_exc:
            raise ET.ParseError(f"RSS XML parse failed after cleanup: {second_exc}; original: {first_exc}") from second_exc
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
    source_name = feed_source_name(template)
    with feed_source_semaphore(source_name):
        return parse_posts(username, http_get_feed(url), source_name)


def active_feed_templates() -> list[str]:
    if MAX_FEED_TEMPLATES_PER_ACCOUNT <= 0:
        return FEED_TEMPLATES
    return FEED_TEMPLATES[: max(1, min(len(FEED_TEMPLATES), MAX_FEED_TEMPLATES_PER_ACCOUNT))]


def short_error(exc: Exception, limit: int = 180) -> str:
    text = str(exc) or repr(exc)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def log_feed_issue(username: str, message: str, *args: Any) -> None:
    formatted = message % args if args else message
    normalized = re.sub(r"\d+\.\d+s|\d+s|line \d+, column \d+", "", formatted)
    key = hashlib.sha1(f"{username}|{normalized}".encode("utf-8", errors="ignore")).hexdigest()
    now = time.time()
    last_logged = FEED_ISSUE_LAST_LOGGED_AT.get(key, 0.0)
    if now - last_logged < FEED_ISSUE_LOG_EVERY_SECONDS:
        return
    FEED_ISSUE_LAST_LOGGED_AT[key] = now
    LOGGED_FEED_ISSUE_KEYS.add(key)
    if len(FEED_ISSUE_LAST_LOGGED_AT) > 1000:
        FEED_ISSUE_LAST_LOGGED_AT.clear()
        LOGGED_FEED_ISSUE_KEYS.clear()
    logging.warning(message, *args)


def collect_posts_from_feed_templates(username: str, feed_templates: list[str]) -> tuple[list[Post], list[str], list[str]]:
    all_posts: dict[str, Post] = {}
    feed_errors: list[str] = []
    timed_out_sources: list[str] = []
    if not feed_templates:
        return [], [], []
    executor = ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_FEED_CHECKS_PER_ACCOUNT, len(feed_templates)))
    futures = {executor.submit(fetch_feed, username, template): template for template in feed_templates}
    try:
        for future in as_completed(futures, timeout=FEED_COLLECTION_TIMEOUT_SECONDS):
            template = futures[future]
            source_name = feed_source_name(template)
            try:
                for post in future.result():
                    all_posts.setdefault(post.post_id, post)
            except Exception as exc:
                feed_errors.append(f"{source_name}: {type(exc).__name__}: {short_error(exc)}")
                continue
    except FuturesTimeoutError:
        timed_out_sources = [feed_source_name(template) for future, template in futures.items() if not future.done()]
    finally:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
    posts = list(all_posts.values())
    posts.sort(key=lambda post: post.published_ts, reverse=True)
    return posts, feed_errors, timed_out_sources


def fetch_posts(username: str) -> list[Post]:
    feed_templates = active_feed_templates()
    primary_count = max(1, min(len(feed_templates), RSS_PRIMARY_SOURCE_COUNT))
    primary_templates = feed_templates[:primary_count]
    fallback_templates = feed_templates[primary_count:] if RSS_ENABLE_FALLBACK else []
    if RSS_FALLBACK_SOURCE_COUNT > 0:
        fallback_templates = fallback_templates[:RSS_FALLBACK_SOURCE_COUNT]
    posts, feed_errors, timed_out_sources = collect_posts_from_feed_templates(username, primary_templates)
    if posts:
        return posts

    fallback_errors: list[str] = []
    fallback_timeouts: list[str] = []
    if fallback_templates:
        fallback_posts, fallback_errors, fallback_timeouts = collect_posts_from_feed_templates(username, fallback_templates)
        if fallback_posts:
            primary_issue_parts = []
            if feed_errors:
                primary_issue_parts.append("errors: " + "; ".join(feed_errors[:4]))
            if timed_out_sources:
                primary_issue_parts.append("timeouts: " + ", ".join(timed_out_sources[:4]))
            logging.info(
                "RSS fallback used for @%s: primary source failed, fallback found %s posts via %s",
                username,
                len(fallback_posts),
                fallback_posts[0].source_name,
            )
            if primary_issue_parts:
                logging.debug("RSS fallback details for @%s: %s", username, " | ".join(primary_issue_parts))
            return fallback_posts

    if not posts:
        checked_templates = primary_templates + fallback_templates
        checked_sources = ", ".join(feed_source_name(template) for template in checked_templates)
        all_errors = feed_errors + fallback_errors
        all_timeouts = timed_out_sources + fallback_timeouts
        issue_parts = []
        if all_errors:
            issue_parts.append("errors: " + "; ".join(all_errors[:8]))
        if all_timeouts:
            issue_parts.append("timeouts: " + ", ".join(all_timeouts[:8]))
        issue_text = " | ".join(issue_parts) or "no items returned"
        logging.debug(
            "RSS details for @%s: checked sources=%s | %s",
            username,
            checked_sources,
            issue_text,
        )
        log_feed_issue(
            username,
            "RSS: no posts found for @%s after checking %s sources in %.1fs. Sources: %s | %s",
            username,
            len(checked_templates),
            FEED_COLLECTION_TIMEOUT_SECONDS,
            checked_sources,
            issue_text,
        )
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
    accounts = active_x_accounts()
    priority = [username for username in accounts if username in PRIORITY_X_ACCOUNTS]
    regular = [username for username in accounts if username not in PRIORITY_X_ACCOUNTS]
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
    accounts = active_x_accounts()
    results: dict[str, list[Post]] = {username: [] for username in accounts}
    workers = min(current_max_parallel_account_checks(), max(1, len(accounts)))
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


def enabled_optional_accounts_from_state(state: dict[str, Any] | None = None) -> list[str]:
    state = state or load_control_state()
    raw_accounts = state.get("enabled_optional_accounts", [])
    if not isinstance(raw_accounts, list):
        raw_accounts = []
    allowed = set(OPTIONAL_CONTROLLED_ACCOUNTS)
    return [username for username in OPTIONAL_CONTROLLED_ACCOUNTS if username in allowed and username in raw_accounts]


def disabled_base_accounts_from_state(state: dict[str, Any] | None = None) -> list[str]:
    state = state or load_control_state()
    raw_accounts = state.get("disabled_base_accounts", [])
    if not isinstance(raw_accounts, list):
        raw_accounts = []
    allowed = set(X_ACCOUNTS)
    return [username for username in X_ACCOUNTS if username in allowed and username in raw_accounts]


def active_x_accounts() -> list[str]:
    disabled_base = set(disabled_base_accounts_from_state())
    accounts = [username for username in X_ACCOUNTS if username not in disabled_base]
    for username in enabled_optional_accounts_from_state():
        if username not in accounts:
            accounts.append(username)
    return accounts


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
    state = load_control_state()
    disabled_base = set(disabled_base_accounts_from_state(state))
    enabled_optional = set(enabled_optional_accounts_from_state(state))
    keyboard: list[list[dict[str, str]]] = []
    if paused:
        keyboard.append([{"text": "להפעיל את הבוט", "callback_data": "football_bot_on"}])
    else:
        keyboard.append([{"text": "לכבות את הבוט", "callback_data": "football_bot_off"}])
    for username in X_ACCOUNTS:
        label = CONTROLLED_BASE_ACCOUNT_LABELS.get(username, ACCOUNT_DISPLAY_NAMES.get(username, username))
        status = "כבוי" if username in disabled_base else "פעיל"
        keyboard.append([{"text": f"{label}: {status}", "callback_data": f"football_base_account:{username}"}])
    for username in OPTIONAL_CONTROLLED_ACCOUNTS:
        label = OPTIONAL_CONTROLLED_ACCOUNT_LABELS.get(username, username)
        status = "פעיל" if username in enabled_optional else "כבוי"
        keyboard.append([{"text": f"{label}: {status}", "callback_data": f"football_account:{username}"}])
    return {"inline_keyboard": keyboard}


def send_control_panel(paused: bool, action_done: str = "", force_new: bool = False) -> None:
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
    # Startup should create a fresh control panel every run, like the old behavior.
    # Button clicks still try to edit the active panel to avoid unnecessary spam.
    if message_id and not force_new:
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
    if message.get("message_id"):
        save_control_state(control_message_id=message.get("message_id"))
    data = str(callback.get("data", ""))
    if CONTROL_CHAT_ID and chat_id != CONTROL_CHAT_ID:
        if callback_id:
            answer_control_callback(callback_id, "אין הרשאה לערוץ הזה")
        return
    if data == "football_bot_off":
        save_control_state(True)
        logging.info("Control panel: bot paused by button click.")
        if callback_id:
            answer_control_callback(callback_id, "הבוט כובה")
        send_control_panel(True, "הפעולה בוצעה בהצלחה: הבוט כובה.")
    elif data == "football_bot_on":
        save_control_state(False, resume_min_ts=time.time() - CONTROL_RESUME_BACKLOG_SECONDS)
        logging.info("Control panel: bot resumed by button click.")
        if callback_id:
            answer_control_callback(callback_id, "הבוט הופעל")
        send_control_panel(False, "\u05d4\u05e4\u05e2\u05d5\u05dc\u05d4 \u05d1\u05d5\u05e6\u05e2\u05d4 \u05d1\u05d4\u05e6\u05dc\u05d7\u05d4: \u05d4\u05d1\u05d5\u05d8 \u05d4\u05d5\u05e4\u05e2\u05dc.")
    elif data.startswith("football_account:"):
        username = data.split(":", 1)[1]
        if username not in OPTIONAL_CONTROLLED_ACCOUNTS:
            if callback_id:
                answer_control_callback(callback_id, "כתב לא מוכר")
            return
        state = load_control_state()
        enabled = set(enabled_optional_accounts_from_state(state))
        label = OPTIONAL_CONTROLLED_ACCOUNT_LABELS.get(username, username)
        if username in enabled:
            enabled.remove(username)
            action_text = f"{label} כובה"
            logging.info("לוח שליטה: הכתב האופציונלי @%s כובה בכפתור ולא ייסרק.", username)
        else:
            enabled.add(username)
            action_text = f"{label} הופעל"
            logging.info("לוח שליטה: הכתב האופציונלי @%s הופעל בכפתור וייכנס לסריקה.", username)
        save_control_state(enabled_optional_accounts=[account for account in OPTIONAL_CONTROLLED_ACCOUNTS if account in enabled])
        if callback_id:
            answer_control_callback(callback_id, action_text)
        send_control_panel(is_control_paused(), f"הפעולה בוצעה בהצלחה: {action_text}.")
    elif data.startswith("football_base_account:"):
        username = data.split(":", 1)[1]
        if username not in X_ACCOUNTS:
            if callback_id:
                answer_control_callback(callback_id, "כתב לא מוכר")
            return
        state = load_control_state()
        disabled = set(disabled_base_accounts_from_state(state))
        label = CONTROLLED_BASE_ACCOUNT_LABELS.get(username, ACCOUNT_DISPLAY_NAMES.get(username, username))
        if username in disabled:
            disabled.remove(username)
            action_text = f"{label} הופעל"
            logging.info("לוח שליטה: הכתב @%s הופעל מחדש בכפתור.", username)
        else:
            disabled.add(username)
            action_text = f"{label} כובה"
            logging.info("לוח שליטה: הכתב @%s כובה בכפתור ולא ייסרק עד להפעלה מחדש.", username)
        save_control_state(disabled_base_accounts=[account for account in X_ACCOUNTS if account in disabled])
        if callback_id:
            answer_control_callback(callback_id, action_text)
        send_control_panel(is_control_paused(), f"הפעולה בוצעה בהצלחה: {action_text}.")


def process_channel_post_update(update: dict[str, Any]) -> None:
    message = update.get("channel_post") or {}
    if not isinstance(message, dict):
        return
    chat = message.get("chat", {}) or {}
    chat_id = str(chat.get("id", ""))
    if chat_id not in set(TELEGRAM_CHAT_IDS):
        return
    text = str(message.get("text") or message.get("caption") or "").strip()
    if not text:
        return
    try:
        state = load_state()
        message_id = str(message.get("message_id", ""))
        remember_channel_news_text(text, state, message_id=message_id, source="channel")
        save_state(state)
        logging.debug("Channel duplicate memory: remembered channel post %s for 12h.", message_id or "unknown")
    except Exception as exc:
        logging.debug("Channel duplicate memory failed: %s", exc)


def is_getupdates_conflict(error: Exception) -> bool:
    error_text = str(error).lower()
    return "409" in error_text and "getupdates" in error_text


def control_saved_offset() -> int:
    try:
        return max(0, int(load_control_state().get("control_update_offset", 0)))
    except Exception:
        return 0


def delete_control_webhook_if_needed() -> None:
    # getUpdates will not receive button clicks if a Telegram webhook is still attached.
    # This call does not send messages and does not use Gemini/AI credits.
    if not CONTROL_DELETE_WEBHOOK_ON_STARTUP:
        return
    try:
        telegram_api("deleteWebhook", {"drop_pending_updates": True}, max_attempts=1)
        logging.debug("Control panel: webhook cleared, polling callbacks is active.")
    except Exception as exc:
        logging.debug("Control panel: could not clear webhook before polling: %s", exc)


def ensure_control_panel_once_if_requested() -> None:
    # Default is false, so the old button can keep working without sending a new one.
    # Set CONTROL_CREATE_PANEL_IF_MISSING=1 only if you want the bot to create one panel when no saved id exists.
    if not CONTROL_CREATE_PANEL_IF_MISSING:
        return
    state = load_control_state()
    if state.get("control_message_id"):
        return
    send_control_panel(is_control_paused())


def control_loop() -> None:
    if not CONTROL_CHAT_ID:
        return
    delete_control_webhook_if_needed()
    offset = control_saved_offset()
    last_conflict_cleanup = 0.0
    if CONTROL_SEND_PANEL_ON_STARTUP:
        try:
            send_control_panel(is_control_paused(), force_new=True)
        except Exception as exc:
            logging.debug("Control panel startup failed: %s", exc)
    else:
        try:
            ensure_control_panel_once_if_requested()
        except Exception as exc:
            logging.debug("Control panel create-if-missing failed: %s", exc)
        logging.debug("Control panel startup send is disabled; existing button callbacks will still work.")
    while True:
        try:
            response = telegram_api(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 20,
                    "allowed_updates": ["callback_query", "channel_post"],
                },
            )
            for update in response.get("result", []):
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                save_control_state(control_update_offset=offset)
                process_control_update(update)
                process_channel_post_update(update)
        except Exception as exc:
            if is_getupdates_conflict(exc):
                logging.debug("Control panel getUpdates conflict; trying webhook cleanup.")
                now = time.time()
                if now - last_conflict_cleanup > 30:
                    last_conflict_cleanup = now
                    try:
                        telegram_api("deleteWebhook", {"drop_pending_updates": True}, max_attempts=1)
                    except Exception as cleanup_exc:
                        logging.warning("Control panel conflict cleanup failed: %s", cleanup_exc)
                time.sleep(CONTROL_POLL_SECONDS)
                continue
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
    normalized_text = normalize_country_flags(raw_text)
    lowered = normalized_text.lower()
    has_podcast_phrase = any(re.search(pattern, normalized_text, re.IGNORECASE) for pattern in PODCAST_BLOCK_PATTERNS)
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
            "פודקסט",
            "פודקראסט",
            "פרקאסט",
            "פרקקאסט",
            "האזינו",
            "פרק מלא",
            "הפרק המלא",
        )
    )
    # Podcast/longform posts should be blocked even when the RSS text does not expose
    # the external link. Previously we required a visible link, so posts such as
    # "פרקאסט חדש ..." could slip through.
    return has_podcast_phrase or has_podcast_domain or has_longform_youtube_hint


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


MATCH_RESULT_OR_ENGAGEMENT_PATTERNS = (
    r"\b(?:wins?|won|beat|beats|defeated|defeats|victory|opening game|opener|matchday|full time|full-time|FT|final score|player of the match|man of the match|MOTM|who was your)\b",
    r"מנצח(?:ת|ים)?|ניצח(?:ה|ו)?|גבר(?:ה|ו)?|הביס(?:ה|ו)?|תוצאה|משחק הפתיחה|מחזור|שריקת סיום|שחקן המצטיין|השחקן המצטיין|איש המשחק|מי היה",
)

MATCH_NEWS_RESCUE_PATTERNS = (
    r"\b(?:injury|injured|suspended|red card ban|ban|appeal|disciplinary|called up|squad|transfer|contract|official|signed|agreement|medical)\b",
    r"פציעה|נפצע|פצוע|השעיה|מורחק|ערעור|זומן|סגל|העברה|חוזה|רשמי|חתם|סיכום|בדיקות רפואיות",
)


LINEUP_OR_SELECTION_BLOCK_PATTERNS = (
    r"\b(?:line-?ups?|starting XI|starting eleven|confirmed XI|team news|starts?\s+(?:for|against|vs\.?|v\.?)|starting\s+(?:for|against|vs\.?|v\.?|XI|eleven)|benched|on the bench)\b",
    r"הרכבים|ההרכב הפותח|פותח(?:ת)? בהרכב|יפתח בהרכב|תפתח בהרכב|יעלה בהרכב|בספסל|על הספסל|מסופסל",
)

LINEUP_OR_SELECTION_CONTEXT_PATTERNS = (
    r"\b(?:today|tonight|opener|debut|match(?:day)?|game|fixture|vs\.?|v\.?|against|world cup opener|club world cup|kick-?off)\b",
    r"היום|הלילה|בכורה|משחק|מחזור|נגד|מול|גביע העולם|מונדיאל|שריקת פתיחה",
)

LINEUP_OR_SELECTION_CONTEXTUAL_PATTERNS = (
    r"\b(?:not in the squad|out of the squad|left out of the squad|included in the squad|match squad|squad list|available|unavailable|not available)\b",
    r"לא בסגל|מחוץ לסגל|נכלל בסגל|סגל למשחק|רשימת הסגל|זמין|לא זמין",
)


def is_lineup_or_selection_post(post: Post) -> bool:
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    if not cleaned:
        return False
    if _matches_any(LINEUP_OR_SELECTION_BLOCK_PATTERNS, cleaned):
        return True
    return _matches_any(LINEUP_OR_SELECTION_CONTEXTUAL_PATTERNS, cleaned) and _matches_any(LINEUP_OR_SELECTION_CONTEXT_PATTERNS, cleaned)


def is_match_result_or_engagement_post(post: Post) -> bool:
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    if not cleaned:
        return False
    if _matches_any(MATCH_NEWS_RESCUE_PATTERNS, cleaned):
        return False
    has_match_result = _matches_any(MATCH_RESULT_OR_ENGAGEMENT_PATTERNS, cleaned)
    has_score = bool(re.search(r"\b\d+\s*[-:]\s*\d+\b", cleaned))
    return bool(has_match_result or has_score)


def filtered_post_text_preview(post: Post, limit: int = 260) -> str:
    raw_text = html.unescape("\n".join([post.text or "", post.quoted_text or ""]))
    cleaned = clean_for_ai_translation(raw_text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return trim(cleaned, limit) if cleaned else "(טקסט ריק)"



# Early quote/interview rescue: keeps newsworthy "X said/told" reports when they
# clearly include a top-5-league/big club plus transfer/future intent. This fixes
# cases like a family/agent/player quote about wanting/being able to move to Napoli.
EARLY_MAJOR_CLUB_CONTEXT_PATTERNS = (
    r"\b(?:Manchester United|Man United|Man Utd|Manchester City|Man City|Liverpool|Arsenal|Chelsea|Tottenham|Spurs|Newcastle|Aston Villa|West Ham|Brighton|Everton|Leicester|Crystal Palace|Wolves|Fulham|Bournemouth|Brentford|Nottingham Forest|Leeds|Sunderland|Burnley)\b",
    r"\b(?:Real Madrid|Barcelona|Barca|Barça|Atletico Madrid|Atlético Madrid|Sevilla|Valencia|Villarreal|Real Sociedad|Athletic Club|Athletic Bilbao|Real Betis|Girona|Celta Vigo|Getafe|Osasuna|Mallorca|Rayo Vallecano|Alaves|Espanyol|Levante|Leganes|Granada|Las Palmas|Valladolid)\b",
    r"\b(?:Juventus|Inter Milan|Inter|AC Milan|Milan|Napoli|Roma|Lazio|Atalanta|Fiorentina|Torino|Bologna|Genoa|Cagliari|Como|Lecce|Empoli|Udinese|Sassuolo|Verona|Parma|Pisa|Cremonese)\b",
    r"\b(?:Bayern Munich|Bayern|Borussia Dortmund|Dortmund|Bayer Leverkusen|Leverkusen|Eintracht Frankfurt|Mainz|Freiburg|Augsburg|Wolfsburg|Union Berlin|Hoffenheim|Werder Bremen|Hamburg|Koln|Köln|St Pauli|Heidenheim|Bochum)\b",
    r"\b(?:PSG|Paris Saint-Germain|Marseille|Monaco|Lyon|Lille|Nice|Rennes|Lens|Strasbourg|Brest|Nantes|Toulouse|Montpellier|Reims|Metz|Auxerre|Angers|Lorient|Paris FC)\b",
    r"ריאל מדריד|ברצלונה|בארסה|אתלטיקו מדריד|מנצ'סטר יונייטד|מנצ'סטר סיטי|ליברפול|ארסנל|צ'לסי|טוטנהאם|ניוקאסל|אסטון וילה|ווסטהאם|ברייטון|אברטון|לסטר|קריסטל פאלאס|וולבס|פולהאם|בורנמות|ברנטפורד|נוטינגהאם|לידס|סנדרלנד|ברנלי",
    r"יובנטוס|אינטר|מילאן|נאפולי|רומא|לאציו|אטאלנטה|פיורנטינה|טורינו|בולוניה|גנואה|קליארי|קומו|לצ'ה|אמפולי|אודינזה|ססואולו|ורונה|פארמה|פיזה|קרמונזה",
    r"באיירן|דורטמונד|לברקוזן|פרנקפורט|מיינץ|פרייבורג|אוגסבורג|וולפסבורג|אוניון ברלין|הופנהיים|ורדר ברמן|המבורג|קלן|סט פאולי|בוכום",
    r"פ\.ס\.ז|פריז סן ז'רמן|מארסיי|מונאקו|ליון|ליל|ניס|רן|לאנס|שטרסבורג|ברסט|נאנט|טולוז|מונפלייה|ריימס|מץ|אוקזר|אנז'ה|לוריין",
)

# A quote/interview is rescued only when it has a REAL transfer/contract mechanism.
# Do NOT rescue ordinary post-match interviews, admiration, vague interest, or "player ideas".
EARLY_TRANSFER_FUTURE_NEWS_PATTERNS = (
    r"\b(?:wants? to join|would like to join|dreams? of joining|keen to join|open to joining|ready to join|could join|could return|wants? to return|would return|return to|back to|wants? to leave|leave|leaving|transfer|move|sign|joining|proposal|offer|bid|talks|negotiations|release clause|loan|option to buy|buy option|purchase option|agreement|medical|contract|deal)\b",
    r'רוצה\s+לעבור|רוצה\s+להצטרף|מעוניין\s+לעבור|מעוניין\s+להצטרף|חולם\s+לעבור|חולם\s+להצטרף|יכול\s+לעבור|יכול\s+להצטרף|יכול\s+לחזור|רוצה\s+לחזור|עשוי\s+לחזור|חזרה\s+ל|לחזור\s+ל|יעזוב|לעזוב|מעבר|העברה|חתימה|הצעה|שיחות|מו"מ|סעיף\s+שחרור|השאלה|אופציית\s+רכישה|אופציית\s+הקנייה|לא\s+הפעיל(?:ה|ו)?\s+את\s+אופציית\s+הרכישה|סיכום|בדיקות\s+רפואיות|חוזה|עסקה',
)

POST_MATCH_INTERVIEW_NOISE_PATTERNS = (
    r"\b(?:post[- ]match|after the game|after the match|following the game|following the match|press conference|mixed zone|interview)\b",
    r"אחרי\s+המשחק|לאחר\s+המשחק|בסיום\s+המשחק|מסיבת\s+עיתונאים|ראיון|בראיון|דיבר\s+אחרי|נשאל\s+אחרי",
)

INTERVIEW_BLOCK_PATTERNS = (
    r"\b(?:interview|press conference|mixed zone|asked about|on\s+@[A-Za-z0-9_]{2,}|via\s+@[A-Za-z0-9_]{2,})\b",
    r"\b(?:speaking to|spoke to|told|tells|said to|says to)\s+(?:@[A-Za-z0-9_]{2,}|[A-Z][A-Za-z0-9_.-]{2,}(?:\s+[A-Z][A-Za-z0-9_.-]{2,}){0,3})\b",
    r"\b(?:on|via)\s+[A-Z][A-Za-z0-9_.-]{2,}(?:\s+[A-Z][A-Za-z0-9_.-]{2,}){0,3}\s*:",
    r"ראיון|בראיון|מסיבת\s+עיתונאים|אזור\s+מעורב|דיבר\s+עם|נשאל\s+על|נשאלה\s+על",
)


def is_interview_post(post: Post) -> bool:
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    if not cleaned:
        return False
    return _matches_any(INTERVIEW_BLOCK_PATTERNS, cleaned)


def has_real_transfer_context(cleaned: str) -> bool:
    if not cleaned:
        return False
    return any(re.search(pattern, cleaned, re.IGNORECASE) for pattern in EARLY_TRANSFER_FUTURE_NEWS_PATTERNS)

def is_post_match_interview_noise(cleaned: str) -> bool:
    if not cleaned:
        return False
    has_interview_noise = any(re.search(pattern, cleaned, re.IGNORECASE) for pattern in POST_MATCH_INTERVIEW_NOISE_PATTERNS)
    return bool(has_interview_noise and not has_real_transfer_context(cleaned))

def is_newsworthy_quote_or_interview_report(cleaned: str) -> bool:
    """Do not treat every quote/interview as social noise.

    If a top-5/big club is in the same report and the quote contains a clear
    transfer/future/return/interest signal, it is a news report and should pass
    to the football relevance filter.
    """
    if not cleaned:
        return False
    has_major_club = any(re.search(pattern, cleaned, re.IGNORECASE) for pattern in EARLY_MAJOR_CLUB_CONTEXT_PATTERNS)
    has_future_transfer_signal = has_real_transfer_context(cleaned)
    if has_major_club and has_future_transfer_signal:
        return True
    return False

def is_non_news_social_post(post: Post) -> bool:
    raw_text = html.unescape("\n".join([post.text or "", post.quoted_text or ""]))
    cleaned = clean_for_ai_translation(raw_text)
    lowered = cleaned.lower()
    if not cleaned:
        return True
    if is_clear_player_departure_post(post):
        return False

    if is_match_result_or_engagement_post(post):
        return True

    # Ordinary interviews/quotes after matches stay blocked unless they contain
    # a concrete transfer/contract mechanism such as bid, offer, loan, option,
    # clause, agreement, medical, wants to join/return/leave, etc.
    if is_post_match_interview_noise(cleaned):
        return True

    if is_newsworthy_quote_or_interview_report(cleaned):
        return False

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
        r"\breturn(?:s|ed|ing)?\s+to\b",
        r"\bwants?\s+to\s+(?:join|return|leave)\b",
        r"\bcould\s+(?:join|return|leave)\b",
        r"\bfuture\b",
        r"\bappointed\b",
        r"\bsacked\b",
        r"\binjury\b",
        r"\bsuspended\b",
        r"\bconfirmed\b",
        r"\bofficial\b",
        r"\bcalled\s+up\b",
        r"\bsquad\b",
        r"\bnational\s+team\b",
        r"הושג|סוכם|חתם|יחתום|מצטרף|יעבור|העברה|השאלה|חוזה|רשמי|בלעדי|פציעה|מונה|פוטר|יכול לחזור|רוצה לחזור|לחזור ל|עתידו",
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
        # A social/quote/interview format is allowed through only when it is
        # clearly about transfers/contracts. Otherwise it is ordinary interview noise.
        return not has_real_transfer_context(cleaned)

    words = re.findall(r"[A-Za-zא-ת0-9]+", cleaned)
    if post.image_urls and len(words) <= 14 and not post.video_urls:
        return True

    return False



# ====== SMART FILTERS: FLAGS, WOMEN/WNBA, DUPLICATE NEWS ======
RECENT_NEWS_STATE_KEY = "__recent_news_events__"
RECENT_NEWS_WINDOW_SECONDS = 24 * 60 * 60
CHANNEL_RECENT_NEWS_STATE_KEY = "__channel_recent_news_events__"
CHANNEL_RECENT_NEWS_WINDOW_SECONDS = 12 * 60 * 60

SOURCE_PRIORITY = {
    "FabrizioRomano": 100,
    "David_Ornstein": 95,
    "DiMarzio": 90,
    "JacobsBen": 80,
    "MatteMoretto": 78,
    "ffpolo": 70,
    "AranchaMOBILE": 70,
    "FabriceHawkins": 68,
    "gerardromero": 65,
    "MonfortCarlos": 62,
    "JLSanchez78": 62,
    "jfelixdiaz": 60,
    "Plettigoal": 55,
    "NicoSchira": 10,
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

MEDICAL_STAFF_BLOCK_PATTERNS = (
    r"\b(?:appoint|appoints?|appointed|hires?|hired|names?|named|set to appoint|will appoint|joins?|joining|new|replacement for|replaces?)\b.{0,120}\b(?:doctor|club doctor|team doctor|physio|physios|physiotherapist|physiotherapists|medical staff|head of medical|medical department|medical team|chief medical officer|sports medicine)\b",
    r"\b(?:doctor|club doctor|team doctor|physio|physios|physiotherapist|physiotherapists|medical staff|head of medical|medical department|medical team|chief medical officer|sports medicine)\b.{0,120}\b(?:appoints?|appointed|hires?|hired|joins?|joining|new|replacement|replaces?|leaves?|left)\b",
    r"(?:ממנה|מינתה|מונה|ימונה|מינוי|מצרפת|מצטרף|מצטרפים|חדש|חדשה|מחליף|מחליפה|עזב|עזבה).{0,120}(?:דוקטור|רופא(?:\s+המועדון|\s+הקבוצה)?|צוות\s+רפואי|מחלקה\s+רפואית|פיזיותרפיסט(?:ים)?|פיזיו(?:תרפיסטים)?|ראש\s+המערך\s+הרפואי|מנהל\s+רפואי)",
    r"(?:דוקטור|רופא(?:\s+המועדון|\s+הקבוצה)?|צוות\s+רפואי|מחלקה\s+רפואית|פיזיותרפיסט(?:ים)?|פיזיו(?:תרפיסטים)?|ראש\s+המערך\s+הרפואי|מנהל\s+רפואי).{0,120}(?:ממנה|מינתה|מונה|ימונה|מינוי|מצרפת|מצטרף|מצטרפים|חדש|חדשה|מחליף|מחליפה|עזב|עזבה)",
)

LOGGED_SKIP_KEYS: set[str] = set()


def log_skip_once(reason: str, post: "Post", message: str, *args: Any) -> None:
    key = hashlib.sha1(f"{reason}|{post.link or post.post_id}".encode("utf-8", errors="ignore")).hexdigest()
    if key in LOGGED_SKIP_KEYS:
        return
    LOGGED_SKIP_KEYS.add(key)
    if len(LOGGED_SKIP_KEYS) > 2000:
        LOGGED_SKIP_KEYS.clear()
    age_seconds = max(0.0, time.time() - post.published_ts) if getattr(post, "published_ts", 0.0) else 0.0
    source_name = getattr(post, "source_name", "unknown") or "unknown"
    logging.info(message + " | מקור RSS: %s | גיל: %.0fs", *args, source_name, age_seconds)

NEWS_DUP_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "from", "as", "by", "at", "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "he", "she", "they", "we", "you", "his", "her", "their", "our", "your",
    "according", "sources", "source", "reported", "report", "reports", "exclusive", "breaking", "official", "confirmed", "understand", "now", "today",
    "לפי", "מקורות", "דיווח", "דיווחים", "רשמי", "בלעדי", "היום", "כעת", "לאחר", "כפי", "כך", "כי", "של", "את", "עם", "על", "אל", "הוא", "היא", "הם", "הן", "זה", "זו", "הזה", "הזו",
}

NEWS_DUP_ACTION_WORDS = {
    "leave", "leaves", "leaving", "left", "exit", "exits", "depart", "departs", "free", "agent", "contract", "extend", "extension", "sign", "signs", "signed", "join", "joins", "joined",
    "transfer", "trade", "traded", "waive", "waived", "injury", "injured", "out", "miss", "misses", "called", "call", "replace", "replaces", "replacement", "sacked", "appointed", "agreed", "agreement", "deal", "announce", "announced", "confirmed",
    "עוזב", "יעזוב", "עזב", "שוחרר", "חופשי", "חוזה", "חתם", "יחתום", "מצטרף", "עבר", "יעבור", "העברה", "טרייד", "פציעה", "נפצע", "יחמיץ", "ייעדר", "מחליף", "להחליף", "זומן", "קורא", "לא", "ישחק", "מונה", "פוטר", "סוכם", "אישרה", "אישר", "הודיעה", "פורסם",
}


def strip_country_code_leftovers_near_flags(text: str) -> str:
    """Keep the flag emoji and remove duplicated ISO/transliterated country-code leftovers.

    Gemini sometimes turns a flag/ISO marker into Hebrew phonetics such as
    "טי אר" next to 🇹🇷. This keeps the emoji and removes the junk letters.
    """
    text = unicodedata.normalize("NFKC", text or "")
    # NFKC converts styled/full-width Latin letters such as 𝐓𝐑 / ＴＲ into normal TR,
    # so the next regexes can remove/convert them while keeping the flag emoji.
    invisible = r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]*"
    separator = r"[\s\u00a0._/\-־]*"
    if "COUNTRY_CODE_FLAGS" not in globals():
        return text
    for code, flag in COUNTRY_CODE_FLAGS.items():
        first, second = re.escape(code[0]), re.escape(code[1])
        first_regional = chr(0x1F1E6 + ord(code[0]) - ord("A"))
        second_regional = chr(0x1F1E6 + ord(code[1]) - ord("A"))
        text = re.sub(rf"{re.escape(first_regional)}\s+{re.escape(second_regional)}", flag, text)
        code_pattern = rf"{invisible}{first}{invisible}{separator}{invisible}{second}{invisible}"
        text = re.sub(rf"(?<![A-Za-z]){code_pattern}\s*{re.escape(flag)}", flag, text)
        text = re.sub(rf"{re.escape(flag)}\s*{code_pattern}(?![A-Za-z])", flag, text)
        text = re.sub(rf"{re.escape(flag)}\s*([🚨⚠️🔴🟡🟢]+)\s*{re.escape(flag)}", rf"{flag} \1", text)
        text = re.sub(rf"{re.escape(flag)}(?:\s*{re.escape(flag)})+", flag, text)

    # Hebrew phonetic leftovers for common two-letter country codes after translation.
    # These are removed only near the matching flag so normal Hebrew words are not touched.
    phonetic_near_flag = {
        "TR": (r"טי\s*[-.־]?\s*אר", r"טי\s*[-.־]?\s*ר"),
        "GE": (r"ג׳?י\s*[-.־]?\s*אי", r"גי\s*[-.־]?\s*אי"),
        "FR": (r"אף\s*[-.־]?\s*אר", r"אפ\s*[-.־]?\s*אר"),
        "IT": (r"איי\s*[-.־]?\s*טי", r"אי\s*[-.־]?\s*טי"),
        "ES": (r"אי\s*[-.־]?\s*אס", r"איי\s*[-.־]?\s*אס"),
        "DE": (r"די\s*[-.־]?\s*אי",),
        "BR": (r"בי\s*[-.־]?\s*אר",),
        "AR": (r"איי\s*[-.־]?\s*אר", r"אי\s*[-.־]?\s*אר"),
        "PT": (r"פי\s*[-.־]?\s*טי",),
        "NL": (r"אן\s*[-.־]?\s*אל",),
        "BE": (r"בי\s*[-.־]?\s*אי",),
        "GB": (r"ג׳?י\s*[-.־]?\s*בי", r"גי\s*[-.־]?\s*בי"),
        "US": (r"יו\s*[-.־]?\s*אס",),
        "UY": (r"יו\s*[-.־]?\s*וואי",),
        "CO": (r"סי\s*[-.־]?\s*או",),
        "MX": (r"אם\s*[-.־]?\s*אקס",),
        "MA": (r"אם\s*[-.־]?\s*איי", r"אם\s*[-.־]?\s*אי"),
        "SN": (r"אס\s*[-.־]?\s*אן",),
        "NG": (r"אן\s*[-.־]?\s*ג׳?י",),
        "JP": (r"ג׳?יי\s*[-.־]?\s*פי",),
    }
    for code, patterns in phonetic_near_flag.items():
        flag = COUNTRY_CODE_FLAGS.get(code)
        if not flag:
            continue
        for pattern in patterns:
            text = re.sub(rf"(?<![א-תA-Za-z]){pattern}(?![א-תA-Za-z])\s*{re.escape(flag)}", flag, text, flags=re.IGNORECASE)
            text = re.sub(rf"{re.escape(flag)}\s*(?<![א-תA-Za-z]){pattern}(?![א-תA-Za-z])", flag, text, flags=re.IGNORECASE)
    return text


def is_women_or_wnba_post(post: Post) -> bool:
    raw_text = html.unescape("\n".join([post.text or "", post.quoted_text or ""]))
    cleaned = remove_external_links(raw_text)
    return any(re.search(pattern, cleaned, re.IGNORECASE) for pattern in WOMEN_SPORT_BLOCK_PATTERNS)


def is_medical_staff_post(post: Post) -> bool:
    raw_text = html.unescape("\n".join([post.text or "", post.quoted_text or ""]))
    cleaned = remove_external_links(raw_text)
    return any(re.search(pattern, cleaned, re.IGNORECASE) for pattern in MEDICAL_STAFF_BLOCK_PATTERNS)


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
    current_numbers = {token for token in current_tokens if re.fullmatch(r"\d+", token)}
    previous_numbers = {token for token in previous_tokens if re.fullmatch(r"\d+", token)}
    number_overlap = len(current_numbers & previous_numbers)
    sequence_score = SequenceMatcher(None, " ".join(sorted(current_tokens)), " ".join(sorted(previous_tokens))).ratio()
    score = max(token_jaccard, sequence_score * 0.75)
    if entity_overlap >= 2 and (action_overlap >= 1 or number_overlap >= 1 or token_jaccard >= 0.24):
        score = max(score, 0.82)
    if entity_overlap >= 2 and number_overlap >= 1 and token_jaccard >= 0.16:
        score = max(score, 0.86)
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
        score = _event_similarity(current, previous)
        local = local_duplicate_verdict(post, item, score) if "local_duplicate_verdict" in globals() else "BORDERLINE"
        if local in {"ADVANCED_NEW", "DIFFERENT"}:
            continue
        if local == "SAME_DUPLICATE" or score >= 0.74:
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
            "ai_text": _ai_duplicate_text_from_post(post) if "_ai_duplicate_text_from_post" in globals() else _news_duplicate_clean_text(post),
            "signature": news_event_signature(post),
        }
    )
    state[RECENT_NEWS_STATE_KEY] = recent[-250:]


def channel_duplicate_text_to_post(text: str, message_id: str = "") -> Post:
    cleaned = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    cleaned = re.sub(r"https?://t\.me/neto_sport\b\S*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace(SIGNATURE_TEXT, " ")
    cleaned = re.sub(r"נטו\s+ספורט\.?", " ", cleaned)
    cleaned = re.sub(r"^\s*[\u200e\u200f]*[^\n:]{2,40}:\s*(?:\r?\n)+", " ", cleaned, count=1)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return Post(
        post_id=f"channel:{message_id or hashlib.sha1(cleaned.encode('utf-8', errors='ignore')).hexdigest()}",
        username="__channel__",
        text=cleaned,
        link=f"channel:{message_id}" if message_id else "",
        image_urls=[],
        video_urls=[],
        has_video=False,
        primary_has_video=False,
        quoted_has_video=False,
        quoted_author="",
        quoted_text="",
        published_ts=time.time(),
        dedupe_ids=[],
        source_name="telegram_channel",
    )


def cleanup_channel_recent_news_events(state: dict[str, Any], now: float | None = None) -> list[dict[str, Any]]:
    now = now or time.time()
    recent_raw = state.get(CHANNEL_RECENT_NEWS_STATE_KEY, [])
    if not isinstance(recent_raw, list):
        recent_raw = []
    recent: list[dict[str, Any]] = []
    for item in recent_raw:
        if isinstance(item, dict) and now - float(item.get("ts", 0) or 0) <= CHANNEL_RECENT_NEWS_WINDOW_SECONDS:
            recent.append(item)
    state[CHANNEL_RECENT_NEWS_STATE_KEY] = recent[-300:]
    return state[CHANNEL_RECENT_NEWS_STATE_KEY]


def remember_channel_news_text(text: str, state: dict[str, Any], message_id: str = "", source: str = "channel") -> None:
    post = channel_duplicate_text_to_post(text, message_id)
    if len(post.text) < 12:
        return
    recent = cleanup_channel_recent_news_events(state)
    signature = news_event_signature(post)
    if not signature.get("tokens"):
        return
    recent.append(
        {
            "ts": time.time(),
            "username": source,
            "priority": 120,
            "link": post.link,
            "ai_text": post.text,
            "signature": signature,
        }
    )
    state[CHANNEL_RECENT_NEWS_STATE_KEY] = recent[-300:]


def find_channel_duplicate_event(post: Post, state: dict[str, Any]) -> dict[str, Any] | None:
    current = news_event_signature(post)
    for item in reversed(cleanup_channel_recent_news_events(state)):
        if not isinstance(item, dict):
            continue
        previous = item.get("signature", {})
        if not isinstance(previous, dict):
            continue
        score = _event_similarity(current, previous)
        local = local_duplicate_verdict(post, item, score) if "local_duplicate_verdict" in globals() else "BORDERLINE"
        if local in {"ADVANCED_NEW", "DIFFERENT"}:
            continue
        if local == "SAME_DUPLICATE" or score >= 0.76:
            return item
    return None


def clone_post_with_text(post: Post, text: str) -> Post:
    return Post(
        post_id=post.post_id,
        username=post.username,
        text=text.strip(),
        link=post.link,
        image_urls=post.image_urls,
        video_urls=post.video_urls,
        has_video=post.has_video,
        primary_has_video=post.primary_has_video,
        quoted_has_video=False,
        quoted_author="",
        quoted_text="",
        published_ts=post.published_ts,
        dedupe_ids=post.dedupe_ids,
        source_name=post.source_name,
    )


def split_clear_report_lines(post: Post) -> list[str]:
    raw = html.unescape(post.text or "")
    has_coach_context = bool(re.search(r"\b(?:coach|manager|head coach)\b|מאמן|מאמנים", raw, re.IGNORECASE))
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw.splitlines()]
    lines = [line for line in lines if line and len(line) >= 18]
    report_lines: list[str] = []
    for line in lines:
        if re.search(r"(?i)\b(?:video|watch|podcast|full episode|listen)\b|וידאו|וידיאו|פודקאסט|פודקסט|פרק מלא|האזינו", line):
            continue
        if has_coach_context and re.search(r"\b(?:list|shortlist|top of .*list)\b|רשימת|בראש רשימת", line, re.IGNORECASE) and not re.search(r"\b(?:coach|manager|head coach)\b|מאמן|מאמנים", line, re.IGNORECASE):
            if re.search(r"\blist\b", line, re.IGNORECASE):
                line = re.sub(r"\blist\b", "manager list", line, count=1, flags=re.IGNORECASE)
            elif "רשימת" in line:
                line = line.replace("רשימת", "רשימת המאמנים", 1)
        if len(_news_duplicate_tokens(_news_duplicate_clean_text(clone_post_with_text(post, line)))) < 3:
            continue
        report_lines.append(line)
    return report_lines


def try_keep_non_duplicate_report_lines(post: Post, state: dict[str, Any]) -> bool:
    lines = split_clear_report_lines(post)
    if len(lines) < 2:
        return False
    kept: list[str] = []
    dropped = 0
    for line in lines:
        line_post = clone_post_with_text(post, line)
        if find_channel_duplicate_event(line_post, state) or find_recent_duplicate_event(line_post, state):
            dropped += 1
            continue
        if is_interview_post(line_post) or is_other_sport_post(line_post) or is_youth_or_academy_post(line_post) or is_lineup_or_selection_post(line_post):
            dropped += 1
            continue
        if is_podcast_or_longform_post(line_post) or is_link_only_or_details_post(line_post):
            dropped += 1
            continue
        allowed, _reason, _score, _signals = football_relevance_decision(line_post)
        if not allowed:
            dropped += 1
            continue
        kept.append(line)
    if dropped and kept:
        post.text = "\n".join(kept)
        post.quoted_text = ""
        return True
    return False


def sort_candidate_posts_for_priority(candidates: list[tuple[str, Post, float]]) -> list[tuple[str, Post, float]]:
    return sorted(
        candidates,
        key=lambda item: (
            -SOURCE_PRIORITY.get(item[0], 0),
            -(item[1].published_ts or 0),
        ),
    )


# ====== SMART AI DUPLICATE CHECK ======
# The cheap token/entity check runs first. Gemini is used only for borderline cases,
# and only for posts that already passed all filters and are about to be sent.
ENABLE_AI_DUPLICATE_CHECK = os.environ.get("ENABLE_AI_DUPLICATE_CHECK", "0") != "0"
AI_DUPLICATE_MIN_SIMILARITY = float(os.environ.get("AI_DUPLICATE_MIN_SIMILARITY", "0.52"))
AI_DUPLICATE_AUTO_SKIP_SIMILARITY = float(os.environ.get("AI_DUPLICATE_AUTO_SKIP_SIMILARITY", "0.90"))
AI_DUPLICATE_ADVANCED_SOURCES = {"FabrizioRomano", "David_Ornstein", "ShamsCharania"}


def _event_similarity_score_for_post(post: Post, previous_item: dict[str, Any]) -> float:
    previous = previous_item.get("signature", {}) if isinstance(previous_item, dict) else {}
    if not isinstance(previous, dict):
        return 0.0
    return _event_similarity(news_event_signature(post), previous)


def _ai_duplicate_text_from_post(post: Post) -> str:
    text = html.unescape("\n".join([post.text or "", post.quoted_text or ""]))
    text = normalize_country_flags(text) if "normalize_country_flags" in globals() else text
    text = remove_external_links(text)
    text = convert_hashtags_to_text(text)
    text = re.sub(r"(?<!\w)@[A-Za-z0-9_]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1800]


def _ai_duplicate_text_from_item(item: dict[str, Any]) -> str:
    value = str(item.get("ai_text") or item.get("text") or "")
    if not value and isinstance(item.get("signature"), dict):
        value = str(item["signature"].get("text") or "")
    return value[:1800]




# ====== GEMINI REQUEST SAVER / SMART LOCAL DECISION LAYER ======
# Goal: do every cheap deterministic check first and use Gemini only for truly borderline cases.
# This saves Gemini quota and also prevents wasting AI work on posts that will be filtered/skipped anyway.
ENABLE_AI_REQUEST_SAVER = os.environ.get("ENABLE_AI_REQUEST_SAVER", "1") != "0"
AI_DECISION_CACHE_MAX_ITEMS = int(os.environ.get("AI_DECISION_CACHE_MAX_ITEMS", "1000"))
AI_PARALLEL_MERGE_USE_AI_MIN_CLUSTER_SIZE = int(os.environ.get("AI_PARALLEL_MERGE_USE_AI_MIN_CLUSTER_SIZE", "3"))
AI_PARALLEL_MERGE_USE_AI_MIN_DETAIL_DELTA = int(os.environ.get("AI_PARALLEL_MERGE_USE_AI_MIN_DETAIL_DELTA", "2"))
AI_DECISION_CACHE: dict[str, str] = {}
AI_DECISION_CACHE_ORDER: list[str] = []


def ai_decision_cache_path() -> Path:
    return Path(__file__).resolve().parent / AI_DECISION_CACHE_FILE

def _load_ai_decision_cache_from_disk() -> None:
    if not ENABLE_AI_REQUEST_SAVER:
        return
    path = ai_decision_cache_path()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data.get("items", data) if isinstance(data, dict) else data
        if isinstance(items, dict):
            iterable = list(items.items())
        elif isinstance(items, list):
            iterable = [(str(item.get("key", "")), str(item.get("verdict", ""))) for item in items if isinstance(item, dict)]
        else:
            return
        for key, verdict in iterable[-AI_DECISION_CACHE_MAX_ITEMS:]:
            if key and verdict in {"SAME_DUPLICATE", "ADVANCED_NEW", "DIFFERENT", "UNKNOWN"}:
                AI_DECISION_CACHE[key] = verdict
                AI_DECISION_CACHE_ORDER.append(key)
        # remove duplicate order entries while preserving order
        seen_keys: set[str] = set()
        AI_DECISION_CACHE_ORDER[:] = [k for k in AI_DECISION_CACHE_ORDER if not (k in seen_keys or seen_keys.add(k))]
        logging.info("נטען cache כפילויות AI מהדיסק: %s החלטות", len(AI_DECISION_CACHE))
    except Exception as exc:
        logging.warning("Could not load AI decision cache: %s", exc)

def save_ai_decision_cache() -> None:
    if not ENABLE_AI_REQUEST_SAVER:
        return
    try:
        path = ai_decision_cache_path()
        temp_path = path.with_suffix(path.suffix + ".tmp")
        ordered = {key: AI_DECISION_CACHE[key] for key in AI_DECISION_CACHE_ORDER[-AI_DECISION_CACHE_MAX_ITEMS:] if key in AI_DECISION_CACHE}
        temp_path.write_text(json.dumps({"items": ordered}, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(path)
    except Exception as exc:
        logging.warning("Could not save AI decision cache: %s", exc)

_load_ai_decision_cache_from_disk()

EVENT_STAGE_PATTERNS: list[tuple[int, str, tuple[str, ...]]] = [
    (100, "official", ("official", "confirmed", "announce", "announced", "announcement", "club statement", "רשמי", "אישר", "אישרה", "הודיעה", "הודעה רשמית")),
    (90, "completed", ("done deal", "completed", "signed", "has signed", "joins", "traded", "waived", "released", "חתם", "חתמה", "עבר", "הצטרף", "שוחרר", "עזב")),
    (80, "agreement", ("agreed", "agreement", "deal agreed", "verbal agreement", "contract agreed", "סיכם", "סיכמה", "סוכם", "סיכום", "הסכמה")),
    (70, "medical_or_final_steps", ("medical", "medical tests", "paperwork", "final details", "בדיקות רפואיות", "ניירת", "פרטים אחרונים")),
    (60, "formal_bid", ("bid", "offer", "proposal", "rejected", "accepted", "הצעה", "הוגשה", "נדחתה", "התקבלה")),
    (50, "talks", ("talks", "negotiations", "advanced talks", "contact", "שיחות", "משא ומתן", "מגעים")),
    (40, "interest", ("interested", "monitoring", "considering", "target", "מעוניינת", "מעוניין", "עוקבת", "מועמד", "יעד")),
    (30, "availability", ("injury", "injured", "out", "questionable", "probable", "ruled out", "פציעה", "פצוע", "ייעדר", "בספק", "לא ישחק")),
]

IMPORTANT_DETAIL_WORDS = {
    "official", "confirmed", "contract", "fee", "salary", "years", "year", "option", "clause", "medical", "loan", "permanent",
    "pick", "picks", "first-round", "second-round", "extension", "waived", "injury", "severity", "return", "date", "deadline",
    "רשמי", "אישרה", "אישר", "חוזה", "שכר", "מיליון", "שנים", "שנה", "אופציה", "סעיף", "בדיקות", "רפואיות", "השאלה",
    "בחירה", "דראפט", "הארכת", "שוחרר", "פציעה", "חומרת", "חזרה", "תאריך", "דדליין",
}


def _text_stage_rank(text: str) -> tuple[int, str]:
    lowered = (text or "").lower()
    for rank, label, patterns in EVENT_STAGE_PATTERNS:
        if any(pattern.lower() in lowered for pattern in patterns):
            return rank, label
    return 0, "unknown"


def _signature_sets_from_post(post: Post) -> tuple[set[str], set[str], set[str], str]:
    sig = news_event_signature(post)
    return set(sig.get("entities", [])), set(sig.get("actions", [])), set(sig.get("tokens", [])), str(sig.get("text", ""))


def _signature_sets_from_item(item: dict[str, Any]) -> tuple[set[str], set[str], set[str], str]:
    sig = item.get("signature", {}) if isinstance(item, dict) else {}
    if not isinstance(sig, dict):
        sig = {}
    return set(sig.get("entities", [])), set(sig.get("actions", [])), set(sig.get("tokens", [])), str(sig.get("text", "") or _ai_duplicate_text_from_item(item))


def _important_detail_delta(current_tokens: set[str], previous_tokens: set[str]) -> int:
    return len((current_tokens - previous_tokens) & IMPORTANT_DETAIL_WORDS)


GENERIC_DUPLICATE_CONTEXT_TOKENS = {
    "manchester", "united", "real", "madrid", "barcelona", "barca", "arsenal", "chelsea", "liverpool",
    "tottenham", "spurs", "city", "inter", "milan", "juventus", "psg", "bayern", "dortmund", "villa",
    "official", "confirmed", "free", "agent", "players", "player", "club", "clubs", "deal", "transfer",
    "contract", "years", "year", "today", "expected", "chapter", "new", "since", "after", "joins", "leaves",
    "רשמי", "רשמית", "שחקן", "שחקנים", "חופשי", "חופשיים", "עוזב", "עוזבים", "עזב", "עזבו", "מועדון",
    "קבוצה", "העברה", "עסקה", "חוזה", "שנים", "שנה", "היום", "צפוי", "צפויים", "חדש", "חדשה",
}


SQUAD_ABSENCE_CONTEXT_PATTERNS = (
    r"\b(?:World Cup|FIFA World Cup|national team|squad|called up|call-up|replacement|replace|replaces|miss|misses|injury|injured|out)\b",
    r"מונדיאל|גביע העולם|נבחרת|סגל|זומן|זימון|קורא|מחליף|להחליף|יחמיץ|ייעדר|פציעה|נפצע|פצוע",
)

SQUAD_ABSENCE_CONTEXT_TOKENS = {
    "world", "cup", "fifa", "national", "team", "squad", "called", "call", "replacement", "replace", "replaces",
    "miss", "misses", "injury", "injured", "out", "brazil", "brasil", "argentina", "france", "spain",
    "מונדיאל", "גביע", "העולם", "נבחרת", "סגל", "זומן", "זימון", "קורא", "מחליף", "להחליף", "יחמיץ", "ייעדר", "פציעה", "נפצע", "פצוע", "ברזיל", "ארגנטינה",
}


def _is_squad_absence_context(text: str) -> bool:
    return _matches_any(SQUAD_ABSENCE_CONTEXT_PATTERNS, text)


def _squad_absence_subject_overlap(cur_tokens: set[str], prev_tokens: set[str]) -> set[str]:
    shared = (cur_tokens & prev_tokens) - SQUAD_ABSENCE_CONTEXT_TOKENS - NEWS_DUP_STOPWORDS - NEWS_DUP_ACTION_WORDS
    return {token for token in shared if len(token) >= 5}


def _distinctive_duplicate_tokens(tokens: set[str], entities: set[str]) -> set[str]:
    """Tokens that usually point to the actual player/manager/event, not just the club/context."""
    combined = set(tokens) | set(entities)
    distinctive: set[str] = set()
    for token in combined:
        lowered = token.lower().strip("-'׳")
        if len(lowered) < 4:
            continue
        if lowered in NEWS_DUP_STOPWORDS or lowered in NEWS_DUP_ACTION_WORDS or lowered in IMPORTANT_DETAIL_WORDS:
            continue
        if lowered in GENERIC_DUPLICATE_CONTEXT_TOKENS:
            continue
        if re.fullmatch(r"\d+", lowered):
            continue
        distinctive.add(lowered)
    return distinctive


def local_duplicate_verdict(current_post: Post, previous_item: dict[str, Any], score: float | None = None) -> str:
    """Fast local decision before Gemini. Returns SAME_DUPLICATE, ADVANCED_NEW, DIFFERENT or BORDERLINE."""
    if not ENABLE_AI_REQUEST_SAVER:
        return "BORDERLINE"
    cur_entities, cur_actions, cur_tokens, cur_text = _signature_sets_from_post(current_post)
    prev_entities, prev_actions, prev_tokens, prev_text = _signature_sets_from_item(previous_item)
    if not cur_tokens or not prev_tokens:
        return "BORDERLINE"
    if score is None:
        previous_sig = previous_item.get("signature", {}) if isinstance(previous_item, dict) else {}
        if isinstance(previous_sig, dict):
            score = _event_similarity(news_event_signature(current_post), previous_sig)
        else:
            score = 0.0

    entity_overlap = len(cur_entities & prev_entities)
    action_overlap = len(cur_actions & prev_actions)
    current_rank, current_stage = _text_stage_rank(cur_text)
    previous_rank, previous_stage = _text_stage_rank(prev_text)
    detail_delta = _important_detail_delta(cur_tokens, prev_tokens)
    same_author = current_post.username == str(previous_item.get("username", ""))
    text_ratio = SequenceMatcher(None, cur_text, prev_text).ratio()
    cur_distinctive = _distinctive_duplicate_tokens(cur_tokens, cur_entities)
    prev_distinctive = _distinctive_duplicate_tokens(prev_tokens, prev_entities)
    distinctive_overlap = len(cur_distinctive & prev_distinctive)
    squad_absence_overlap = _squad_absence_subject_overlap(cur_tokens, prev_tokens)

    # Same journalist often posts several separate updates about the same club minutes apart.
    # For the same source, block only a near-repeat or a post sharing the same distinctive
    # player/manager/event tokens. Club/context overlap alone is not enough.
    if same_author:
        if text_ratio >= 0.94:
            return "SAME_DUPLICATE"
        if cur_distinctive and prev_distinctive and distinctive_overlap == 0:
            return "DIFFERENT"
        if distinctive_overlap == 0 and score < 0.94:
            return "DIFFERENT"
        if score < 0.86 and text_ratio < 0.86:
            return "DIFFERENT"

    # Clearly different: not enough shared entities and not enough text/action overlap.
    if score < AI_DUPLICATE_MIN_SIMILARITY and entity_overlap < 2:
        return "DIFFERENT"
    if entity_overlap == 0 and score < 0.72:
        return "DIFFERENT"

    if squad_absence_overlap and _is_squad_absence_context(cur_text) and _is_squad_absence_context(prev_text):
        return "SAME_DUPLICATE"

    # Material advancement: official/completed/agreed after a lower stage, or important new detail.
    if entity_overlap >= 1 and current_rank >= previous_rank + 20 and current_rank >= 50:
        return "ADVANCED_NEW"
    if entity_overlap >= 2 and detail_delta >= 3 and current_rank >= previous_rank:
        return "ADVANCED_NEW"

    # Very strong same-event match with no higher stage: skip locally, no Gemini needed.
    if score >= AI_DUPLICATE_AUTO_SKIP_SIMILARITY and current_rank <= previous_rank and detail_delta == 0:
        return "SAME_DUPLICATE"
    if entity_overlap >= 3 and action_overlap >= 1 and score >= 0.80 and current_rank <= previous_rank and detail_delta <= 1:
        return "SAME_DUPLICATE"

    # Same entity but stronger trusted source: usually same duplicate unless it materially advances.
    if entity_overlap >= 2 and score >= 0.82 and SOURCE_PRIORITY.get(current_post.username, 0) > int(previous_item.get("priority", 0) or 0) and current_rank <= previous_rank and detail_delta <= 1:
        return "SAME_DUPLICATE"

    return "BORDERLINE"


def _ai_cache_key(previous_text: str, current_text: str) -> str:
    base = (previous_text.strip().lower() + "\n---\n" + current_text.strip().lower()).encode("utf-8", errors="ignore")
    return hashlib.sha1(base).hexdigest()


def _ai_cache_get(previous_text: str, current_text: str) -> str | None:
    if not ENABLE_AI_REQUEST_SAVER:
        return None
    return AI_DECISION_CACHE.get(_ai_cache_key(previous_text, current_text))


def _ai_cache_set(previous_text: str, current_text: str, verdict: str) -> None:
    if not ENABLE_AI_REQUEST_SAVER or verdict not in {"SAME_DUPLICATE", "ADVANCED_NEW", "DIFFERENT", "UNKNOWN"}:
        return
    key = _ai_cache_key(previous_text, current_text)
    if key not in AI_DECISION_CACHE:
        AI_DECISION_CACHE_ORDER.append(key)
    AI_DECISION_CACHE[key] = verdict
    save_ai_decision_cache()
    while len(AI_DECISION_CACHE_ORDER) > AI_DECISION_CACHE_MAX_ITEMS:
        old = AI_DECISION_CACHE_ORDER.pop(0)
        AI_DECISION_CACHE.pop(old, None)


def parallel_merge_needs_ai(cluster: list[tuple[str, Post, float]]) -> bool:
    """Use AI merge only when there are enough parallel sources or one source adds real details."""
    if not ENABLE_AI_PARALLEL_MERGE or not GEMINI_API_KEYS or not ENABLE_AI_REQUEST_SAVER:
        return bool(ENABLE_AI_PARALLEL_MERGE and GEMINI_API_KEYS)
    if len(cluster) >= AI_PARALLEL_MERGE_USE_AI_MIN_CLUSTER_SIZE:
        return True
    ordered = sorted(cluster, key=lambda item: (-SOURCE_PRIORITY.get(_candidate_username(item), 0), -(_candidate_post(item).published_ts or 0)))
    base_tokens = set(news_event_signature(_candidate_post(ordered[0])).get("tokens", []))
    for _username, post, _found in ordered[1:]:
        tokens = set(news_event_signature(post).get("tokens", []))
        if _important_detail_delta(tokens, base_tokens) >= AI_PARALLEL_MERGE_USE_AI_MIN_DETAIL_DELTA:
            return True
    return False

def gemini_duplicate_event_verdict(current_post: Post, previous_item: dict[str, Any]) -> str:
    """
    Returns one of: SAME_DUPLICATE, ADVANCED_NEW, DIFFERENT, UNKNOWN.
    Gemini is called only after local cheap checks and cache lookup fail.
    """
    previous_text = _ai_duplicate_text_from_item(previous_item)
    current_text = _ai_duplicate_text_from_post(current_post)
    if not previous_text or not current_text:
        return "UNKNOWN"

    score = _event_similarity_score_for_post(current_post, previous_item)
    local = local_duplicate_verdict(current_post, previous_item, score)
    if local in {"SAME_DUPLICATE", "ADVANCED_NEW", "DIFFERENT"}:
        logging.info("חיסכון Gemini: החלטה מקומית בכפילות @%s מול @%s => %s | score=%.2f", current_post.username, previous_item.get("username", "unknown"), local, score)
        return local

    cached = _ai_cache_get(previous_text, current_text)
    if cached:
        logging.info("חיסכון Gemini: תשובת כפילות מה-cache @%s מול @%s => %s", current_post.username, previous_item.get("username", "unknown"), cached)
        return cached

    if not ENABLE_AI_DUPLICATE_CHECK or not GEMINI_API_KEYS:
        return "UNKNOWN"
    if not has_gemini_key_available():
        logging.info("חיסכון Gemini: אין מפתח זמין כרגע לפי cooldown מקומי; מדלג על AI כפילות למחזור הזה")
        return "UNKNOWN"

    prompt = (
        "You are a strict sports-news duplicate detector for a Telegram news bot.\n"
        "Compare PREVIOUS_SENT and CURRENT_CANDIDATE.\n"
        "Return exactly one label only:\n"
        "SAME_DUPLICATE = same core news event and CURRENT adds no important new factual development.\n"
        "ADVANCED_NEW = same topic/player/team, but CURRENT materially advances the story: official confirmation after rumor, completed deal after talks, new club/destination, new fee, new injury severity, new contract decision, new date, lineup/squad update, or stronger verified source.\n"
        "DIFFERENT = related sport but a different event/story.\n"
        "When unsure, prefer ADVANCED_NEW instead of blocking.\n\n"
        f"PREVIOUS_SENT_SOURCE: @{previous_item.get('username', 'unknown')}\n"
        f"CURRENT_SOURCE: @{current_post.username}\n"
        f"PREVIOUS_SENT:\n{previous_text}\n\n"
        f"CURRENT_CANDIDATE:\n{current_text}\n"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 12},
    }
    last_error: Exception | None = None
    real_requests_used = 0
    for index, key in gemini_available_keys_for_operation():
        if real_requests_used >= 1:
            break
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_FAST_MODEL}:generateContent?key={urllib.parse.quote(key)}"
        try:
            # One real Gemini duplicate-judge request max. Key sweep is local/free.
            real_requests_used += 1
            data = http_post_json(url, payload, timeout=18, max_attempts=1, respect_retry_after=False)
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            answer = "".join(part.get("text", "") for part in parts).strip().upper()
            if "SAME_DUPLICATE" in answer:
                _ai_cache_set(previous_text, current_text, "SAME_DUPLICATE")
                return "SAME_DUPLICATE"
            if "ADVANCED_NEW" in answer:
                _ai_cache_set(previous_text, current_text, "ADVANCED_NEW")
                return "ADVANCED_NEW"
            if "DIFFERENT" in answer:
                _ai_cache_set(previous_text, current_text, "DIFFERENT")
                return "DIFFERENT"
        except Exception as exc:
            last_error = exc
            try:
                cool_down_gemini_key(key, exc)
            except Exception:
                pass
            continue
    if last_error:
        logging.warning("AI duplicate check unavailable: %s", gemini_error_summary(last_error) if 'gemini_error_summary' in globals() else last_error)
    _ai_cache_set(previous_text, current_text, "UNKNOWN")
    return "UNKNOWN"

def find_recent_duplicate_event_ai_aware(post: Post, state: dict[str, Any]) -> dict[str, Any] | None:
    """Final duplicate gate. Cheap local rules first, Gemini only for borderline near-matches."""
    recent = list(reversed(cleanup_recent_news_events(state)))
    fallback_duplicate: dict[str, Any] | None = None
    for item in recent:
        if not isinstance(item, dict):
            continue
        score = _event_similarity_score_for_post(post, item)
        if score < AI_DUPLICATE_MIN_SIMILARITY and score < 0.72:
            continue

        local = local_duplicate_verdict(post, item, score)
        if local == "SAME_DUPLICATE":
            return item
        if local in {"ADVANCED_NEW", "DIFFERENT"}:
            continue

        # Gemini only for true borderline cases.
        if score >= AI_DUPLICATE_MIN_SIMILARITY:
            verdict = gemini_duplicate_event_verdict(post, item)
            if verdict == "SAME_DUPLICATE":
                return item
            if verdict in {"ADVANCED_NEW", "DIFFERENT"}:
                continue
            if score >= 0.78 and fallback_duplicate is None:
                fallback_duplicate = item
    return fallback_duplicate



# ====== PARALLEL BREAKING-FATIGUE MERGE ======
# This layer runs after all cheap filters and before translation/video lookup.
# It solves the "many accounts posted the same thing at the same second" problem:
# candidates from the same run are clustered, then either merged into one smart update
# or kept separate if Gemini says one of them is a real advancement.
ENABLE_AI_PARALLEL_MERGE = os.environ.get("ENABLE_AI_PARALLEL_MERGE", "0") != "0"
PARALLEL_MERGE_WINDOW_SECONDS = int(os.environ.get("PARALLEL_MERGE_WINDOW_SECONDS", "180"))
PARALLEL_MERGE_MIN_SIMILARITY = float(os.environ.get("PARALLEL_MERGE_MIN_SIMILARITY", "0.52"))
PARALLEL_MERGE_AUTO_SIMILARITY = float(os.environ.get("PARALLEL_MERGE_AUTO_SIMILARITY", "0.86"))


def _candidate_post(item: tuple[str, Post, float]) -> Post:
    return item[1]


def _candidate_username(item: tuple[str, Post, float]) -> str:
    return item[0]


def _published_gap_ok(post_a: Post, post_b: Post) -> bool:
    if not post_a.published_ts or not post_b.published_ts:
        return True
    return abs(post_a.published_ts - post_b.published_ts) <= PARALLEL_MERGE_WINDOW_SECONDS


def parallel_duplicate_relation(post_a: Post, post_b: Post) -> str:
    """Return SAME, ADVANCED, DIFFERENT or UNKNOWN for two same-cycle candidates. Gemini is last resort."""
    if not _published_gap_ok(post_a, post_b):
        return "DIFFERENT"
    sig_a = news_event_signature(post_a)
    sig_b = news_event_signature(post_b)
    score = _event_similarity(sig_a, sig_b)
    if score >= PARALLEL_MERGE_AUTO_SIMILARITY:
        # Same-cycle very strong match: merge locally, no Gemini.
        return "SAME"
    if score < PARALLEL_MERGE_MIN_SIMILARITY:
        return "DIFFERENT"

    fake_previous = {
        "username": post_a.username,
        "priority": SOURCE_PRIORITY.get(post_a.username, 0),
        "ai_text": _ai_duplicate_text_from_post(post_a),
        "signature": sig_a,
    }
    local = local_duplicate_verdict(post_b, fake_previous, score)
    if local == "SAME_DUPLICATE":
        return "SAME"
    if local == "ADVANCED_NEW":
        return "ADVANCED"
    if local == "DIFFERENT":
        return "DIFFERENT"

    if ENABLE_AI_PARALLEL_MERGE and GEMINI_API_KEYS:
        verdict = gemini_duplicate_event_verdict(post_b, fake_previous)
        if verdict == "SAME_DUPLICATE":
            return "SAME"
        if verdict == "ADVANCED_NEW":
            return "ADVANCED"
        if verdict == "DIFFERENT":
            return "DIFFERENT"
    return "SAME" if score >= 0.74 else "DIFFERENT"


def best_source_item(cluster: list[tuple[str, Post, float]]) -> tuple[str, Post, float]:
    return sorted(
        cluster,
        key=lambda item: (
            -SOURCE_PRIORITY.get(_candidate_username(item), 0),
            -(_candidate_post(item).published_ts or 0),
            _candidate_username(item),
        ),
    )[0]


def ai_merge_parallel_posts(cluster: list[tuple[str, Post, float]]) -> str:
    """Create one concise English source text for a merged same-event update."""
    if len(cluster) <= 1:
        return _ai_duplicate_text_from_post(_candidate_post(cluster[0]))
    ordered = sorted(
        cluster,
        key=lambda item: (-SOURCE_PRIORITY.get(_candidate_username(item), 0), -(_candidate_post(item).published_ts or 0)),
    )[:6]
    source_blocks = []
    for username, post, _found in ordered:
        source_blocks.append(f"@{username}: {_ai_duplicate_text_from_post(post)}")
    fallback = _ai_duplicate_text_from_post(_candidate_post(ordered[0]))
    if not parallel_merge_needs_ai(cluster):
        also = ", ".join("@" + _candidate_username(item) for item in ordered[1:4])
        logging.info("חיסכון Gemini: מיזוג מקביל מקומי בלי AI. מקורות: %s", also or _candidate_username(ordered[0]))
        return fallback + (f"\nAlso reported by: {also}" if also else "")
    if not has_gemini_key_available():
        also = ", ".join("@" + _candidate_username(item) for item in ordered[1:4])
        logging.info("חיסכון Gemini: מיזוג AI נדחה כי אין מפתח זמין; משתמש במקור הטוב ביותר")
        return fallback + (f"\nAlso reported by: {also}" if also else "")
    logging.info("Gemini merge: משתמש בבינה רק כי יש כמה מקורות/פרטים חדשים שצריך למזג חכם")
    prompt = (
        "You are an elite sports Telegram news editor. Several sources posted at nearly the same time.\n"
        "Merge them into ONE short factual English update for translation to Hebrew.\n"
        "Rules:\n"
        "- Do not invent facts.\n"
        "- Keep only the newest/strongest facts.\n"
        "- If sources repeat the same news, write it once.\n"
        "- If one source adds a material detail, include that detail.\n"
        "- Do not write analysis/opinion.\n"
        "- End with: Sources: @source1, @source2.\n\n"
        + "\n\n".join(source_blocks)
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 320},
    }
    real_requests_used = 0
    for _index, key in gemini_available_keys_for_operation():
        if real_requests_used >= 1:
            break
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_FAST_MODEL}:generateContent?key={urllib.parse.quote(key)}"
        try:
            # One real Gemini merge request max. Key sweep is local/free.
            real_requests_used += 1
            data = http_post_json(url, payload, timeout=22, max_attempts=1, respect_retry_after=False)
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            merged = "".join(part.get("text", "") for part in parts).strip()
            if merged and len(merged) >= 20:
                return merged[:1800]
        except Exception as exc:
            try:
                cool_down_gemini_key(key, exc)
            except Exception:
                pass
            continue
    also = ", ".join("@" + _candidate_username(item) for item in ordered[1:4])
    return fallback + (f"\nAlso reported by: {also}" if also else "")


def make_merged_parallel_candidate(cluster: list[tuple[str, Post, float]]) -> tuple[str, Post, float]:
    best_username, best_post, found_seconds = best_source_item(cluster)
    if len(cluster) <= 1:
        return best_username, best_post, found_seconds
    merged_text = ai_merge_parallel_posts(cluster)
    all_ids: list[str] = []
    all_images: list[str] = []
    all_videos: list[str] = []
    has_video = False
    for username, post, _found in cluster:
        all_ids.extend(post.dedupe_ids)
        all_images.extend(post.image_urls)
        all_videos.extend(post.video_urls)
        has_video = has_video or post.has_video
    merged_post = Post(
        post_id="merged:" + hashlib.sha1("|".join(sorted(set(all_ids))).encode("utf-8")).hexdigest(),
        username=best_username,
        text=merged_text,
        link=best_post.link,
        image_urls=list(dict.fromkeys(all_images))[:MAX_IMAGES_PER_POST],
        video_urls=list(dict.fromkeys(all_videos)),
        has_video=has_video,
        primary_has_video=best_post.primary_has_video,
        quoted_has_video=False,
        quoted_author="",
        quoted_text="",
        published_ts=max((post.published_ts or 0.0) for _u, post, _f in cluster),
        dedupe_ids=list(dict.fromkeys(all_ids)),
        source_name="parallel-merged",
    )
    # Dynamic metadata for state/logging. Dataclass has no slots, so this is safe.
    setattr(merged_post, "merged_sources", [_candidate_username(item) for item in cluster])
    logging.info(
        "מיזוג חכם: %s דיווחים מקבילים אוחדו להודעה אחת. מקור מוביל: @%s | מקורות: %s",
        len(cluster),
        best_username,
        ", ".join("@" + _candidate_username(item) for item in cluster),
    )
    return best_username, merged_post, min(found_seconds for _u, _p, found_seconds in cluster)


def cluster_parallel_candidates(candidates: list[tuple[str, Post, float]]) -> list[tuple[str, Post, float]]:
    """Merge same-cycle duplicate bursts before any translation/video work is done."""
    if len(candidates) <= 1:
        return candidates
    ordered = sort_candidate_posts_for_priority(candidates)
    clusters: list[list[tuple[str, Post, float]]] = []
    for candidate in ordered:
        post = _candidate_post(candidate)
        placed = False
        for cluster in clusters:
            # Compare to the best representative and at least one member.
            representative = _candidate_post(best_source_item(cluster))
            relation = parallel_duplicate_relation(representative, post)
            if relation == "SAME" or any(parallel_duplicate_relation(_candidate_post(item), post) == "SAME" for item in cluster):
                cluster.append(candidate)
                placed = True
                break
            if relation == "ADVANCED":
                # Real development: keep separate, do not merge.
                continue
        if not placed:
            clusters.append([candidate])
    merged = [make_merged_parallel_candidate(cluster) for cluster in clusters]
    return sort_candidate_posts_for_priority(merged)


def mark_candidate_seen(state: dict[str, Any], candidate: tuple[str, Post, float]) -> None:
    """Mark all dedupe ids for a candidate, including merged-source ids, without doing extra work later."""
    username, post, _found = candidate
    target_names = list(getattr(post, "merged_sources", []) or [username])
    for target in target_names:
        seen = set(state.get(target, []))
        seen.update(post.dedupe_ids)
        state[target] = list(seen)[-500:]

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
    for handle, replacement in sorted(ATTRIBUTION_HANDLE_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True):
        text = re.sub(rf"(?i)@{re.escape(handle)}\b", replacement, text)
    text = re.sub(r"(?iu)\s*,?\s*(?:told|said to|speaking to|via|for)\s+@?[A-Za-z0-9_]{3,40}\s*[.!?]?\s*$", "", text)
    text = re.sub(r"(?iu)\s*,?\s*(?:אמר|אמרה|אמרו|בראיון|בשיחה|דיבר|דיברה)\s+ל-?@?[A-Za-z0-9_]{3,40}\s*[.!?]?\s*$", "", text)
    text = re.sub(
        r"(?<!\w)@[A-Za-z0-9_]*(?:FC|CF|TV|News|Sport|Sports|Calcio|Official|Media)[A-Za-z0-9_]*\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"(?iu)(?:^|\s)@?(?:acmilan|juventusfc|inter|sscnapoli|officialsscnapoli|asroma|officialasroma|realmadrid|fcbarcelona|manutd|mancity|lfc|chelseafc|arsenal|spursofficial|psg_inside|fcbayern)\b(?=\s|$|[.,;:!?])", " ", text)
    text = re.sub(r"(?<!\w)@[A-Za-z0-9_]*[_\d][A-Za-z0-9_]*\b", "", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def remove_junk_topic_tags(text: str) -> str:
    value = text or ""
    value = re.sub(
        r"(?ium)^\s*#?(?:transfers?|transfernews|mercato|calciomercato|market|football|soccer|news|breaking|exclusive|העברות|העברה|חדשות|כדורגל|בלעדי|דיווח)\s*[.!?.,;:]*\s*$",
        "",
        value,
    )
    value = re.sub(
        r"(?iu)(?:\s+|^)#(?:transfers?|transfernews|mercato|calciomercato|market|football|soccer|news|breaking|exclusive)\b",
        " ",
        value,
    )
    value = re.sub(r"(?iu)(?<=[.!?。])\s+(?:העברות|העברה|חדשות|כדורגל)\s*[.!?.,;:]*\s*$", "", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    value = re.sub(r" *\n+ *", "\n", value)
    return value.strip()


def normalize_official_club_names_for_translation(text: str) -> str:
    value = text or ""
    value = re.sub(r"(?iu)\bBrighton\s*(?:&|and)\s*Hove\s+Albion\b", "Brighton", value)
    value = re.sub(r"(?iu)\bברייטון\s+(?:אנד|ו)?\s*הוב\s+אלביון\b", "ברייטון", value)
    value = re.sub(r"(?iu)\bברייטון\s+אלביון\b", "ברייטון", value)
    return value


def remove_untranslated_arabic_leftovers(text: str) -> str:
    lines: list[str] = []
    for line in (text or "").splitlines():
        if ARABIC_TEXT_RE.search(line):
            has_hebrew = bool(re.search(r"[א-ת]", line))
            arabic_chars = len(ARABIC_TEXT_RE.findall(line))
            # After Gemini, raw Arabic is usually an untranslated source tag or
            # a short copied phrase. Keep Hebrew around it, remove the leftover.
            if not has_hebrew or len(line.strip()) <= 90:
                line = ARABIC_TEXT_RE.sub("", line)
            else:
                line = ARABIC_TEXT_RE.sub("", line)
        line = re.sub(r"\s+([,.!?;:])", r"\1", line)
        line = re.sub(r"[ \t]{2,}", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines).strip()


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
    text = normalize_official_club_names_for_translation(text)
    text = apply_handle_replacements(text)
    text = remove_credit_handles(text)
    text = remove_junk_topic_tags(text)
    text = convert_hashtags_to_text(text)
    text = remove_junk_topic_tags(text)
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
    text = normalize_official_club_names_for_translation(text)
    text = remove_junk_topic_tags(text)
    text = convert_hashtags_to_text(text)
    text = remove_junk_topic_tags(text)
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


def gemini_key_order_limited(max_keys: int | None = None) -> list[tuple[int, str]]:
    """Return available Gemini keys without doing any network request.

    This is intentionally only a local availability/cooldown check. It keeps the
    bot scanning often, but prevents one borderline post from burning all API
    keys/retries in a single cycle.
    """
    keys = gemini_key_order()
    limit = GEMINI_MAX_KEYS_PER_OPERATION if max_keys is None else max_keys
    if limit <= 0:
        return keys
    return keys[:limit]

def has_gemini_key_available() -> bool:
    # Free local check only: scans all configured key cooldowns in memory, never calls Gemini.
    return bool(GEMINI_API_KEYS and gemini_key_order_limited(GEMINI_LOCAL_KEY_SWEEP_SIZE))


def gemini_available_keys_for_operation() -> list[tuple[int, str]]:
    """Return every locally-available Gemini key for this operation.

    This performs only an in-memory cooldown sweep over up to
    GEMINI_LOCAL_KEY_SWEEP_SIZE keys. It does not contact Gemini and therefore
    does not spend requests/credit. Real requests are still capped separately by
    GEMINI_MAX_REAL_TRANSLATION_REQUESTS and the max_real_requests argument in
    gemini_translate().
    """
    return gemini_key_order_limited(GEMINI_LOCAL_KEY_SWEEP_SIZE)


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
    logging.warning("⚠️ ג'מיני לא זמין כרגע. הבוט לא ישלח פוסטים בלי תרגום Gemini תקין. סיבה: %s", gemini_error_summary(error))


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


def gemini_translate(text: str, respect_global_cooldown: bool = True, max_real_requests: int = 1) -> str:
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
        "- First decide if this is a real MEN'S football news update connected to one of the allowed clubs or to an Israeli-league club. If not, return an empty string.\n"
        "- Send only reports with concrete news: transfer, contract, injury, squad, appointment, dismissal, official announcement, negotiation, bid, match-relevant update, or a verified factual development.\n"
        "- If it is only a social/atmosphere post, quote, interview sentence, player/coach reaction, meme, congratulation, reaction, Instagram/story screenshot, personal message, vague caption, tribute, joke, opinion or image with no concrete news update, return an empty string.\n"
        "- Interview quotes such as 'X on Y: ...', 'X said...', 'X told...' are usually not news.\n"
        "- Keep an interview/quote only when it is genuinely newsworthy or highly relevant: club president/owner/coach/agent speaking about a star player, contract renewal, future at the club, transfer, injury, official decision, squad call-up, bid, club direction or a major sporting development.\n"
        "- Remove ordinary statistics-only posts unless they contain a real record, official achievement or current news angle.\n"
        "- Block women's football, women's leagues/teams, WNBA/NBA/NFL/UFC/tennis/basketball and every sport that is not men's football.\n"
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
    real_requests_used = 0
    available_keys = gemini_available_keys_for_operation()
    if not available_keys:
        raise RuntimeError("No Gemini key is locally available")
    for index, key in available_keys:
        if real_requests_used >= max(1, max_real_requests):
            break
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{urllib.parse.quote(GEMINI_FAST_MODEL)}:generateContent?key={urllib.parse.quote(key)}"
        )
        try:
            # This is the only line in this loop that spends a Gemini request.
            # The sweep above over all 8 keys is local/cooldown-only and free.
            real_requests_used += 1
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
            logging.warning("⚠️ ג'מיני נכשל עם %s. בדיקת שאר המפתחות היא מקומית וחינמית; בקשות אמיתיות מוגבלות. סיבה: %s", gemini_key_label(index), gemini_error_summary(exc))
            continue
    log_gemini_unavailable(last_error)
    raise RuntimeError(f"Gemini translation failed after {real_requests_used} real request(s): {last_error}")


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


def normalize_exclusive_label(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        prefix = (match.group(1) or "").rstrip()
        return f"{prefix} בלעדי: " if prefix else "בלעדי: "

    pattern = (
        r"(?im)^(\s*(?:[^A-Za-z0-9א-ת\n]*\s*)?)"
        r"(?:אקסקלוסיבי|אקסקלוסיב|אקסלוסיב|exclusive|excl)\s*[-:–—]?\s*"
    )
    text = re.sub(pattern, repl, text)
    text = re.sub(r"(?im)^(\s*(?:[^A-Za-z0-9א-ת\n]*\s*)?)בלעדי\s*[-:–—]\s*", repl, text)
    return text


def normalize_breaking_label(text: str) -> str:
    label = (
        r"שובר\s+שוויון|"
        r"חדשות\s+מרעישות|"
        r"חדשות\s+מתפרצות|"
        r"ידיעה\s+מתפרצת|"
        r"מבזק|"
        r"ברייקינג|"
        r"breaking"
    )
    text = re.sub(rf"(?im)^(\s*(?:[^A-Za-z0-9א-ת\n]*\s*)?)(?:{label})\s*[-:–—]?\s*", r"\1דיווח דרמטי: ", text or "")
    text = re.sub(r"(?im)^(\s*(?:[^A-Za-z0-9א-ת\n]*\s*)?)דיווח\s+דרמטי\s*[-:–—]\s*", r"\1דיווח דרמטי: ", text)
    return text


def final_hebrew_polish(text: str) -> str:
    text = remove_external_links(text)
    text = remove_weird_symbols(text)
    text = normalize_exclusive_label(text)
    text = normalize_breaking_label(text)
    text = re.sub(r"(?im)^\s*(?:אקסקלוסיב|אקסקלוסיבי|אקסלוסיב|אקסקלוסיב-י)\s*[-:–—]?\s*", "בלעדי: ", text)
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
    text = strip_country_code_leftovers_near_flags(text)
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
    text = normalize_exclusive_label(text)
    text = normalize_breaking_label(text)
    text = re.sub(r"(?im)^\s*(?:אקסקלוסיב|אקסקלוסיבי|אקסלוסיב|אקסקלוסיב-י)\s*[-:–—]?\s*", "בלעדי: ", text)
    text = re.sub(r"(?im)^בלעדי\s*[-:–—]\s*", "בלעדי: ", text)
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
    if False and fallback_key in TRANSLATION_CACHE:
        return final_visual_cleanup(preserve_original_country_flags(ai_text or text, preserve_original_emojis(ai_text or text, TRANSLATION_CACHE[fallback_key])))

    if GEMINI_API_KEYS and ai_text:
        if not has_gemini_key_available():
            logging.warning("⏳ ג'מיני לא זמין לפי cooldown מקומי. לא שורף בקשה; הפוסט יישאר לניסיון הבא.")
            raise TranslationUnavailable("Gemini currently unavailable without network check")
        last_error: Exception | None = None
        real_requests_used = 0
        for attempt in range(1, GEMINI_TRANSLATION_ATTEMPTS + 1):
            if real_requests_used >= GEMINI_MAX_REAL_TRANSLATION_REQUESTS:
                logging.warning(
                    "⏳ נעצר אחרי %s בקשות Gemini אמיתיות לתרגום. בדיקות זמינות מקומיות ממשיכות בלי קרדיט; הפוסט יישאר לניסיון הבא.",
                    GEMINI_MAX_REAL_TRANSLATION_REQUESTS,
                )
                break
            if not has_gemini_key_available():
                logging.warning("⏳ אין כרגע מפתח Gemini זמין לפי cooldown מקומי. לא שורף בקשה; הפוסט יישאר לניסיון הבא.")
                break
            try:
                with GEMINI_TRANSLATION_SEMAPHORE:
                    allowed_real_requests = max(1, GEMINI_MAX_REAL_TRANSLATION_REQUESTS - real_requests_used)
                    polished = final_hebrew_polish(gemini_translate(ai_text, respect_global_cooldown=False, max_real_requests=allowed_real_requests))
                    real_requests_used += allowed_real_requests
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
        logging.error("⛔ ג'מיני לא הצליח בתרגום אחרי עד %s בדיקות / עד %s בקשות אמיתיות. הפוסט לא יישלח בלי תרגום ויישאר לניסיון הבא.", GEMINI_TRANSLATION_ATTEMPTS, GEMINI_MAX_REAL_TRANSLATION_REQUESTS)
        raise TranslationUnavailable("Gemini translation failed after all attempts")

    logging.error("No valid Gemini translation. Post will not be sent.")
    raise TranslationUnavailable("Gemini-only translation unavailable")


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


def translate_quoted_text(text: str, force: bool = False) -> str:
    cleaned = clean_before_translation(text)
    if not cleaned:
        return ""
    # Big Gemini saver: quoted posts are usually duplicated context, not the news
    # we publish. By default we do NOT translate them with AI.
    if not force and not TRANSLATE_QUOTED_POSTS:
        logging.info("חיסכון Gemini: ציטוט לא תורגם כי TRANSLATE_QUOTED_POSTS כבוי")
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
    # Never call Gemini for quoted author labels; dictionary/local cleanup is enough.
    translated = apply_phrase_replacements(cleaned, HANDLE_REPLACEMENTS)
    translated = apply_phrase_replacements(translated, TEAM_REPLACEMENTS)
    translated = apply_phrase_replacements(translated, PLAYER_REPLACEMENTS)
    translated = final_hebrew_polish(translated)
    return translated or cleaned



# ====== PLAYER ROLE/POSITION SAFETY FIXES ======
# Gemini/free translators sometimes infer a wrong position from a generic word
# such as “forward”. These deterministic fixes run after translation and before
# sending. Keep this list small and high-confidence.
PLAYER_POSITION_FIXES = (
    (r"חלוץ\s+(?:איברהימה\s+)?קונאטה", "בלם איברהימה קונאטה"),
    (r"(?:איברהימה\s+)?קונאטה,?\s+החלוץ", "איברהימה קונאטה, הבלם"),
    (r"(?:איברהימה\s+)?קונאטה\s+החלוץ", "איברהימה קונאטה הבלם"),
    (r"forward\s+Ibrahima\s+Konat[ée]", "centre-back Ibrahima Konaté"),
)


def fix_known_player_positions(text: str) -> str:
    value = text or ""
    for pattern, replacement in PLAYER_POSITION_FIXES:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    return value

def tidy_translated_text(text: str) -> str:
    text = final_hebrew_polish(normalize_country_flags(html.unescape(text or "").strip()))
    text = fix_known_player_positions(text)
    text = remove_junk_topic_tags(text)
    text = remove_untranslated_arabic_leftovers(text)
    text = re.sub(r"(?im)^\s*(וידאו|וידיאו|וידאו מצורף|וידיאו מצורף|📹\s*וידאו מצורף|📹\s*וידיאו מצורף)\s*$", "", text)
    for handle, replacement in sorted(ATTRIBUTION_HANDLE_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True):
        text = re.sub(rf"(?i)@{re.escape(handle)}\b", replacement, text)
    text = re.sub(r"(?iu)\s*,?\s*(?:אמר|אמרה|אמרו|בראיון|בשיחה|דיבר|דיברה)\s+ל-?@?[A-Za-z0-9_]{3,40}\s*[.!?]?\s*$", "", text)
    text = re.sub(r"(?<!\w)@[A-Za-z0-9_]{3,40}\b", "", text)
    text = re.sub(r"(?iu)\s+(?:אקמילאנ|איי\s*סי\s*מילאן|ACMilan|acmilan)\s*[.!?.,;:]*\s*$", "", text)
    text = re.sub(r"(?iu)\bברייטון\s+(?:אנד|ו)?\s*הוב\s+אלביון\b", "ברייטון", text)
    text = re.sub(r"(?iu)\bברייטון\s+אלביון\b", "ברייטון", text)
    text = re.sub(
        r"(?iu)\b(?:נמצא(?:ים|ות)?|נמצאת|נכלל(?:ים|ות)?|נכללת|נותר(?:ים|ות)?|נותרת)\s+בהרצה(?=\s+(?:כ(?:אופצי(?:ה|ות)|מועמד(?:ים|ות)?)|לתפקיד|למשרת|למאמן|לאימון|ברשימת|במרוץ))",
        lambda match: re.sub(r"\s+בהרצה\b", " בין המועמדים", match.group(0), flags=re.IGNORECASE),
        text,
    )
    text = re.sub(r"(?m)^\s*פריצת דרך\s*:\s*", "התפתחות משמעותית: ", text)
    text = re.sub(r"(?iu)\bבייר\s*04\s+לברקוזן\b", "באייר לברקוזן", text)
    text = re.sub(r"(?iu)\bבאייר\s*04\s+לברקוזן\b", "באייר לברקוזן", text)
    text = re.sub(r"(?iu)\s+לפי\s*[.!?.,;:]*\s*$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = remove_junk_tail_lines(text)
    text = final_visual_cleanup(text)
    return text.strip()


def polish_team_names_with_original_context(post: Post, text: str) -> str:
    value = text or ""
    original = html.unescape("\n".join([post.text or "", post.quoted_text or ""]))
    original_has_tottenham = bool(re.search(r"\bTottenham(?:\s+Hotspur)?\b|טוטנהאם", original, re.IGNORECASE))
    original_has_spurs = bool(re.search(r"\bSpurs\b|ספרס", original, re.IGNORECASE))
    if original_has_tottenham and not original_has_spurs:
        value = re.sub(r"(?iu)\bה?ספרס\b", "טוטנהאם", value)
    return value


def has_meaningful_text(text: str) -> bool:
    cleaned = tidy_translated_text(text)
    cleaned = re.sub(r"[\s\"'׳״.,:;!?()\[\]{}\-–—_]+", "", cleaned)
    return bool(cleaned and cleaned not in {"עדכוןחדש", "newupdate", "update"})


def rtl(text: str) -> str:
    return "\n".join(f"{RTL_MARK}{line}" if line.strip() else line for line in text.splitlines())


def telegram_api(method: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable")
    response = http_post_json(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}", payload, **kwargs)
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
    include_video_link: bool = False,
) -> str:
    translated = tidy_translated_text(translated)
    quoted_translated = tidy_translated_text(quoted_translated)
    translated = polish_team_names_with_original_context(post, translated)
    quoted_translated = polish_team_names_with_original_context(post, quoted_translated)
    display_name = ACCOUNT_DISPLAY_NAMES.get(post.username, post.username)

    safe_account = html.escape(rtl(f"{display_name}:"))
    safe_body = html.escape(rtl(translated or "עדכון חדש"))
    safe_quoted_author = html.escape(rtl(quoted_author_translated))
    safe_quoted_body = html.escape(rtl(f'"{quoted_translated}"')) if quoted_translated else ""
    quote_label = f"<b>{html.escape(rtl('פוסט מצוטט:'))}</b>"
    signature = f'<a href="{html.escape(SIGNATURE_LINK)}">{html.escape(rtl(SIGNATURE_TEXT))}</a>'

    parts = [f"<b>{safe_account}</b>", "", safe_body]

    if safe_quoted_body:
        parts.append("")
        if safe_quoted_author:
            parts.append(quote_label)
            parts.append(safe_quoted_author)
        parts.append(safe_quoted_body)
    parts.extend(["", signature])

    return "\n".join(parts)





# ====== STRICT ALLOWED CLUB FILTER ======
# The bot may publish ONLY posts connected to these clubs or to Israeli-league clubs.
# If an allowed club is mentioned anywhere in the main or quoted text, the post can continue
# to the normal news-quality filter. If no allowed club appears, it is blocked before Gemini.
ALLOWED_CLUB_PATTERNS = (
    # Germany
    r"\b(?:Bayern Munich|FC Bayern|FCBayern|Bayern|FCB|Borussia Dortmund|Dortmund|BVB|Bayer Leverkusen|Leverkusen|B04|Eintracht Frankfurt|Frankfurt|SGE|Stuttgart|VfB Stuttgart)\b",
    r"באיירן(?: מינכן)?|בורוסיה דורטמונד|דורטמונד|באייר לברקוזן|לברקוזן|איינטרכט פרנקפורט|פרנקפורט|שטוטגרט",
    # France
    r"\b(?:Paris Saint-Germain|Paris Saint Germain|PSG|Marseille|Olympique Marseille|OM|Lyon|Olympique Lyon|OL|Lille|LOSC|Lens|RC Lens|RCL|Monaco|AS Monaco|ASM)\b",
    r"פריז סן[- ]?ז'רמן|פ\.ס\.ז|פ.ס.ז|מארסיי|מרסיי|אולימפיק מארסיי|ליון|אולימפיק ליון|ליל|לאנס|מונאקו",
    # Spain
    r"\b(?:Real Madrid|RMA|Barcelona|Barca|Barça|FC Barcelona|Atletico Madrid|Atlético Madrid|Atleti|ATM|Sevilla|Villarreal|Athletic Bilbao|Athletic Club|Real Betis|Betis|Valencia|Real Sociedad|La Real)\b",
    r"ריאל מדריד|ברצלונה|בארסה|אתלטיקו מדריד|סביליה|ויאריאל|אתלטיק בילבאו|בטיס|ריאל בטיס|ולנסיה|ריאל סוסיאדד",
    # England
    r"\b(?:Manchester United|Man United|Man Utd|MUFC|Manchester City|Man City|MCFC|Liverpool|LFC|Chelsea|CFC|Arsenal|AFC|Tottenham|Spurs|THFC|Newcastle United|Newcastle|NUFC|Aston Villa|AVFC|West Ham|West Ham United|WHUFC|Everton|EFC|Brighton|BHAFC)\b",
    r"מנצ'סטר יונייטד|מנצ'סטר סיטי|ליברפול|צ'לסי|ארסנל|טוטנהאם|ספרס|ניוקאסל(?: יונייטד)?|אסטון וילה|ווסטהאם|אברטון|ברייטון",
    # Italy
    r"\b(?:Juventus|Juve|AC Milan|A\.C\. Milan|ACM|Milan|Inter Milan|Internazionale|Inter|Roma|Napoli|Lazio|Atalanta|Fiorentina)\b",
    r"יובנטוס|מילאן|איי סי מילאן|אינטר(?: מילאנו)?|רומא|נאפולי|לאציו|אטאלנטה|אטלנטה|פיורנטינה",
    # Portugal / Netherlands / Belgium / Serbia
    r"\b(?:Porto|FC Porto|Benfica|SL Benfica|Benfica Lisbon|Sporting CP|Sporting Lisbon|Ajax|PSV|PSV Eindhoven|Club Brugge|Red Star Belgrade|Crvena Zvezda)\b",
    r"פורטו|בנפיקה(?: ליסבון)?|ספורטינג(?: ליסבון)?|אייאקס|פ\.ס\.וו|פ.ס.וו|פסוו|קלאב ברוז'|קלאב ברוז|הכוכב האדום",
    # South America / Saudi / Turkey / USA
    r"\b(?:Flamengo|CR Flamengo|Palmeiras|Sao Paulo|São Paulo|Boca Juniors|River Plate|Botafogo|Al Nassr|Al-Nassr|Al Hilal|Al-Hilal|Al Ahli|Al-Ahli|Galatasaray|Fenerbahce|Fenerbahçe|Inter Miami|Inter Miami CF)\b",
    r"פלמנגו|פלמייראס|סאו פאולו|בוקה ג'וניורס|ריבר פלייט|בוטאפוגו|אל[- ]?נאסר|אל[- ]?הילאל|אל[- ]?אהלי|גלאטסראיי|פנרבחצ'ה|אינטר מיאמי",
)

# These allowed clubs are lower-priority for the channel: publish them only when
# the report is final or almost final. If one of the bigger clubs also appears in
# the same report, the bigger-club rule can still allow it.
FINAL_ONLY_ALLOWED_CLUB_PATTERNS = (
    # England
    r"\b(?:Tottenham|Spurs|THFC|Newcastle United|Newcastle|NUFC|Aston Villa|AVFC|West Ham|West Ham United|WHUFC|Everton|EFC|Brighton|BHAFC)\b",
    r"טוטנהאם|ספרס|ניוקאסל(?: יונייטד)?|אסטון וילה|ווסטהאם|אברטון|ברייטון",
    # Spain
    r"\b(?:Sevilla|Villarreal|Athletic Bilbao|Athletic Club|Real Betis|Betis|Valencia|Real Sociedad|La Real)\b",
    r"סביליה|ויאריאל|אתלטיק בילבאו|בטיס|ריאל בטיס|ולנסיה|ריאל סוסיאדד",
    # Italy
    r"\b(?:Roma|Napoli|Lazio|Atalanta|Fiorentina)\b",
    r"רומא|נאפולי|לאציו|אטאלנטה|אטלנטה|פיורנטינה",
    # Germany
    r"\b(?:Bayer Leverkusen|Leverkusen|B04|Eintracht Frankfurt|Frankfurt|SGE|Stuttgart|VfB Stuttgart)\b",
    r"באייר לברקוזן|לברקוזן|איינטרכט פרנקפורט|פרנקפורט|שטוטגרט",
    # France
    r"\b(?:Marseille|Olympique Marseille|OM|Lyon|Olympique Lyon|OL|Lille|LOSC|Lens|RC Lens|RCL|Monaco|AS Monaco|ASM)\b",
    r"מארסיי|מרסיי|אולימפיק מארסיי|ליון|אולימפיק ליון|ליל|לאנס|מונאקו",
    # Rest of Europe
    r"\b(?:Porto|FC Porto|Benfica|SL Benfica|Benfica Lisbon|Sporting CP|Sporting Lisbon|Ajax|PSV|PSV Eindhoven|Galatasaray|Fenerbahce|Fenerbahçe|Club Brugge|Red Star Belgrade|Crvena Zvezda)\b",
    r"פורטו|בנפיקה(?: ליסבון)?|ספורטינג(?: ליסבון)?|אייאקס|פ\.ס\.וו|פ.ס.וו|פסוו|גלאטסראיי|פנרבחצ'ה|קלאב ברוז'|קלאב ברוז|הכוכב האדום",
    # South America
    r"\b(?:Flamengo|CR Flamengo|Palmeiras|Sao Paulo|São Paulo|Boca Juniors)\b",
    r"פלמנגו|פלמייראס|סאו פאולו|בוקה ג'וניורס",
)

FINAL_OR_NEAR_FINAL_PATTERNS = (
    r"\b(?:official|confirmed|announced|announcement|club statement|signed|has signed|will sign|set to sign|set to join|here we go|done deal|deal done|deal agreed|agreement reached|full agreement|verbal agreement|agreed in principle|medical booked|medical tests|medical|documents signed|contracts signed|completed|sealed|final details|final stages|final steps|closing stages|one step away|imminent|expected to be completed|approved|green light|accepted bid|bid accepted)\b",
    r"רשמי|אושר|אישר|אישרה|הודיע|הודיעה|הודעה רשמית|חתם|חתמה|יחתום|תחתום|צפוי לחתום|צפויה לחתום|צפוי להצטרף|צפויה להצטרף|הנה זה קורה|עסקה סגורה|העסקה סגורה|העסקה הושלמה|העסקה סוכמה|סוכמה העסקה|סיכום מלא|הושג סיכום|סיכום בעל פה|סוכמו התנאים|בדיקות רפואיות|נקבעו בדיקות|מסמכים נחתמו|חוזים נחתמו|הושלם|הושלמה|נסגר|נסגרה|פרטים אחרונים|בשלבים האחרונים|צעד אחד מסגירה|קרוב לסגירה|קרובה לסגירה|מיידי|צפוי להיסגר|אור ירוק|הצעה התקבלה|ההצעה התקבלה",
)

FINAL_ONLY_STRICT_PATTERNS = (
    r"\b(?:official|confirmed|announced|announcement|club statement|signed|has signed|done deal|deal done|deal agreed|agreement reached|full agreement|documents signed|contracts signed|completed|sealed|approved|accepted bid|bid accepted)\b",
    r"׳¨׳©׳׳™|׳׳•׳©׳¨|׳׳™׳©׳¨|׳׳™׳©׳¨׳”|׳”׳•׳“׳™׳¢|׳”׳•׳“׳™׳¢׳”|׳”׳•׳“׳¢׳” ׳¨׳©׳׳™׳×|׳—׳×׳|׳—׳×׳׳”|׳”׳¢׳¡׳§׳” ׳¡׳’׳•׳¨׳”|׳¢׳¡׳§׳” ׳¡׳’׳•׳¨׳”|׳”׳¢׳¡׳§׳” ׳”׳•׳©׳׳׳”|׳”׳¢׳¡׳§׳” ׳¡׳•׳›׳׳”|׳¡׳•׳›׳׳” ׳”׳¢׳¡׳§׳”|׳¡׳™׳›׳•׳ ׳׳׳|׳”׳•׳©׳’ ׳¡׳™׳›׳•׳|׳׳¡׳׳›׳™׳ ׳ ׳—׳×׳׳•|׳—׳•׳–׳™׳ ׳ ׳—׳×׳׳•|׳”׳•׳©׳׳|׳”׳•׳©׳׳׳”|׳ ׳¡׳’׳¨|׳ ׳¡׳’׳¨׳”|׳”׳¦׳¢׳” ׳”׳×׳§׳‘׳׳”|׳”׳”׳¦׳¢׳” ׳”׳×׳§׳‘׳׳”",
)

ISRAELI_LEAGUE_PATTERNS = (
    r"\b(?:Israeli Premier League|Ligat HaAl|Ligat Ha'al|Israel Premier League|Israel league|Israeli league|Liga Leumit|Israel State Cup|Toto Cup)\b",
    r"ליגת העל|ליגת ווינר|ליגה לאומית|הליגה הישראלית|גביע המדינה|גביע הטוטו|כדורגל ישראלי",
    r"\b(?:Maccabi Tel Aviv|Maccabi Haifa|Hapoel Be'er Sheva|Hapoel Beer Sheva|Beitar Jerusalem|Beitar|Hapoel Tel Aviv|Maccabi Netanya|Bnei Sakhnin|Maccabi Bnei Reineh|Ironi Tiberias|Hapoel Haifa|Hapoel Jerusalem|Maccabi Petah Tikva|Hapoel Petah Tikva|MS Ashdod|Ashdod|Ironi Kiryat Shmona|Hapoel Hadera|Hapoel Raanana|Hapoel Ramat Gan|Bnei Yehuda|Hapoel Acre|Hapoel Kfar Saba|Hapoel Nof HaGalil|Hapoel Umm al-Fahm|Kafr Qasim|Sektzia Nes Tziona)\b",
    r'מכבי תל אביב|מכבי חיפה|הפועל באר שבע|בית"ר ירושלים|ביתר ירושלים|הפועל תל אביב|מכבי נתניה|בני סכנין|מכבי בני ריינה|עירוני טבריה|הפועל חיפה|הפועל ירושלים|מכבי פתח תקווה|הפועל פתח תקווה|מ.ס אשדוד|מועדון ספורט אשדוד|עירוני קריית שמונה|קריית שמונה|הפועל חדרה|הפועל רעננה|הפועל רמת גן|בני יהודה|הפועל עכו|הפועל כפר סבא|נוף הגליל|אום אל פאחם|כפר קאסם|נס ציונה',
)

# Top-70 men's national teams by current FIFA ranking source + Israel.
# This lets reports about national teams/country squads pass even when no club is named.
ALLOWED_NATIONAL_TEAM_PATTERNS = (
    r"\b(?:France|Spain|Argentina|England|Portugal|Brazil|Netherlands|Morocco|Belgium|Germany|Croatia|Italy|Colombia|Senegal|Mexico|USA|United States|Uruguay|Japan|Switzerland|Denmark|Iran|Türkiye|Turkey|Ecuador|Austria|South Korea|Korea Republic|Nigeria|Australia|Algeria|Egypt|Canada|Norway|Ukraine|Panama|Côte d'Ivoire|Ivory Coast|Poland|Russia|Wales|Sweden|Serbia|Paraguay|Czechia|Czech Republic|Hungary|Scotland|Tunisia|Cameroon|DR Congo|Greece|Slovakia|Venezuela|Uzbekistan|Costa Rica|Mali|Peru|Chile|Qatar|Romania|Iraq|Slovenia|Ireland|South Africa|Saudi Arabia|Burkina Faso|Jordan|Albania|Bosnia and Herzegovina|Bosnia & Herzegovina|Honduras|North Macedonia|United Arab Emirates|UAE|Cape Verde|Northern Ireland|Israel)\b",
    r"\b(?:national team|men's national team|senior national team|squad|call(?:ed)? up|international duty|World Cup|FIFA World Cup|EURO|Euros|Euro 202[0-9]|Copa America|AFCON|Asian Cup|CONCACAF Gold Cup|Nations League)\b",
    r"נבחרת|הנבחרת|סגל|זימון|זומן|זומנו|מוקדמות|מונדיאל|גביע העולם|יורו|קופה אמריקה|אליפות אפריקה|גביע אסיה|ליגת האומות",
    r"צרפת|ספרד|ארגנטינה|אנגליה|פורטוגל|ברזיל|הולנד|מרוקו|בלגיה|גרמניה|קרואטיה|איטליה|קולומביה|סנגל|מקסיקו|ארצות הברית|אורוגוואי|אורוגואי|יפן|שווייץ|שוויץ|דנמרק|איראן|טורקיה|אקוודור|אוסטריה|דרום קוריאה|ניגריה|אוסטרליה|אלג'יריה|מצרים|קנדה|נורבגיה|אוקראינה|פנמה|חוף השנהב|פולין|רוסיה|וויילס|ויילס|שבדיה|סרביה|פרגוואי|צ'כיה|הונגריה|סקוטלנד|תוניסיה|קמרון|קונגו|יוון|סלובקיה|ונצואלה|אוזבקיסטן|קוסטה ריקה|מאלי|פרו|צ'ילה|קטאר|רומניה|עיראק|סלובניה|אירלנד|דרום אפריקה|ערב הסעודית|בורקינה פאסו|ירדן|אלבניה|בוסניה|הונדורס|צפון מקדוניה|איחוד האמירויות|כף ורדה|צפון אירלנד|ישראל",
)

NATIONAL_TEAM_CONTEXT_PATTERNS = (
    r"\b(?:national team|men's national team|senior national team|squad|called up|call-up|call up|international duty|World Cup|FIFA World Cup|EURO|Euros|Copa America|AFCON|Asian Cup|Nations League|qualifiers?)\b",
    r"נבחרת|הנבחרת|סגל|זימון|זומן|זומנו|מוקדמות|מונדיאל|גביע העולם|יורו|קופה אמריקה|אליפות אפריקה|גביע אסיה|ליגת האומות",
)


OTHER_SPORT_BLOCK_PATTERNS = (
    r"\b(?:NBA|WNBA|NFL|MLB|NHL|UFC|MMA|Formula 1|F1|tennis|basketball|baseball|hockey|handball|volleyball|rugby|cricket|golf|boxing|cycling|MotoGP|Olympics)\b",
    r"כדורסל|NBA|WNBA|פוטבול אמריקאי|בייסבול|הוקי|טניס|פורמולה|פורמולה 1|UFC|MMA|אגרוף|רוגבי|כדוריד|כדורעף|קריקט|גולף|אופניים|אולימפי|אולימפיאדה",
)

YOUTH_ACADEMY_BLOCK_PATTERNS = (
    r"\b(?:academy|youth team|youth sides?|youth football|U-?15|U-?16|U-?17|U-?18|U-?19|U-?20|U-?21|U-?23|under[- ]?(?:15|16|17|18|19|20|21|23)|juvenil|primavera|reserve team|reserves|B team|underage)\b",
    r"מחלקת נוער|קבוצת נוער|נוער|נערים|נערים א|נערים ב|ילדים|אקדמיה|קבוצת מילואים|מילואים|עד גיל\s*(?:15|16|17|18|19|20|21|23)|U ?(?:15|16|17|18|19|20|21|23)",
)


def is_youth_or_academy_post(post: Post) -> bool:
    cleaned = post_filter_text(post)
    return _matches_any(YOUTH_ACADEMY_BLOCK_PATTERNS, cleaned)


FOOTBALL_CONTEXT_ALLOW_PATTERNS = (
    r"\b(?:football|soccer|club|manager|head coach|coach|player|goalkeeper|defender|midfielder|winger|striker|forward|transfer|loan|signing|contract|match|squad|injury)\b",
    r"כדורגל|מועדון|מאמן|שחקן|שוער|בלם|מגן|קשר|כנף|חלוץ|העברה|השאלה|חתימה|חוזה|סגל|משחק|פציעה",
)


def post_filter_text(post: Post) -> str:
    raw_text = html.unescape("\n".join([post.text or "", post.quoted_text or "", post.quoted_author or "", post.link or ""]))
    raw_text = normalize_country_flags(raw_text) if "normalize_country_flags" in globals() else raw_text
    raw_text = remove_external_links(raw_text) if "remove_external_links" in globals() else raw_text
    return raw_text


def contains_allowed_national_team(post: Post) -> bool:
    cleaned = post_filter_text(post)
    return _matches_any(ALLOWED_NATIONAL_TEAM_PATTERNS, cleaned) and _matches_any(NATIONAL_TEAM_CONTEXT_PATTERNS, cleaned)


def contains_allowed_club_or_israeli_league(post: Post) -> bool:
    cleaned = post_filter_text(post)
    return (
        _matches_any(ALLOWED_CLUB_PATTERNS, cleaned)
        or _matches_any(ISRAELI_LEAGUE_PATTERNS, cleaned)
        or contains_allowed_national_team(post)
    )


def contains_tracked_club_or_israeli_league(post: Post) -> bool:
    """User club gate: tier 1, tier 2/final-only, Israeli league or allowed national teams."""
    cleaned = post_filter_text(post)
    return (
        _matches_any(ALLOWED_CLUB_PATTERNS, cleaned)
        or _matches_any(FINAL_ONLY_ALLOWED_CLUB_PATTERNS, cleaned)
        or _matches_any(ISRAELI_LEAGUE_PATTERNS, cleaned)
        or contains_allowed_national_team(post)
    )


def is_clear_player_departure_post(post: Post) -> bool:
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    return contains_allowed_club_or_israeli_league(post) and _matches_any(CLEAR_PLAYER_DEPARTURE_PATTERNS, cleaned)


def is_other_sport_post(post: Post) -> bool:
    cleaned = post_filter_text(post)
    if not _matches_any(OTHER_SPORT_BLOCK_PATTERNS, cleaned):
        return False
    # Do not block if the same text is clearly football and has an allowed club.
    # This prevents false blocks from generic words, but blocks NBA/NFL/etc. noise.
    return not (_matches_any(FOOTBALL_CONTEXT_ALLOW_PATTERNS, cleaned) and contains_allowed_club_or_israeli_league(post))


# ====== FOOTBALL SMART RELEVANCE FILTER ======
# Network-free editor gate. It runs before Gemini/video/Telegram and blocks low-value
# football noise without relying on a manually-maintained player list.
# Core rule: judge by club relevance + report strength + role type, not by player names.

POPULAR_OR_RECENT_UCL_CLUB_PATTERNS = (
    # All current/recent top-5 league clubs and clubs promoted/back to a top league are treated like popular clubs.
    # This prevents important reports from Premier League / La Liga / Serie A / Bundesliga / Ligue 1 sides being blocked as "small".
    r"\b(?:Brighton|Bournemouth|Brentford|Fulham|Wolves|Everton|West Ham|Crystal Palace|Nottingham Forest|Leeds|Sunderland|Leicester|Southampton|Burnley|Sheffield United|Ipswich|Luton|Aston Villa|Newcastle)\b",
    r"\b(?:Genoa|Cagliari|Como|Lecce|Empoli|Udinese|Sassuolo|Bologna|Torino|Monza|Verona|Parma|Sampdoria|Pisa|Cremonese|Salernitana)\b",
    r"\b(?:Getafe|Osasuna|Mallorca|Rayo Vallecano|Alaves|Alavés|Celta Vigo|Espanyol|Levante|Leganes|Leganés|Granada|Las Palmas|Valladolid|Girona)\b",
    r"\b(?:Nantes|Toulouse|Montpellier|Reims|Metz|Nice|Rennes|Strasbourg|Lens|Brest|Auxerre|Angers|Lorient|Paris FC|Saint-Étienne|Saint Etienne)\b",
    r"\b(?:Bochum|Augsburg|Mainz|Freiburg|Heidenheim|St Pauli|Werder Bremen|Wolfsburg|Union Berlin|Hoffenheim|Hamburg|Koln|Köln|Darmstadt|Holstein Kiel)\b",
    r"ברייטון|בורנמות|ברנטפורד|פולהאם|וולבס|אברטון|ווסטהאם|קריסטל פאלאס|נוטינגהאם|לידס|סנדרלנד|לסטר|סאות'המפטון|ברנלי|אסטון וילה|ניוקאסל",
    r"גנואה|קליארי|קומו|לצ'ה|אמפולי|אודינזה|ססואולו|בולוניה|טורינו|מונצה|ורונה|פארמה|סמפדוריה|פיזה|קרמונזה",
    r"חטאפה|אוססונה|מיורקה|ראיו|אלאבס|סלטה|אספניול|לבאנטה|לגאנס|גרנאדה|לאס פאלמאס|ויאדוליד|ג'ירונה",
    r"נאנט|טולוז|מונפלייה|ריימס|מץ|ניס|רן|שטרסבורג|לאנס|ברסט|אוקזר|אנז'ה|לוריין|פאריס FC|סנט אטיין",
    r"בוכום|אוגסבורג|מיינץ|פרייבורג|היידנהיים|סט פאולי|ורדר ברמן|וולפסבורג|אוניון ברלין|הופנהיים|המבורג|קלן|דרמשטאדט|הולשטיין קיל",
    r"\b(?:promoted|promotion|newly promoted|back in|back to|return to|returns to)\s+(?:the\s+)?(?:Premier League|La Liga|Serie A|Bundesliga|Ligue 1)\b",
    r"\b(?:Premier League|La Liga|Serie A|Bundesliga|Ligue 1)\s+(?:newcomers|side|club|team)\b",
    r"עלתה\s+ל(?:פרמייר ליג|לה ליגה|סרייה א|בונדסליגה|ליגה 1)|חזרה\s+ל(?:פרמייר ליג|לה ליגה|סרייה א|בונדסליגה|ליגה 1)",
    # England / global Premier League brands
    r"\b(?:Manchester United|Man United|Man Utd|Manchester City|Man City|Liverpool|Arsenal|Chelsea|Tottenham|Spurs|Newcastle|Aston Villa)\b",
    # Spain
    r"\b(?:Real Madrid|Barcelona|Barca|Barça|Atletico Madrid|Atlético Madrid)\b",
    # Germany / France
    r"\b(?:Bayern Munich|Bayern|Borussia Dortmund|Dortmund|Bayer Leverkusen|Leverkusen|PSG|Paris Saint-Germain|Marseille|Monaco|Lyon|Lille)\b",
    # Italy / Portugal / Netherlands
    r"\b(?:Juventus|Inter Milan|Inter|AC Milan|Milan|Napoli|Roma|Atalanta|Lazio|Benfica|Porto|Sporting CP|Sporting Lisbon|Ajax|PSV|Feyenoord)\b",
    # Globally relevant non-European / high-traffic clubs
    r"\b(?:Al Hilal|Al-Hilal|Al Ittihad|Al-Ittihad|Al Nassr|Al-Nassr|Inter Miami)\b",
    # Hebrew equivalents
    r"ריאל מדריד|ברצלונה|בארסה|אתלטיקו מדריד|מנצ'סטר יונייטד|מנצ'סטר סיטי|ליברפול|ארסנל|צ'לסי|טוטנהאם|ניוקאסל|אסטון וילה",
    r"באיירן|דורטמונד|לברקוזן|פ\.ס\.ז|פריז סן ז'רמן|מארסיי|מונאקו|ליון|ליל",
    r"יובנטוס|אינטר|מילאן|נאפולי|רומא|אטאלנטה|לאציו|בנפיקה|פורטו|ספורטינג|אייאקס|פ.ס.וו|פיינורד",
    r"אל[- ]?הילאל|אל[- ]?איתיחאד|אל[- ]?נאסר|אינטר מיאמי",
)


# For backroom/admin appointments, user wants ONLY the absolute biggest clubs:
# Barcelona/Barça and Real Madrid. Other clubs remain popular for player/coach/transfer news,
# but NOT for sporting/technical director or similar appointments.
ELITE_ADMIN_CLUB_PATTERNS = (
    r"\b(?:Real Madrid|Barcelona|Barca|Barça)\b",
    r"ריאל מדריד|ברצלונה|בארסה",
)

# Smaller/mid-table clubs are NOT blocked automatically. They only get filtered when
# the report is weak, administrative, or has no connection to a popular club.
LOW_INTEREST_CLUB_PATTERNS = (
    # Do NOT put top-5-league clubs here. They are handled as popular clubs above.
    # Keep this list only for genuinely small/non-top-5/non-UCL contexts if you add any later.
    r"\b(?:Copenhagen|FC Copenhagen|Kobenhavn|Kobenhavn|Al Ettifaq|Al-Ettifaq|Ettifaq|Al Shabab|Al-Shabab|Al Taawoun|Al-Taawoun|Al Fateh|Al-Fateh|Al Riyadh|Al-Riyadh|Damac|Al Khaleej|Al-Khaleej|Al Raed|Al-Raed|Al Okhdood|Al-Okhdood)\b",
    r"\b(?:FC Vaduz|Vaduz|Dudelange|Lincoln Red Imps|Flora Tallinn|Klaksvik|KÍ Klaksvík|Ballkani)\b",
    r"ואדוץ|דודלאנג'|לינקולן רד אימפס|פלורה טאלין|קלאקסוויק|בלקאני",
)

LOW_INTEREST_GERMAN_UPDATE_PATTERNS = (
    r"\b(?:RB Leipzig|Leipzig|RBL|SV Elversberg|Elversberg|Augsburg|Mainz|Freiburg|Heidenheim|St Pauli|Werder Bremen|Wolfsburg|Union Berlin|Hoffenheim|Hamburg|Koln|Köln|Bochum)\b",
    r"לייפציג|אלברסברג|אוגסבורג|מיינץ|פרייבורג|היידנהיים|סט פאולי|ורדר ברמן|וולפסבורג|אוניון ברלין|הופנהיים|המבורג|קלן|בוכום",
)

LOW_INTEREST_GERMAN_DESTINATION_PATTERNS = (
    r"\b(?:join|joining|sign for|signing for|move to|moving to|loan to|loaned to|headed to|set for)\s+(?:SV\s+)?(?:Elversberg|RB Leipzig|Leipzig|RBL|Augsburg|Mainz|Freiburg|Heidenheim|St Pauli|Werder Bremen|Wolfsburg|Union Berlin|Hoffenheim|Hamburg|Koln|Köln|Bochum)\b",
    r"\b(?:SV\s+)?(?:Elversberg|RB Leipzig|Leipzig|RBL|Augsburg|Mainz|Freiburg|Heidenheim|St Pauli|Werder Bremen|Wolfsburg|Union Berlin|Hoffenheim|Hamburg|Koln|Köln|Bochum)\b.{0,80}\b(?:on loan|loan deal|permanent transfer|transfer)\b",
    r"(?:מצטרף|יצטרף|עובר|יעבור|מושאל|יושאל|יחתום|קרוב להצטרף|צפוי להצטרף)\s+ל(?:-|\s)?(?:לייפציג|אלברסברג|אוגסבורג|מיינץ|פרייבורג|היידנהיים|סט פאולי|ורדר ברמן|וולפסבורג|אוניון ברלין|הופנהיים|המבורג|קלן|בוכום)",
)

LOW_INTEREST_STAY_RENEWAL_PATTERNS = (
    r"\b(?:agreement reached|agreed|set to sign|will sign|signs|signed)\b.{0,100}\b(?:new contract|contract extension|renewal)\b.{0,140}\b(?:with|at)\s+(?:Twente|FC Twente|PSV|AZ Alkmaar|Utrecht|Feyenoord|Anderlecht|Genk|Gent|Basel|Young Boys|Salzburg|Celtic|Rangers)\b",
    r"\b(?:Twente|FC Twente|PSV|AZ Alkmaar|Utrecht|Feyenoord|Anderlecht|Genk|Gent|Basel|Young Boys|Salzburg|Celtic|Rangers)\b.{0,140}\b(?:new contract|contract extension|renewal|decides? to stay|stays?|remain|remains)\b",
    r"\b(?:Barcelona|Barca|Barça|Real Madrid|PSV|Eintracht|Frankfurt|Manchester United|Man United|Liverpool|Arsenal|Chelsea|Bayern|PSG|Juventus|Milan|Inter)\b.{0,180}\b(?:interested|wanted|keen|monitoring)\b.{0,180}\b(?:decides? to stay|stays?|remain|remains|new contract|contract extension|renewal)\b",
    r"(?:הושג סיכום|סיכם|סיכמה|יחתום|חתם|חתמה).{0,100}(?:חוזה חדש|הארכת חוזה).{0,140}(?:טוונטה|פ\.ס\.וו|פסוו|אלקמאר|פיינורד|אנדרלכט|גנק|גנט|באזל|יאנג בויז|זלצבורג|סלטיק|ריינג'רס)",
    r"(?:ברצלונה|בארסה|ריאל מדריד|פ\.ס\.וו|פסוו|איינטרכט|פרנקפורט|מנצ'סטר יונייטד|ליברפול|ארסנל|צ'לסי|באיירן|פ\.ס\.ז|יובנטוס|מילאן|אינטר).{0,180}(?:התעניינה|התעניינו|מעוניינת|מעוניינות).{0,180}(?:נשאר|נשארת|יישאר|תישאר|חוזה חדש|הארכת חוזה)",
)

LOW_INTEREST_NON_EUROPE_CONTRACT_PATTERNS = (
    r"\b(?:Club Tijuana|Tijuana|Xolos|Santos Laguna|Pachuca|Monterrey|Tigres|Club America|América|Chivas|Pumas)\b.{0,180}\b(?:contract|new contract|signs?|signed|shirt number|number 10|release clause|clause)\b",
    r"\b(?:contract|new contract|signs?|signed|shirt number|number 10|release clause|clause)\b.{0,180}\b(?:Club Tijuana|Tijuana|Xolos|Santos Laguna|Pachuca|Monterrey|Tigres|Club America|América|Chivas|Pumas)\b",
    r"(?:קלאב\s+)?טיחואנה.{0,180}(?:חוזה|חתם|חתימה|חולצת\s+מספר|מספר\s+10|סעיף\s+שחרור)",
    r"(?:חוזה|חתם|חתימה|חולצת\s+מספר|מספר\s+10|סעיף\s+שחרור).{0,180}(?:קלאב\s+)?טיחואנה",
)

# Non-playing staff roles. These are usually not urgent unless attached to a major club.
ADMIN_OR_BACKROOM_ROLE_PATTERNS = (
    r"\b(?:sporting director|sports director|technical director|technical manager|director of football|football director|head of recruitment|chief scout|recruitment director|technical area|technical chief|director deportivo|direttore sportivo|directeur sportif|academy director|youth director|club secretary|consultant|advisor|scout|head scout|data director|performance director|executive director|chief operating officer|chief operations officer|operations director|COO|CEO|chairman|president)\b",
    r"מנהל\s+(?:ספורטיבי|מקצועי|טכני|תפעול|תפעולי|אקדמיה|נוער|גיוס|סקאוטינג|נתונים|ביצועים)|המנהל\s+(?:הספורטיבי|המקצועי|הטכני|התפעולי)|ראש\s+(?:מערך\s+)?(?:הסקאוטינג|גיוס|אקדמיה|תפעול)|סקאוט|יועץ|מזכיר\s+המועדון|מנהל\s+הכדורגל|סמנכ\"ל\s+תפעול|מנהל\s+תפעול\s+ראשי|יו\"ר|נשיא|מנכ\"ל",
)

KNOWN_ADMIN_PERSON_PATTERNS = (
    r"\b(?:Damien Comolli|Comolli|Cristiano Giuntoli|Giuntoli|Monchi|Ramon Planes|Ramón Planes|Luis Campos|Campos|Deco|Jordi Cruyff|Mateu Alemany|Alemany|Michael Edwards|Hugo Viana|Txiki Begiristain|Begiristain|Hasan Salihamidzic|Salihamidzic)\b",
    r"דמיאן\s+קומולי|קומולי|כריסטיאנו\s+ג'ונטולי|ג'ונטולי|מונצ'י|רמון\s+פלאנס|לואיס\s+קמפוס|דקו|ג'ורדי\s+קרויף|מתאו\s+אלמאני|מייקל\s+אדוארדס|הוגו\s+ויאנה|צ'יקי\s+בגיריסטיין|חסן\s+סליהמידז'יץ'",
)

ADMIN_PERSON_EXIT_OR_STATUS_PATTERNS = (
    r"\b(?:story|chapter|time|spell|tenure|future)\b.{0,80}\b(?:is over|over|ended|ends|finished|done|leaves?|leaving|steps? down|resigns?|terminated|termination)\b",
    r"\b(?:leaves?|leaving|steps? down|resigns?|terminated|termination|part ways|departure)\b.{0,80}\b(?:role|position|club|project|chapter|story)\b",
    r"(?:הסיפור|הפרק|התקופה|הקדנציה|העתיד).{0,80}(?:הסתיים|הסתיימה|נגמר|נגמרה|תם|תמה|עזב|עוזב|יעזוב)",
    r"(?:עוזב|עזב|יעזוב|התפטר|סיים את דרכו|סיום דרכו|היפרדות|פרידה).{0,80}(?:תפקיד|מועדון|פרויקט|הסיפור|התקופה|הקדנציה)",
)

WEAK_INTEREST_PATTERNS = (
    r"\b(?:interest|interested|monitoring|tracking|keeping tabs|admire|considering|could|might|eyeing|linked with|on the list|shortlist|inquired|enquired|exploring|watching|following)\b",
    r"מתעניין|מתעניינת|הביע(?:ו)? עניין|עוקב(?:ת|ים)?|שוקל(?:ת|ים)?|עשוי|יכולה|מקושר|ברשימה|ברשימת המועמדים|בירר(?:ה|ו)?|בודק(?:ת|ים)?|נמצא במעקב",
)

# Weak/quote reports around big clubs should pass only when the text itself is
# connected to transfer/future mechanics. This keeps items like "his son says
# he can return to Napoli after the option was not activated", but blocks vague
# player ideas/lists/admiration with no concrete transfer angle.
TRANSFER_LINKED_WEAK_PATTERNS = (
    r"\b(?:wants? to join|would like to join|keen to join|open to joining|dreams? of joining|wants? to return|could return|can return|expected to return|set to return|return to|back to|wants? to leave|could leave|future|transfer|move|signing|sign|join|loan|option to buy|buy option|purchase option|clause|release clause|bid|offer|proposal|talks|negotiations|agreement|medical|deal)\b",
    r"רוצה\s+לעבור|רוצה\s+להצטרף|מעוניין\s+לעבור|מעוניין\s+להצטרף|חולם\s+לעבור|חולם\s+להצטרף|רוצה\s+לחזור|יכול\s+לחזור|יכולה\s+לחזור|צפוי\s+לחזור|עשוי\s+לחזור|חזרה\s+ל|לחזור\s+ל|רוצה\s+לעזוב|יכול\s+לעזוב|עתידו|עתיד\s+ב|מעבר|העברה|חתימה|יחתום|יצטרף|השאלה|אופציית\s+רכישה|אופציית\s+הקנייה|לא\s+הפעיל(?:ה|ו)?\s+את\s+אופציית\s+הרכישה|סעיף\s+שחרור|הצעה|שיחות|מו\"מ|סיכום|בדיקות\s+רפואיות|עסקה",
)

VAGUE_PLAYER_IDEA_PATTERNS = (
    r"\b(?:idea|option|profile|candidate|shortlist|on the list|monitoring|tracking|watching|following|admire|appreciate|considering|exploring)\b",
    r"רעיון|אופציה|פרופיל|מועמד|ברשימה|ברשימת\s+המועמדים|עוקב(?:ת|ים)?|נמצא\s+במעקב|מעריכ(?:ה|ים)|שוקל(?:ת|ים)?|בודק(?:ת|ים)?",
)

STRONG_PLAYER_MOVE_PATTERNS = (
    r"\b(?:official|confirmed|here we go|deal agreed|agreement reached|full agreement|verbal agreement|set to sign|set to join|close to signing|close to joining|medical|medical tests|contract signed|signs|joins|completed|done deal|bid accepted|release clause activated|loan agreed|permanent transfer|free agent)\b",
    r"רשמי|אושר|הנה זה קורה|העסקה סוכמה|הושג סיכום|סיכום מלא|סיכום בעל פה|צפוי לחתום|צפוי להצטרף|קרוב לחתימה|קרוב להצטרף|בדיקות רפואיות|החוזה נחתם|חתם|יחתום|מצטרף|עסקה סגורה|ההצעה התקבלה|סעיף שחרור|שחקן חופשי|העברה קבועה|השאלה סוכמה",
)

CLEAR_PLAYER_DEPARTURE_PATTERNS = (
    r"\b(?:leaves?|leaving|left|departs?|departing|released|out of contract|contract expires?|free agent|free transfer)\b",
    r"עוזב|עוזבת|עזב|עזבה|יעזוב|תעזוב|שוחרר|שוחררה|משוחרר|מסיים חוזה|סיים חוזה|תום חוזה|שחקן חופשי|העברה חופשית",
)

COACH_IMPORTANT_PATTERNS = (
    r"\b(?:head coach|manager|coach|appointed|set to be appointed|sacked|fired|dismissed|resigned|leaves role|new manager|new head coach)\b",
    r"מאמן|מאמן ראשי|מונה|ימונה|צפוי להתמנות|פוטר|התפטר|עזב את תפקידו|מאמן חדש",
)

BIG_CLUB_CONTEXT_PATTERNS = (
    # A small club can still be relevant if the player is described through a big club.
    r"\b(?:former|ex|outgoing|current)\s+(?:Real Madrid|Barcelona|Barca|Barça|Liverpool|Manchester United|Man United|Manchester City|Man City|Arsenal|Chelsea|Tottenham|Bayern|PSG|Juventus|Inter|Milan|Napoli|Roma)\b",
    r"\b(?:Real Madrid|Barcelona|Barca|Barça|Liverpool|Manchester United|Man United|Manchester City|Man City|Arsenal|Chelsea|Tottenham|Bayern|PSG|Juventus|Inter|Milan|Napoli|Roma)\s+(?:defender|centre-back|center-back|midfielder|forward|striker|winger|goalkeeper|player|star)\b",
    r"(?:שחקן|בלם|קשר|חלוץ|כנף|שוער)\s+(?:ריאל מדריד|ברצלונה|ליברפול|מנצ'סטר יונייטד|מנצ'סטר סיטי|ארסנל|צ'לסי|טוטנהאם|באיירן|פ\.ס\.ז|יובנטוס|אינטר|מילאן|נאפולי|רומא)",
    r"(?:לשעבר|אקס|שחקן חופשי מ|עוזב את)\s+(?:ריאל מדריד|ברצלונה|ליברפול|מנצ'סטר יונייטד|מנצ'סטר סיטי|ארסנל|צ'לסי|טוטנהאם|באיירן|פ\.ס\.ז|יובנטוס|אינטר|מילאן|נאפולי|רומא)",
)


# Level 1: truly big clubs. For these, even early transfer-rumour language
# such as interested/monitoring/appreciate is worth sending from the trusted writers.
# If a report mentions both a big club and a small club, this big-club signal wins.
BIG_CLUB_RUMOR_PATTERNS = (
    r"\b(?:Real Madrid|Barcelona|Barca|Barça|Atletico Madrid|Atlético Madrid|Manchester United|Man United|Man Utd|Manchester City|Man City|Liverpool|Arsenal|Chelsea|Tottenham|Spurs|Bayern Munich|Bayern|Borussia Dortmund|Dortmund|Bayer Leverkusen|Leverkusen|PSG|Paris Saint-Germain|Juventus|Inter Milan|Inter|AC Milan|Milan|Napoli|Roma)\b",
    r"ריאל מדריד|ברצלונה|בארסה|אתלטיקו מדריד|מנצ'סטר יונייטד|מנצ'סטר סיטי|ליברפול|ארסנל|צ'לסי|טוטנהאם|באיירן|דורטמונד|לברקוזן|פ\.ס\.ז|פריז סן ז'רמן|יובנטוס|אינטר|מילאן|נאפולי|רומא",
)

# Transfer/future language broad enough to catch quotes like "his son wants Napoli",
# but still specific enough to block ordinary post-match interviews.
TRANSFER_OR_FUTURE_PATTERNS = (
    r"\b(?:transfer|move|join|joining|sign|signing|leave|leaving|return|back to|future|loan|buy option|option to buy|purchase option|clause|release clause|bid|offer|proposal|talks|negotiations|agreement|medical|deal|contract|free agent|wants? to|would like to|keen to|open to|dreams? of)\b",
    r"העברה|מעבר|לעבור|להצטרף|חתימה|יחתום|יחתמו|יעזוב|לעזוב|לחזור|חזרה ל|עתידו|עתיד ב|השאלה|אופציית רכישה|אופציית הקנייה|סעיף שחרור|הצעה|שיחות|מו\"מ|משא ומתן|סיכום|בדיקות רפואיות|עסקה|חוזה|שחקן חופשי|רוצה|מעוניין|מעוניינת|חולם|פתוח להצטרף",
)

# Injury reports are allowed only when they are meaningful, especially around big clubs.
# Minor "doubt / trained separately / will be assessed" items remain blocked.
INJURY_PATTERNS = (
    r"\b(?:injury|injured|surgery|operation|ACL|hamstring|muscle injury|fracture|broken|ruled out|out for|set to miss|will miss|misses|season over|out until|recovery|rehab)\b",
    r"פציעה|נפצע|פצוע|ניתוח|קרע|רצועה|שריר|שבר|ייעדר|בחוץ ל|יחמיץ|גמר את העונה|סיים את העונה|שיקום|החלמה",
)

SERIOUS_INJURY_PATTERNS = (
    r"\b(?:surgery|operation|ACL|fracture|broken|ruled out|out for|set to miss|will miss|season over|out until|months?|weeks?|long-term|major injury)\b",
    r"ניתוח|קרע|רצועה|שבר|ייעדר|בחוץ ל|יחמיץ|גמר את העונה|סיים את העונה|חודשים|שבועות|פציעה קשה|פציעה משמעותית",
)

# Broad fitness/recovery/injury-status words. These catch reports that do not say
# "injury" explicitly, for example: "his recovery is progressing well",
# "he will be ready for the World Cup", "fit for the opener".
INJURY_OR_FITNESS_UPDATE_PATTERNS = (
    r"\b(?:injury|injured|fitness|fit|unfit|available|ready|recovered|recovery|recovering|rehab|returning|return to training|back in training|back with the squad|progressing well|steps up recovery|close to return|expected back|set to return|will be ready|should be fit|match fit|opener|opening game|first game|ruled out|out for|will miss|set to miss|doubt|doubtful|assessment|tests|scan|surgery|operation|ACL|hamstring|muscle|fracture|broken)\b",
    r"פציעה|פצוע|נפצע|כשיר|כשירות|לא כשיר|זמין|מוכן|יהיה מוכן|אמור להיות כשיר|יהיה כשיר|החלים|החלמה|מחלים|שיקום|חזרה לאימונים|חזר לאימונים|חוזר לאימונים|חזר לסגל|חוזר לסגל|מתקדם יפה|מתקדמת יפה|התקדמות|מתקרב לחזרה|צפוי לחזור|צפויה לחזור|חזרה קרובה|משחק הפתיחה|פתיחת|ייעדר|בחוץ|יחמיץ|בספק|ייבדק|בדיקות|סריקה|ניתוח|קרע|רצועה|שריר|שבר",
)

MAJOR_NATIONAL_TEAM_CONTEXT_PATTERNS = (
    r"\b(?:World Cup|FIFA World Cup|Euro|EURO|Euros|Copa America|AFCON|Nations League|national team|international duty|Argentina|Brazil|England|France|Spain|Germany|Italy|Portugal|Netherlands|Belgium|Croatia|Uruguay|Colombia|Morocco|Senegal|Nigeria|Japan|USA|Mexico|Luis de la Fuente|De la Fuente)\b",
    r"מונדיאל|גביע העולם|יורו|קופה אמריקה|אליפות אפריקה|ליגת האומות|נבחרת|נבחרות|ארגנטינה|ברזיל|אנגליה|צרפת|ספרד|גרמניה|איטליה|פורטוגל|הולנד|בלגיה|קרואטיה|אורוגוואי|קולומביה|מרוקו|סנגל|ניגריה|יפן|ארה\"ב|מקסיקו|דה לה פואנטה|לואיס דה לה פואנטה|🇪🇸|🇦🇷|🇧🇷|🇫🇷|🇩🇪|🇮🇹|🇵🇹|🇳🇱|🇧🇪|🇭🇷|🇺🇾|🇨🇴|🇲🇦|🇸🇳|🇳🇬|🇯🇵|🇺🇸|🇲🇽",
)

PURE_ADMIN_APPOINTMENT_PATTERNS = (
    r"\b(?:appointed|set to be appointed|will become|new)\b.*\b(?:sporting director|technical director|director of football|chief scout|head of recruitment|advisor|consultant)\b",
    r"(?:צפוי להתמנות|ימונה|מונה|מנהל חדש|המנהל החדש).{0,80}(?:מנהל\s+(?:טכני|מקצועי|ספורטיבי)|סקאוט|יועץ|ראש\s+גיוס|מנהל\s+הכדורגל)",
)

MIN_IMPORTANCE_SCORE_TO_SEND = 35
MIN_IMPORTANCE_SCORE_TO_SEND_WEAK_INTEREST = 45


def _matches_any(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def should_use_ai_affiliation_fallback(post: Post) -> bool:
    """Use one Gemini request only for rare name-only football reports.

    This is for reports that mention a player/coach name and news mechanics but no club
    was detected locally. Gemini may allow only if the person is currently tied to, or
    was very recently tied to, one of the user's allowed big clubs or a top-70 national team.
    """
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    if len(cleaned) < 25 or len(cleaned) > 900:
        return False
    if _matches_any(OTHER_SPORT_BLOCK_PATTERNS, cleaned) or _matches_any(WOMEN_SPORT_BLOCK_PATTERNS, cleaned):
        return False
    has_news = _matches_any(TRANSFER_OR_FUTURE_PATTERNS, cleaned) or _matches_any(STRONG_PLAYER_MOVE_PATTERNS, cleaned) or _matches_any(COACH_IMPORTANT_PATTERNS, cleaned) or _matches_any(INJURY_OR_FITNESS_UPDATE_PATTERNS, cleaned)
    has_name_shape = bool(re.search(r"\b[A-Z][A-Za-zÀ-ÿ'’.-]{2,}(?:\s+[A-Z][A-Za-zÀ-ÿ'’.-]{2,}){1,3}\b", cleaned))
    return bool(has_news and has_name_shape and has_gemini_key_available())


def ai_affiliation_fallback_allows(post: Post) -> bool:
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    prompt = (
        "Return ONLY YES or NO. This is a men's football Telegram filter.\n"
        "Allow YES only if the report is real men's football news and the main person/team is clearly connected to one of these allowed clubs, an Israeli-league club, Israel national team, or a current FIFA top-70 men's national team.\n"
        "Connection can be current club/national team, confirmed destination, or very recent former club if the report is directly about transfer/contract/injury/squad/coach news.\n"
        "Return NO for women's football, basketball/NBA/WNBA/other sports, generic quotes, vague admiration, or if you are not sure.\n"
        "Allowed clubs include Bayern, Dortmund, Leverkusen, Frankfurt, Stuttgart, PSG, Marseille, Lyon, Lille, Lens, Monaco, Real Madrid, Barcelona, Atletico, Sevilla, Villarreal, Athletic Bilbao, Betis, Valencia, Real Sociedad, Man United, Man City, Liverpool, Chelsea, Arsenal, Tottenham, Newcastle, Aston Villa, West Ham, Everton, Brighton, Juventus, AC Milan, Inter, Roma, Napoli, Lazio, Atalanta, Fiorentina, Porto, Benfica, Sporting, Ajax, PSV, Flamengo, Palmeiras, Sao Paulo, Boca Juniors, River Plate, Al Nassr, Al Hilal, Al Ahli, Galatasaray, Fenerbahce, Inter Miami, Club Brugge, Red Star, Botafogo.\n\n"
        f"Post:\n{cleaned}"
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8}}
    for _index, key in gemini_available_keys_for_operation():
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_FAST_MODEL}:generateContent?key={urllib.parse.quote(key)}"
        try:
            data = http_post_json(url, payload, timeout=18, max_attempts=1, respect_retry_after=False)
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            answer = "".join(part.get("text", "") for part in parts).strip().upper()
            return answer.startswith("YES")
        except Exception as exc:
            try:
                cool_down_gemini_key(key, exc)
            except Exception:
                pass
            return False
    return False


def contains_final_only_allowed_club(post: Post) -> bool:
    text = html.unescape("\n".join([post.text or "", post.quoted_text or ""]))
    return _matches_any(FINAL_ONLY_ALLOWED_CLUB_PATTERNS, clean_for_ai_translation(text))


def contains_final_or_near_final_signal(post: Post) -> bool:
    text = html.unescape("\n".join([post.text or "", post.quoted_text or ""]))
    return _matches_any(FINAL_OR_NEAR_FINAL_PATTERNS, clean_for_ai_translation(text))


def is_known_admin_person_status_post(cleaned: str) -> bool:
    return _matches_any(KNOWN_ADMIN_PERSON_PATTERNS, cleaned) and _matches_any(ADMIN_PERSON_EXIT_OR_STATUS_PATTERNS, cleaned)


def football_relevance_decision(post: Post) -> tuple[bool, str, int, list[str]]:
    """Return (allowed, reason, score, signals) for football relevance.

    Updated logic:
    1) Big clubs: send even early transfer rumours from trusted writers.
    2) Top-5 league / promoted clubs: send when there is a real transfer/future/contract link.
    3) Small clubs: send only strong transfer steps or clear big-club connection.
    Interviews/quotes after matches are blocked unless they contain a real transfer/future link.
    """
    raw_text = html.unescape("\n".join([post.text or "", post.quoted_text or ""]))
    cleaned = clean_for_ai_translation(raw_text)
    if not cleaned:
        return False, "empty_after_clean", 0, ["empty"]
    if not contains_tracked_club_or_israeli_league(post):
        logging.debug("פוסט של %s נפסל בסינון האיכות: לא קשור לקבוצה ברשימות הדרגים.", post.username)
        return False, "not_connected_to_tracked_club", 0, ["no_tracked_club"]
    if is_other_sport_post(post):
        return False, "other_sport", 0, ["other_sport"]
    if is_youth_or_academy_post(post):
        return False, "youth_or_academy", 0, ["youth_or_academy"]
    if is_interview_post(post):
        return False, "interview_blocked", 0, ["interview"]
    if is_lineup_or_selection_post(post):
        return False, "lineup_or_selection", 0, ["lineup_or_selection"]

    has_allowed_interest_club = contains_allowed_club_or_israeli_league(post)
    has_final_only_club = _matches_any(FINAL_ONLY_ALLOWED_CLUB_PATTERNS, cleaned)
    has_big_rumor_club = _matches_any(BIG_CLUB_RUMOR_PATTERNS, cleaned) and not has_final_only_club
    has_top5_or_promoted_club = _matches_any(POPULAR_OR_RECENT_UCL_CLUB_PATTERNS, cleaned)
    has_elite_admin_club = _matches_any(ELITE_ADMIN_CLUB_PATTERNS, cleaned)
    has_low_interest_club = _matches_any(LOW_INTEREST_CLUB_PATTERNS, cleaned)
    has_low_interest_german_update = _matches_any(LOW_INTEREST_GERMAN_UPDATE_PATTERNS, cleaned)
    has_low_interest_german_destination = _matches_any(LOW_INTEREST_GERMAN_DESTINATION_PATTERNS, cleaned)
    has_low_interest_stay_renewal = _matches_any(LOW_INTEREST_STAY_RENEWAL_PATTERNS, cleaned)
    has_low_interest_non_europe_contract = _matches_any(LOW_INTEREST_NON_EUROPE_CONTRACT_PATTERNS, cleaned)
    has_admin_role = _matches_any(ADMIN_OR_BACKROOM_ROLE_PATTERNS, cleaned)
    has_known_admin_person_status = is_known_admin_person_status_post(cleaned)
    has_weak_interest = _matches_any(WEAK_INTEREST_PATTERNS, cleaned)
    has_transfer_or_future = _matches_any(TRANSFER_OR_FUTURE_PATTERNS, cleaned) or _matches_any(TRANSFER_LINKED_WEAK_PATTERNS, cleaned)
    has_vague_player_idea = _matches_any(VAGUE_PLAYER_IDEA_PATTERNS, cleaned)
    has_strong_move = _matches_any(STRONG_PLAYER_MOVE_PATTERNS, cleaned)
    has_clear_departure = is_clear_player_departure_post(post)
    has_coach_news = _matches_any(COACH_IMPORTANT_PATTERNS, cleaned)
    has_big_club_context = _matches_any(BIG_CLUB_CONTEXT_PATTERNS, cleaned)
    has_pure_admin_appointment = _matches_any(PURE_ADMIN_APPOINTMENT_PATTERNS, cleaned)
    has_injury = _matches_any(INJURY_PATTERNS, cleaned)
    has_serious_injury = _matches_any(SERIOUS_INJURY_PATTERNS, cleaned)
    has_injury_or_fitness_update = _matches_any(INJURY_OR_FITNESS_UPDATE_PATTERNS, cleaned)
    has_major_national_context = _matches_any(MAJOR_NATIONAL_TEAM_CONTEXT_PATTERNS, cleaned)
    has_final_or_near_final = _matches_any(FINAL_OR_NEAR_FINAL_PATTERNS, cleaned)
    has_final_only_strict = _matches_any(FINAL_ONLY_STRICT_PATTERNS, cleaned)

    # For the user's lower-priority club group, block pure rumours/loose interest.
    # Keep normal rules if a major club is also part of the same report, or when the
    # post is really about a national team / country squad.
    if has_final_only_club and not has_final_only_strict:
        return False, "final_only_club_not_strict_final", 0, ["final_only_club", "not_strict_final"]

    score = 0
    signals: list[str] = []

    def add(points: int, signal: str) -> None:
        nonlocal score
        score += points
        signals.append(signal)

    if has_allowed_interest_club:
        add(20, "allowed_club_or_israeli_league")
    if has_big_rumor_club:
        add(70, "big_club")
    if has_top5_or_promoted_club:
        add(45, "top5_or_promoted_club")
    if has_elite_admin_club:
        add(20, "elite_admin_club")
    if has_big_club_context:
        add(55, "big_club_context")
    if has_strong_move:
        add(45, "strong_transfer_step")
    if has_clear_departure:
        add(60, "clear_player_departure")
    if has_transfer_or_future:
        add(25, "transfer_or_future_link")
    if has_coach_news:
        add(25, "coach_news")
    if has_injury:
        add(10, "injury")
    if has_serious_injury:
        add(25, "serious_injury")
    if has_injury_or_fitness_update:
        add(30, "injury_or_fitness_update")
    if has_major_national_context:
        add(25, "major_national_context")
    if has_final_only_club:
        add(5, "final_only_club")
    if has_final_or_near_final:
        add(45, "final_or_near_final")
    if has_weak_interest:
        add(-10, "weak_interest")
    if has_vague_player_idea:
        add(-20, "vague_player_idea")
    if has_low_interest_club and not (has_big_rumor_club or has_big_club_context):
        add(-25, "low_interest_club")
    if has_low_interest_german_update and not (has_big_rumor_club or has_big_club_context or has_major_national_context):
        add(-35, "low_interest_german_update")
    if has_admin_role or has_known_admin_person_status:
        add(-45, "admin_or_backroom_role")
    if has_pure_admin_appointment:
        add(-25, "pure_admin_appointment")

    # Backroom/admin appointments remain restricted: only Barcelona/Barça or Real Madrid.
    if (has_admin_role or has_known_admin_person_status) and not has_elite_admin_club:
        return False, "admin_or_backroom_only_barca_real_allowed", score, signals

    if has_low_interest_stay_renewal:
        return False, "low_interest_stay_renewal", score, signals

    if has_low_interest_non_europe_contract and not (has_big_rumor_club or has_big_club_context):
        return False, "low_interest_non_europe_contract", score, signals

    if has_low_interest_german_destination and not has_major_national_context:
        return False, "low_interest_german_destination", score, signals

    if has_low_interest_german_update and not (has_big_rumor_club or has_big_club_context or has_major_national_context):
        if not (has_strong_move and has_final_or_near_final):
            return False, "low_interest_german_update_not_enough", score, signals

    # Injuries / fitness / recovery: send broadly for popular clubs, top-5 clubs,
    # and major national-team or World Cup contexts. This intentionally catches
    # reports that do not say "injury" but discuss recovery/fitness/readiness.
    if has_injury_or_fitness_update:
        if has_big_rumor_club:
            return True, "big_club_injury_or_fitness_update", score, signals
        if has_top5_or_promoted_club:
            return True, "top5_injury_or_fitness_update", score, signals
        if has_major_national_context:
            return True, "major_national_team_injury_or_fitness_update", score, signals
        if has_serious_injury:
            return True, "serious_injury_update", score, signals
        if not (has_strong_move or has_transfer_or_future or has_coach_news):
            return False, "minor_or_unclear_injury_not_enough", score, signals

    # Strong transfer steps are newsworthy only when they are not just
    # low-interest clubs with no big-club/national-team context.
    if has_strong_move and has_low_interest_club and not (has_big_rumor_club or has_big_club_context or has_top5_or_promoted_club or has_major_national_context):
        return False, "low_interest_club_strong_move_not_enough", score, signals
    if has_strong_move:
        return True, "strong_transfer_step", score, signals

    # Big-club logic: early rumours are allowed, but pure vague player-idea posts still need
    # either interest language or a transfer/future link. A small club mentioned in the same
    # post does NOT drag it down; the big-club connection wins.
    if has_big_rumor_club or has_big_club_context:
        if has_vague_player_idea and not (has_weak_interest or has_transfer_or_future or has_coach_news):
            return False, "vague_big_club_player_idea_without_real_rumour", score, signals
        if has_weak_interest or has_transfer_or_future or has_coach_news:
            return True, "big_club_rumour_or_transfer_context", score, signals

    # Strict allow-list clubs: if the post mentions one of the user's clubs, continue only
    # when the text has real news mechanics. This also catches abbreviations such as BVB/MUFC.
    if has_allowed_interest_club:
        if has_transfer_or_future or has_coach_news or has_injury_or_fitness_update:
            return True, "allowed_club_news_context", score, signals
        if has_weak_interest and (has_transfer_or_future or has_big_club_context):
            return True, "allowed_club_weak_transfer_context", score, signals

    # Top-5 / promoted clubs are relevant, but they need a real transfer/future/contract/coach link.
    # This blocks regular post-match interviews and generic admiration.
    if has_top5_or_promoted_club:
        if has_transfer_or_future or has_coach_news:
            return True, "top5_or_promoted_transfer_context", score, signals
        if has_weak_interest:
            return False, "top5_weak_interest_without_transfer_link", score, signals
        return False, "top5_club_but_no_transfer_or_coach_context", score, signals

    # Small clubs: only send concrete transfer steps, coach news, or explicit big-club context.
    if has_low_interest_club and not (has_strong_move or has_big_club_context or has_coach_news):
        return False, "small_club_not_important_enough", score, signals

    if has_coach_news and score >= MIN_IMPORTANCE_SCORE_TO_SEND:
        return True, "coach_news", score, signals

    threshold = MIN_IMPORTANCE_SCORE_TO_SEND_WEAK_INTEREST if has_weak_interest else MIN_IMPORTANCE_SCORE_TO_SEND
    if score < threshold:
        return False, f"importance_score_too_low:{score}<{threshold}", score, signals

    return True, "allowed", score, signals

def football_importance_block_reason(post: Post) -> str:
    allowed, reason, score, signals = football_relevance_decision(post)
    if allowed:
        logging.debug(
            "מסנן חשיבות עבר: score=%s signals=%s @%s %s",
            score,
            ",".join(signals),
            post.username,
            post.link,
        )
        return ""
    return f"{reason}; score={score}; signals={','.join(signals) or 'none'}"

def pre_send_final_local_block_reason(post: Post) -> str:
    """Last cheap safety gate before any Gemini translation or video lookup.

    This function must stay deterministic and network-free. It guarantees that if a
    post reached send_post by mistake, the bot still will not spend Gemini/video
    requests on content that is clearly not publishable.
    """
    if is_too_old_post(post):
        return "old_post"
    if is_women_or_wnba_post(post):
        return "women_or_wnba"
    if is_medical_staff_post(post):
        return "medical_staff"
    if is_other_sport_post(post):
        return "other_sport"
    if is_youth_or_academy_post(post):
        return "youth_or_academy"
    if is_interview_post(post):
        return "interview_blocked"
    if is_lineup_or_selection_post(post):
        return "lineup_or_selection"
    if is_match_result_or_engagement_post(post):
        return "match_result_or_engagement"
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    if _matches_any(FINAL_ONLY_ALLOWED_CLUB_PATTERNS, cleaned) and not _matches_any(FINAL_ONLY_STRICT_PATTERNS, cleaned):
        return "final_only_club_not_strict_final"
    if is_known_admin_person_status_post(cleaned) and not _matches_any(ELITE_ADMIN_CLUB_PATTERNS, cleaned):
        return "admin_or_backroom_only_barca_real_allowed"
    if _matches_any(LOW_INTEREST_STAY_RENEWAL_PATTERNS, cleaned):
        return "low_interest_stay_renewal"
    if _matches_any(LOW_INTEREST_NON_EUROPE_CONTRACT_PATTERNS, cleaned) and not (
        _matches_any(BIG_CLUB_RUMOR_PATTERNS, cleaned)
        or _matches_any(BIG_CLUB_CONTEXT_PATTERNS, cleaned)
    ):
        return "low_interest_non_europe_contract"
    if (
        _matches_any(LOW_INTEREST_CLUB_PATTERNS, cleaned)
        and not (
            _matches_any(BIG_CLUB_RUMOR_PATTERNS, cleaned)
            or _matches_any(BIG_CLUB_CONTEXT_PATTERNS, cleaned)
            or _matches_any(POPULAR_OR_RECENT_UCL_CLUB_PATTERNS, cleaned)
            or _matches_any(MAJOR_NATIONAL_TEAM_CONTEXT_PATTERNS, cleaned)
        )
    ):
        return "low_interest_club_not_allowed"
    if not contains_tracked_club_or_israeli_league(post):
        return "not_connected_to_tracked_club"
    if is_link_only_or_details_post(post) and not is_clear_player_departure_post(post):
        return "link_or_details_only"
    if is_podcast_or_longform_post(post):
        return "podcast_or_longform"
    if is_non_news_social_post(post):
        return "non_news_social"
    importance_reason = football_importance_block_reason(post)
    if importance_reason:
        return importance_reason
    return ""

def _extract_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def gemini_translate_post_once(post: Post, include_quote: bool) -> tuple[str, str, str]:
    """Translate main + quoted text in ONE Gemini request, after local approval only."""
    if not GEMINI_API_KEYS:
        raise TranslationUnavailable("No Gemini API key configured")
    if not has_gemini_key_available():
        raise TranslationUnavailable("Gemini currently unavailable without network check")
    main_source = clean_for_ai_translation(post.text) or clean_before_translation(post.text)
    quote_source = clean_for_ai_translation(post.quoted_text) if include_quote and post.quoted_text else ""
    author_source = clean_before_translation(post.quoted_author) if include_quote and post.quoted_author else ""
    if not main_source and not quote_source:
        return "", "", ""
    cache_material = json.dumps({"m": main_source, "q": quote_source, "a": author_source}, ensure_ascii=False, sort_keys=True)
    cache_key = "combined-gemini-only-v3:" + hashlib.sha256(cache_material.encode("utf-8")).hexdigest()
    if cache_key in TRANSLATION_CACHE:
        cached = _extract_json_object(TRANSLATION_CACHE[cache_key])
        if cached:
            return (
                final_visual_cleanup(preserve_original_country_flags(main_source, preserve_original_emojis(main_source, str(cached.get("main", ""))))),
                final_visual_cleanup(preserve_original_country_flags(quote_source, preserve_original_emojis(quote_source, str(cached.get("quote", ""))))) if quote_source else "",
                final_hebrew_polish(str(cached.get("quote_author", ""))).strip(),
            )
    glossary_text = "\n".join(x for x in [relevant_name_glossary(main_source), relevant_name_glossary(quote_source), relevant_name_glossary(author_source)] if x)
    glossary_block = f"\nKnown names glossary. Use these exact Hebrew names when relevant:\n{glossary_text}\n" if glossary_text else ""
    prompt = (
        "You are a senior Hebrew MEN'S football news translator and name editor.\n"
        "The post below already passed a strict local publishing filter. Do NOT decide whether to publish. Translate only.\n"
        "Return ONLY compact valid JSON with exactly these keys: main, quote, quote_author.\n"
        "Rules:\n"
        "- Hebrew only, natural Telegram sports-news Hebrew.\n"
        "- Do not add facts, context, clubs, years, dates, injuries, transfer status, or words that are not directly in the source.\n"
        "- Preserve every factual item exactly: player/coach names, clubs, national teams, years, dates, numbers, scores, fees, and status.\n"
        "- If a name is uncertain, keep the clean original Latin name instead of inventing Hebrew.\n"
        "- Verify names from football context; fix malformed transliterations, but never replace one club/person with a different one.\n"
        "- Convert known @handles only when they are part of the news; remove source/junk handles and URLs.\n"
        "- Remove URLs, tracking text, sponsor lines, and useless link prompts.\n"
        "- Preserve real flag emojis. If country-code letters are used as a flag marker, output the correct flag emoji and remove the letters.\n"
        "- Remove leftovers such as TR, טי אר, GE, FR, IT, ES, DE when they only duplicate a nearby flag emoji.\n"
        "- Keep emojis only when useful and already implied by the source.\n"
        "- Do not write explanations. JSON only.\n"
        f"{glossary_block}\n"
        "MAIN_TEXT:\n" + (main_source or "") + "\n\n"
        "QUOTED_AUTHOR:\n" + (author_source or "") + "\n\n"
        "QUOTED_TEXT:\n" + (quote_source or "")
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0, "topP": 0.7, "maxOutputTokens": 900},
    }
    last_error: Exception | None = None
    real_requests_used = 0
    for index, key in gemini_available_keys_for_operation():
        if real_requests_used >= max(1, GEMINI_MAX_REAL_TRANSLATION_REQUESTS):
            break
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{urllib.parse.quote(GEMINI_FAST_MODEL)}:generateContent?key={urllib.parse.quote(key)}"
        )
        try:
            with GEMINI_TRANSLATION_SEMAPHORE:
                real_requests_used += 1
                data = http_post_json(url, payload, timeout=10, max_attempts=1, respect_retry_after=False)
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            raw = "".join(part.get("text", "") for part in parts).strip()
            parsed = _extract_json_object(raw)
            if not parsed:
                parsed = {"main": raw, "quote": "", "quote_author": ""}
            main = final_hebrew_polish(str(parsed.get("main", ""))).strip()
            quote = final_hebrew_polish(str(parsed.get("quote", ""))).strip()
            quote_author = final_hebrew_polish(str(parsed.get("quote_author", ""))).strip()
            main = final_visual_cleanup(preserve_original_country_flags(main_source, preserve_original_emojis(main_source, main)))
            quote = final_visual_cleanup(preserve_original_country_flags(quote_source, preserve_original_emojis(quote_source, quote))) if quote_source else ""
            if translation_contradicts_source(main_source + "\n" + quote_source, main + "\n" + quote):
                raise RuntimeError("Gemini translation contradicted source names")
            if translation_changes_locked_numbers(main_source + "\n" + quote_source, main + "\n" + quote):
                raise RuntimeError("Gemini translation changed locked numbers or years")
            if main or quote:
                TRANSLATION_CACHE[cache_key] = json.dumps({"main": main, "quote": quote, "quote_author": quote_author}, ensure_ascii=False)
                GEMINI_KEY_COOLDOWNS.pop(key, None)
                mark_gemini_available()
                return main, quote, quote_author
            raise RuntimeError("Gemini returned empty translation")
        except Exception as exc:
            last_error = exc
            cool_down_gemini_key(key, exc)
            remaining = max(0, max(1, GEMINI_MAX_REAL_TRANSLATION_REQUESTS) - real_requests_used)
            if remaining:
                logging.warning(
                    "⚠️ תרגום Gemini נכשל עם %s; עובר למפתח הבא. נשארו עד %s ניסיונות מפתח לפוסט הזה. סיבה: %s",
                    gemini_key_label(index),
                    remaining,
                    gemini_error_summary(exc),
                )
            else:
                logging.warning(
                    "⚠️ תרגום Gemini נכשל עם %s ואין עוד ניסיונות מפתח לפוסט הזה. סיבה: %s",
                    gemini_key_label(index),
                    gemini_error_summary(exc),
                )
            continue
    log_gemini_unavailable(last_error)
    raise TranslationUnavailable(f"Gemini single translation failed after {real_requests_used} real request(s): {last_error}")


def translate_post_for_send(post: Post) -> tuple[str, str, str]:
    """Return publishable translation. If Gemini is unavailable, do not send."""
    include_quote = bool(
        not is_self_quote(post)
        and post.quoted_text
        and (
            TRANSLATE_QUOTED_POSTS
            or (
                TRANSLATE_QUOTED_POSTS_IF_MAIN_TOO_SHORT
                and len(clean_before_translation(post.text)) < MIN_MAIN_TEXT_CHARS_FOR_SKIP_QUOTE
            )
        )
    )
    main, quote, quote_author = gemini_translate_post_once(post, include_quote)
    if not (has_meaningful_text(main) or has_meaningful_text(quote)):
        raise TranslationUnavailable("Gemini returned no meaningful translation")
    return main, quote, quote_author


def send_post(post: Post) -> dict[str, Any]:
    started = time.perf_counter()
    timings: dict[str, Any] = {"sent": False, "mode": "skipped"}

    # Final network-free approval gate. No Gemini request, video HEAD/GET,
    # external video API, or Telegram upload is allowed before this passes.
    if getattr(post, "force_startup_send", False):
        logging.info("Startup verification force mode: skipping local filters for latest @%s post. Gemini/translation and Telegram send still run.", post.username)
        block_reason = ""
    else:
        block_reason = pre_send_final_local_block_reason(post)
    if block_reason:
        timings["total_seconds"] = time.perf_counter() - started
        timings["mode"] = f"pre_send_blocked:{block_reason}"
        log_skip_once(
            "pre_send:" + block_reason,
            post,
            "דילוג לפני בינה/וידיאו: %s מ-@%s לא נשלח ולא בוצעה בדיקת וידיאו/Gemini: %s | %s",
            block_reason,
            post.username,
            post.link,
            filtered_post_text_preview(post),
        )
        return timings

    translation_started = time.perf_counter()
    try:
        translated, quoted_translated, quoted_author_translated = translate_post_for_send(post)
    except TranslationUnavailable as exc:
        timings["translation_seconds"] = time.perf_counter() - translation_started
        timings["total_seconds"] = time.perf_counter() - started
        timings["mode"] = "translation_unavailable"
        log_skip_once(
            "translation_unavailable",
            post,
            "⏳ פוסט עבר סינון אבל לא נשלח כי אין תרגום Gemini תקין אחרי ניסיון מפתחות Gemini: @%s %s | %s",
            post.username,
            post.link,
            exc,
        )
        return timings
    timings["translation_seconds"] = time.perf_counter() - translation_started

    video_started = time.perf_counter()
    video_url = sendable_video_url(post) if SEND_VIDEO_FILES else ""
    timings["video_lookup_seconds"] = time.perf_counter() - video_started

    prepare_started = time.perf_counter()
    message = build_message(
        post,
        translated,
        quoted_translated,
        quoted_author_translated,
        include_video_link=False,
    )
    timings["channel_memory_text"] = message
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
            logging.warning("Video send failed, falling back to clean text only: %s", exc)
            message = build_message(
                post,
                translated,
                quoted_translated,
                quoted_author_translated,
                include_video_link=False,
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
    if not active_x_accounts():
        raise ValueError("Add at least one X/Twitter account to X_ACCOUNTS")


def run_once(state: dict[str, list[str]], startup_cycle: bool = False, min_published_ts: float = 0.0) -> int:
    cycle_started = time.perf_counter()
    first_run = not any(state.values())
    sent = 0
    accounts = active_x_accounts()
    fetch_workers = min(current_max_parallel_account_checks(), max(1, len(accounts)))
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
            result["force_startup_send"] = bool(getattr(post, "force_startup_send", False))
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
                force_fabrizio_startup_check = (
                    startup_cycle
                    and FORCE_SEND_LATEST_FABRIZIO_ON_STARTUP
                    and username == "FabrizioRomano"
                    and bool(posts)
                )
                if force_fabrizio_startup_check:
                    forced_already_sent = set(state.get(FORCED_FABRIZIO_STARTUP_STATE_KEY, []))
                    latest_post = posts[0]
                    if (
                        not FORCE_SEND_LATEST_FABRIZIO_EVERY_STARTUP
                        and any(post_id in forced_already_sent for post_id in latest_post.dedupe_ids)
                    ):
                        new_posts = []
                        logging.info(
                            "Startup verification: latest @FabrizioRomano post was already force-sent before, skipping this startup. Set FORCE_SEND_LATEST_FABRIZIO_EVERY_STARTUP=1 to send it every restart. Link: %s",
                            latest_post.link,
                        )
                    else:
                        setattr(latest_post, "force_startup_send", True)
                        new_posts = [latest_post]
                        logging.info(
                            "Startup verification: force-sending latest @FabrizioRomano post through RSS, Gemini translation and Telegram send. Local filters are skipped for this check only. RSS source: %s | link: %s",
                            posts[0].source_name,
                            posts[0].link,
                        )
                elif startup_cycle and SEND_LAST_POST_ON_EVERY_START:
                    new_posts = posts[:1]
                elif first_run and SEND_LAST_POST_ON_FIRST_RUN:
                    new_posts = posts[:1]
                elif first_run:
                    for post in posts:
                        seen.update(post.dedupe_ids)
                    state[username] = list(seen)[-500:]
                    continue

                candidate_posts: list[tuple[str, Post, float]] = []
                posts_to_consider = new_posts[: min(MAX_NEW_POSTS_PER_ACCOUNT_PER_CHECK, MAX_POSTS_SENT_PER_CYCLE)]
                for post in reversed(posts_to_consider):
                    if min_published_ts and post.published_ts and post.published_ts < min_published_ts:
                        seen.update(post.dedupe_ids)
                        continue
                    if is_interview_post(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("interview_blocked", post, "׳“׳™׳׳•׳’ ׳׳¡׳ ׳: ׳¨׳׳™׳•׳ ׳-@%s ׳׳ ׳ ׳©׳׳—: %s | ׳˜׳§׳¡׳˜: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if getattr(post, "force_startup_send", False):
                        candidate_posts.append((username, post, time.perf_counter() - cycle_started))
                        continue
                    if is_too_old_post(post) and not (startup_cycle and SEND_LAST_POST_ON_EVERY_START):
                        seen.update(post.dedupe_ids)
                        continue
                    if any(post_id in queued_ids for post_id in post.dedupe_ids):
                        log_skip_once("queued_duplicate", post, "דילוג: כפילות באותו סבב מ-@%s לא נשלחה: %s", username, post.link)
                        continue
                    if is_women_or_wnba_post(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("women_or_wnba", post, "דילוג מסנן: נשים/WNBA מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_medical_staff_post(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("medical_staff", post, "דילוג מסנן: צוות רפואי/דוקטור/פיזיותרפיסט מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_lineup_or_selection_post(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("lineup_or_selection", post, "Skip filter: lineup/bench/match squad report from @%s was not sent: %s | text: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_link_only_or_details_post(post) and not is_clear_player_departure_post(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("link_only", post, "דילוג מסנן: קישור/פרטים בלי דיווח מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_podcast_or_longform_post(post) and not try_keep_non_duplicate_report_lines(post, state):
                        seen.update(post.dedupe_ids)
                        log_skip_once("podcast_or_longform", post, "דילוג מסנן: פודקאסט/תוכן ארוך מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_non_news_social_post(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("non_news_social", post, "דילוג מסנן: פוסט לא חדשותי/סטטיסטיקה בלבד מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    importance_reason = football_importance_block_reason(post)
                    if importance_reason:
                        seen.update(post.dedupe_ids)
                        log_skip_once("importance:" + importance_reason, post, "דילוג מסנן חשיבות: %s מ-@%s לא נשלח: %s | טקסט: %s", importance_reason, username, post.link, filtered_post_text_preview(post))
                        continue
                    duplicate_event = find_channel_duplicate_event(post, state) or find_recent_duplicate_event(post, state)
                    if duplicate_event:
                        if try_keep_non_duplicate_report_lines(post, state):
                            duplicate_event = None
                        else:
                            seen.update(post.dedupe_ids)
                            log_skip_once("recent_duplicate", post, "דילוג כפילות חכמה: אותו אירוע כבר נמצא בזיכרון 24/12 שעות. @%s לא נשלח: %s", username, post.link)
                            continue
                    if duplicate_event:
                        seen.update(post.dedupe_ids)
                        log_skip_once("recent_duplicate", post, "דילוג כפילות חכמה: אותו אירוע כבר נשלח ב-24 השעות האחרונות מ-@%s. הנוכחי מ-@%s לא נשלח: %s", duplicate_event.get("username", "unknown"), username, post.link)
                        continue
                    candidate_posts.append((username, post, time.perf_counter() - cycle_started))

                global_candidate_posts.extend(candidate_posts)

                state[username] = list(seen)[-500:]

        global_candidate_posts = cluster_parallel_candidates(global_candidate_posts)

        for candidate in sort_candidate_posts_for_priority(global_candidate_posts):
            if len(send_futures) >= MAX_POSTS_SENT_PER_CYCLE:
                break
            username, post, _ = candidate
            seen = set(state.get(username, []))
            final_block_reason = "interview_blocked" if is_interview_post(post) else ("" if getattr(post, "force_startup_send", False) else pre_send_final_local_block_reason(post))
            if final_block_reason:
                mark_candidate_seen(state, candidate)
                log_skip_once(
                    "final:" + final_block_reason,
                    post,
                    "דילוג סופי לפני שליחה: %s מ-@%s לא נשלח, לפני Gemini/וידיאו: %s | %s",
                    final_block_reason,
                    username,
                    post.link,
                    filtered_post_text_preview(post),
                )
                continue
            duplicate_event = None if getattr(post, "force_startup_send", False) else (find_channel_duplicate_event(post, state) or find_recent_duplicate_event_ai_aware(post, state))
            if duplicate_event:
                if try_keep_non_duplicate_report_lines(post, state):
                    duplicate_event = None
                else:
                    mark_candidate_seen(state, candidate)
                    log_skip_once("same_cycle_duplicate", post, "דילוג כפילות חכמה: אותו אירוע כבר נמצא בזיכרון הערוץ/הבוט. @%s לא נשלח: %s", username, post.link)
                    continue
            if duplicate_event:
                mark_candidate_seen(state, candidate)
                log_skip_once("same_cycle_duplicate", post, "דילוג כפילות חכמה באותו סבב: אותו אירוע כבר נבחר ממקור עדיף/קודם. @%s לא נשלח: %s", username, post.link)
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
                if result.get("force_startup_send"):
                    forced_seen = set(state.get(FORCED_FABRIZIO_STARTUP_STATE_KEY, []))
                    forced_seen.update(post_ids)
                    state[FORCED_FABRIZIO_STARTUP_STATE_KEY] = list(forced_seen)[-100:]
                if result.get("channel_memory_text"):
                    remember_channel_news_text(str(result.get("channel_memory_text", "")), state, message_id=link, source="bot_sent")
                sent += 1
                logging.info(
                    "✅ נשלח פוסט מ-@%s | מצב: %s | מקור RSS: %s | גיל %.0fs | מציאה %.2fs | תרגום/Gemini %.2fs | וידיאו %.2fs | הכנה %.2fs | שליחה %.2fs | סה״כ %.2fs",
                    username,
                    result.get("mode", "unknown"),
                    result.get("source_name", "unknown"),
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
                logging.info(
                    "דילוג: ג'מיני זיהה שאין עדכון חדשותי, הפוסט סומן כנראה: %s | מקור RSS: %s",
                    link,
                    result.get("source_name", "unknown"),
                )
            else:
                logging.warning(
                    "⏳ פוסט מ-@%s לא נשלח ולכן לא סומן כנראה, יישאר לניסיון הבא: %s | מקור RSS: %s | מצב: %s",
                    username,
                    link,
                    result.get("source_name", "unknown"),
                    result.get("mode", "unknown"),
                )
    finally:
        send_executor.shutdown(wait=True, cancel_futures=False)

    return sent


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    refresh_gemini_api_keys_from_env()
    validate_settings()
    env_parts_count = gemini_env_parts_count()
    normal_loader_count = len(configured_gemini_api_keys())
    emergency_loader_count = len(emergency_gemini_api_keys_from_any_env())
    logging.info("BOT_BUILD_ID: %s", BOT_BUILD_ID)
    print(f"Football bot is running. Accounts: {', '.join('@' + account for account in active_x_accounts())}", flush=True)
    print(f"Checking every {CHECK_EVERY_SECONDS} seconds.", flush=True)
    print("Gemini translation: " + (f"ON - {len(GEMINI_API_KEYS)} key(s) loaded" if GEMINI_API_KEYS else "OFF - posts will not be sent without Gemini"), flush=True)
    logging.info("Gemini: נטענו %s מפתחות API מתוך %s חלקים שנמצאו במשתני הסביבה.", len(GEMINI_API_KEYS), env_parts_count)
    logging.info("Gemini env debug בטוח, בלי ערכי מפתחות: %s", gemini_env_debug_summary())
    if not normal_loader_count and emergency_loader_count and GEMINI_API_KEYS:
        logging.warning(
            "Gemini אבחון: הטעינה הרגילה החזירה 0, אבל טעינת חירום מצאה %s מפתחות והבוט משתמש בהם עכשיו.",
            emergency_loader_count,
        )
    if env_parts_count and not GEMINI_API_KEYS:
        logging.error(
            "Gemini אבחון חמור: Railway מכיל %s חלקי מפתחות אבל הקוד טען 0. אם הלוג הזה מופיע עם BOT_BUILD_ID=%s, שלח את שורת הדיבאג; אם BOT_BUILD_ID אחר/חסר, Railway מריץ קוד ישן.",
            env_parts_count,
            BOT_BUILD_ID,
        )
    if not env_parts_count:
        logging.error("Gemini אבחון: לא נמצאו חלקי מפתחות בכלל במשתני הסביבה. בדוק שהשם המדויק הוא GEMINI_API_KEYS ושהוא מחובר לסביבה production.")
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
    last_heartbeat_log = 0.0
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
                save_ai_decision_cache()
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
            save_ai_decision_cache()
            if sent:
                print(f"Sent {sent} new post(s).", flush=True)
            now = time.time()
            if now - last_heartbeat_log >= HEARTBEAT_LOG_SECONDS:
                logging.info("בוט הכדורגל עדיין עובד. כתבים פעילים: %s | בדיקה כל %ss | נשלחו בסבב: %s", len(active_x_accounts()), current_check_every_seconds(), sent)
                last_heartbeat_log = now
        except Exception as exc:
            logging.error("Unexpected error. Bot will keep running: %s", exc)
        elapsed = time.time() - cycle_started
        time.sleep(max(0, current_check_every_seconds() - elapsed))


if __name__ == "__main__":
    main()

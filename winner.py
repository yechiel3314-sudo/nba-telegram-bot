#!/usr/bin/env python3
"""
Single-file X/Twitter to Telegram football news forwarder.

Run:
  python3 football_x_to_telegram.py

What this version does:
- Scans all accounts in parallel with a server-credit-saving cadence.
- Checks nitter.net RSS first, then uses RSS fallback mirrors only when the
  primary source is empty, stale, or failing.
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
import math
import os
import re
import shutil
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

BOT_BUILD_ID = "football-control-buttons-refined-2026-06-19"
BOT_STARTED_AT = time.time()
SUPPRESS_STARTUP_OLD_POST_BLOCK_REPORT_SECONDS = int(os.environ.get("SUPPRESS_STARTUP_OLD_POST_BLOCK_REPORT_SECONDS", str(30 * 60)))


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
# Default: try the configured key pool for a publishable post before giving up.
# Keep translation reliability high by default. Railway/server savings are handled
# by scan cadence, retries, parallelism, and retrying transient translation failures later.
GEMINI_MAX_REAL_TRANSLATION_REQUESTS = max(3, int(os.environ.get("GEMINI_MAX_REAL_TRANSLATION_REQUESTS", "8")))
GEMINI_RETRY_WAIT_SECONDS = int(os.environ.get("GEMINI_RETRY_WAIT_SECONDS", "8"))
GEMINI_TRANSLATION_TIMEOUT_SECONDS = int(os.environ.get("GEMINI_TRANSLATION_TIMEOUT_SECONDS", "18"))
GEMINI_COOLDOWN_SECONDS = 10 * 60
GEMINI_TEMPORARY_OVERLOAD_COOLDOWN_SECONDS = int(os.environ.get("GEMINI_TEMPORARY_OVERLOAD_COOLDOWN_SECONDS", "90"))
# When Gemini quota is exhausted, do not keep probing the API every few minutes.
# A failed probe is also an API request, so quota protection pauses all real Gemini requests
# until the control-panel button releases it after the quota has refilled.
GEMINI_QUOTA_GUARD_ENABLED = os.environ.get("GEMINI_QUOTA_GUARD_ENABLED", "1") == "1"
GEMINI_QUOTA_GUARD_STATE_KEY = "gemini_requests_paused_until_refill"
GEMINI_MAX_PARALLEL_TRANSLATIONS = int(os.environ.get("GEMINI_MAX_PARALLEL_TRANSLATIONS", "1"))
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

DEFAULT_ENABLED_OPTIONAL_ACCOUNTS = {"Plettigoal"}
ALWAYS_ENABLED_OPTIONAL_ACCOUNTS: set[str] = set()
LOCKED_DISABLED_BASE_ACCOUNTS: set[str] = set()
EXTRA_STRICT_SOURCE_ACCOUNTS = {"NicoSchira", "DiMarzio"}
CONTROL_STATE_DIMARZIO_REENABLED_KEY = "dimarzio_reenabled_after_strict_filter"

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
CHECK_EVERY_SECONDS = int(os.environ.get("CHECK_EVERY_SECONDS", "30"))
HEARTBEAT_LOG_SECONDS = 5 * 60  # לוג חיים כל 5 דקות
SCAN_CYCLE_SUMMARY_SECONDS = int(os.environ.get("SCAN_CYCLE_SUMMARY_SECONDS", "60"))
SCAN_CYCLE_SUMMARY_LAST_LOGGED_AT = 0.0
SCAN_CYCLE_SUMMARY: dict[str, int] = {}
DAILY_QUALITY_REPORT_ENABLED = os.environ.get("DAILY_QUALITY_REPORT_ENABLED", "1") == "1"
DAILY_QUALITY_REPORT_HOUR = int(os.environ.get("DAILY_QUALITY_REPORT_HOUR", "22"))
DAILY_QUALITY_REPORT_MINUTE = int(os.environ.get("DAILY_QUALITY_REPORT_MINUTE", "0"))
DAILY_QUALITY_REPORT_LAST_DATE = ""
DAILY_QUALITY_STATS: dict[str, Any] = {}
DAILY_QUALITY_STATS_FILE = os.environ.get("DAILY_QUALITY_STATS_FILE", "football_daily_quality_stats.json")
DAILY_QUALITY_STATS_SAVE_EVERY_SECONDS = int(os.environ.get("DAILY_QUALITY_STATS_SAVE_EVERY_SECONDS", "10"))
DAILY_QUALITY_STATS_LAST_SAVE_AT = 0.0
DAILY_QUALITY_STATS_LOADED = False
BOT_DATA_DIR = os.environ.get("FOOTBALL_BOT_DATA_DIR") or os.environ.get("BOT_DATA_DIR") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or ""
APP_DATA_DIR_CACHE: Path | None = None
HTTP_RETRIES = int(os.environ.get("HTTP_RETRIES", "2"))
REQUEST_TIMEOUT_SECONDS = 10
FEED_REQUEST_TIMEOUT_SECONDS = float(os.environ.get("FEED_REQUEST_TIMEOUT_SECONDS", "6"))
FEED_HTTP_RETRIES = int(os.environ.get("FEED_HTTP_RETRIES", "2"))
FEED_COLLECTION_TIMEOUT_SECONDS = float(os.environ.get("FEED_COLLECTION_TIMEOUT_SECONDS", "8"))
MAX_PARALLEL_ACCOUNT_CHECKS = int(os.environ.get("MAX_PARALLEL_ACCOUNT_CHECKS", "4"))
MAX_PARALLEL_FEED_CHECKS_PER_ACCOUNT = int(os.environ.get("MAX_PARALLEL_FEED_CHECKS_PER_ACCOUNT", "3"))
MAX_NEW_POSTS_PER_ACCOUNT_PER_CHECK = int(os.environ.get("MAX_NEW_POSTS_PER_ACCOUNT_PER_CHECK", "20"))
MAX_POSTS_SENT_PER_CYCLE = int(os.environ.get("MAX_POSTS_SENT_PER_CYCLE", "4"))
MAX_POST_AGE_SECONDS = int(os.environ.get("MAX_POST_AGE_SECONDS", str(2 * 60 * 60)))
MIN_TRANSFER_FEE_MILLIONS_TO_SEND = float(os.environ.get("MIN_TRANSFER_FEE_MILLIONS_TO_SEND", "15"))
SEND_BACKLOG_FOR_NEW_ACCOUNTS = False
NIGHT_MODE_ENABLED = False
NIGHT_START_HOUR = 0
NIGHT_END_HOUR = 7
NIGHT_CHECK_EVERY_SECONDS = 20
NIGHT_MAX_PARALLEL_ACCOUNT_CHECKS = int(os.environ.get("NIGHT_MAX_PARALLEL_ACCOUNT_CHECKS", "3"))
NIGHT_MAX_PARALLEL_POST_SENDS = 4
SEND_LAST_POST_ON_FIRST_RUN = False
SEND_LAST_POST_ON_EVERY_START = False
FORCE_FABRIZIO_STARTUP_TEST_SEND = False  # השאר False; הפעלה כ-True שולחת את פבריציו בכוח בכל הרצה ועוקפת כפילויות
# Startup behavior requested:
# - Check every active reporter.
# - Do NOT send the latest post from every reporter.
# - Send only Fabrizio Romano's latest post on startup.
# Safety: the manual "latest Fabrizio" test is allowed to send ONLY to the quiet/control channel.
# Do not force-send Fabrizio automatically on bot startup, because startup sends use the main broadcast path.
FORCE_SEND_LATEST_FABRIZIO_ON_STARTUP = False
FORCE_SEND_LATEST_FABRIZIO_EVERY_STARTUP = False
FORCED_FABRIZIO_STARTUP_STATE_KEY = "__forced_fabrizio_startup_posts__"
SEND_STARTUP_STATUS_MESSAGE = False
CONTROL_CHAT_ID = required_env_any(
    "NETO_SPORT_FOOTBALL_NEWS_CONTROL_TELEGRAM_CHAT_ID_PRIVATE",
    "NETO_SPORT_FOOTBALL_NEWS_TELEGRAM_CONTROL_CHAT_ID",
    "CONTROL_CHAT_ID",
)
CONTROL_STATE_FILE = "football_control_state.json"
CONTROL_POLL_SECONDS = float(os.environ.get("CONTROL_POLL_SECONDS", "0.8"))
TELEGRAM_BUTTON_FAST_TIMEOUT_SECONDS = float(os.environ.get("TELEGRAM_BUTTON_FAST_TIMEOUT_SECONDS", "1.2"))
CONTROL_RESUME_BACKLOG_SECONDS = 10 * 60
CONTROL_TEMP_MODE_SECONDS = int(os.environ.get("CONTROL_TEMP_MODE_SECONDS", str(2 * 60 * 60)))
CONTROL_PANEL_MESSAGES_ENABLED = os.environ.get("CONTROL_PANEL_MESSAGES_ENABLED", "1") == "1"
CONTROL_SEND_PANEL_ON_STARTUP = os.environ.get("CONTROL_SEND_PANEL_ON_STARTUP", "1") == "1"
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
MAX_PARALLEL_POST_SENDS = int(os.environ.get("MAX_PARALLEL_POST_SENDS", "4"))
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
    "https://nitter.poast.org/{username}/rss",
    "https://nitter.privacydev.net/{username}/rss",
    "https://xcancel.com/{username}/rss",
    "https://nitter.tiekoetter.com/{username}/rss",
]
EXTRA_FEED_TEMPLATES = [
    template.strip()
    for template in re.split(r"[\n,]+", os.environ.get("EXTRA_FEED_TEMPLATES", ""))
    if os.environ.get("RSS_ALLOW_EXTRA_FEED_TEMPLATES", "0") == "1" and template.strip() and "{username}" in template
]
if EXTRA_FEED_TEMPLATES:
    FEED_TEMPLATES = list(dict.fromkeys(FEED_TEMPLATES + EXTRA_FEED_TEMPLATES))
MAX_FEED_TEMPLATES_PER_ACCOUNT = max(5, int(os.environ.get("MAX_FEED_TEMPLATES_PER_ACCOUNT", "5")))
RSS_PRIMARY_SOURCE_COUNT = int(os.environ.get("RSS_PRIMARY_SOURCE_COUNT", "1"))
RSS_ENABLE_FALLBACK = os.environ.get("RSS_DISABLE_FALLBACK", "0") != "1"
RSS_FALLBACK_SOURCE_COUNT = max(4, int(os.environ.get("RSS_FALLBACK_SOURCE_COUNT", "4")))
RSS_ENABLE_STALE_FALLBACK = os.environ.get("RSS_ENABLE_STALE_FALLBACK", "1") == "1"
RSS_STALE_FALLBACK_SECONDS = int(os.environ.get("RSS_STALE_FALLBACK_SECONDS", str(6 * 60 * 60)))
LOGGED_FEED_ISSUE_KEYS: set[str] = set()
FEED_ISSUE_LOG_EVERY_SECONDS = int(os.environ.get("FEED_ISSUE_LOG_EVERY_SECONDS", str(10 * 60)))
FEED_ISSUE_LAST_LOGGED_AT: dict[str, float] = {}
FEED_NO_POSTS_WARNING_AFTER_FAILURES = int(os.environ.get("FEED_NO_POSTS_WARNING_AFTER_FAILURES", "0"))
FEED_NO_POSTS_FAILURE_COUNTS: dict[str, int] = {}
RSS_CONTROL_ALERT_AFTER_FAILURES = int(os.environ.get("RSS_CONTROL_ALERT_AFTER_FAILURES", "0"))
RSS_CONTROL_ALERT_EVERY_SECONDS = int(os.environ.get("RSS_CONTROL_ALERT_EVERY_SECONDS", str(30 * 60)))
RSS_CONTROL_ALERT_LAST_SENT_AT: dict[str, float] = {}
RSS_STALE_LATEST_ALERT_SECONDS = int(os.environ.get("RSS_STALE_LATEST_ALERT_SECONDS", "0"))
RSS_STALE_LATEST_ALERT_EVERY_SECONDS = int(os.environ.get("RSS_STALE_LATEST_ALERT_EVERY_SECONDS", str(6 * 60 * 60)))
RSS_STALE_LATEST_ALERT_LAST_SENT_AT: dict[str, float] = {}
FEED_SOURCE_MAX_PARALLEL = int(os.environ.get("FEED_SOURCE_MAX_PARALLEL", "3"))
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
    r"\bwatch\s+the\s+full\s+(?:video|interview|show|episode)\b",
    r"\bnew\s+episode\b",
    r"\bepisode\s+\d+\b",
    r"\b(?:read|see|click)\s+(?:the\s+)?(?:full\s+)?(?:story|article|piece|column|report)\b",
    r"\b(?:full|exclusive)\s+(?:story|article|piece|column|report)\s+(?:on|in|at)\b",
    r"\b(?:my|our)\s+(?:story|article|piece|column|report)\s+(?:on|in|at)\b",
    r"\b(?:for|with)\s+@[A-Za-z0-9_]{3,40}\s*$",
    r"\b(?:live\s+now|we\s+are\s+live|join\s+us\s+live|live\s+on|stream\s+live)\b",
    r"\b(?:newsletter|substack|website|site|blog)\b",
    r"האזינו",
    r"להאזנה",
    r"לכתבה\s+המלאה",
    r"קראו\s+(?:את\s+)?הכתבה",
    r"קראו\s+עוד",
    r"לקריאה",
    r"לטור\s+המלא",
    r"הטור\s+המלא",
    r"באתר",
    r"כתבתי\s+באתר",
    r"כתבתי\s+על",
    r"הכתבה\s+שלי",
    r"הכתבה\s+המלאה",
    r"הדיווח\s+המלא\s+באתר",
    r"שידור\s+חי",
    r"לייב",
    r"אנחנו\s+בשידור",
    r"הצטרפו\s+לשידור",
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
    "breaking": "דיווח",
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
    "Spurs": "טוטנהאם",
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
    "Raphinha": "ראפיניה",
    "Raphael Dias Belloli": "ראפיניה",
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
    "רפאלניה": "ראפיניה",
    "רפאליניה": "ראפיניה",
    "ראפליניה": "ראפיניה",
    "רפליניה": "ראפיניה",
    "רפה": "ראפיניה",
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
    return bool(MAX_POST_AGE_SECONDS > 0 and post.published_ts and time.time() - post.published_ts > MAX_POST_AGE_SECONDS)


def post_age_text(post: Post) -> str:
    if not getattr(post, "published_ts", 0.0):
        return "גיל לא ידוע"
    seconds = max(0.0, time.time() - float(post.published_ts or 0.0))
    if seconds < 60:
        return f"{seconds:.0f} שניות"
    if seconds < 3600:
        return f"{seconds / 60:.1f} דקות"
    return f"{seconds / 3600:.1f} שעות"


def max_post_age_text() -> str:
    if MAX_POST_AGE_SECONDS <= 0:
        return "ללא הגבלה"
    if MAX_POST_AGE_SECONDS < 3600:
        return f"{MAX_POST_AGE_SECONDS / 60:.0f} דקות"
    return f"{MAX_POST_AGE_SECONDS / 3600:.1f} שעות"


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
    logging.debug(message, *args)


def send_rss_control_alert_if_needed(username: str, failures: int, checked_sources: int, issue_text: str) -> None:
    if not CONTROL_CHAT_ID or RSS_CONTROL_ALERT_AFTER_FAILURES <= 0:
        return
    if failures < RSS_CONTROL_ALERT_AFTER_FAILURES:
        return
    now = time.time()
    last_sent = RSS_CONTROL_ALERT_LAST_SENT_AT.get(username, 0.0)
    if now - last_sent < RSS_CONTROL_ALERT_EVERY_SECONDS:
        return
    RSS_CONTROL_ALERT_LAST_SENT_AT[username] = now
    minutes = max(1, round(failures * current_check_every_seconds() / 60))
    text = (
        "⚠️ התראת RSS\n"
        f"@{username} לא מחזיר פוסטים כבר {failures} בדיקות רצופות, בערך {minutes} דקות.\n"
        f"נבדקו {checked_sources} מקורות RSS.\n"
        f"סיבה אחרונה: {trim(issue_text, 700)}"
    )
    try:
        telegram_api(
            "sendMessage",
            {
                "chat_id": CONTROL_CHAT_ID,
                "text": text,
                "disable_web_page_preview": True,
            },
            max_attempts=1,
        )
        logging.warning("⚠️ נשלחה התראת RSS ללוח השליטה עבור @%s אחרי %s בדיקות בלי פוסטים.", username, failures)
    except Exception as exc:
        logging.warning("⚠️ התראת RSS ללוח השליטה נכשלה עבור @%s: %s", username, exc)


def send_rss_stale_latest_alert_if_needed(username: str, posts: list["Post"]) -> None:
    if not CONTROL_CHAT_ID or RSS_STALE_LATEST_ALERT_SECONDS <= 0 or not posts:
        return
    latest = posts[0]
    if not latest.published_ts:
        return
    age_seconds = max(0.0, time.time() - latest.published_ts)
    if age_seconds < RSS_STALE_LATEST_ALERT_SECONDS:
        return
    now = time.time()
    last_sent = RSS_STALE_LATEST_ALERT_LAST_SENT_AT.get(username, 0.0)
    if now - last_sent < RSS_STALE_LATEST_ALERT_EVERY_SECONDS:
        return
    RSS_STALE_LATEST_ALERT_LAST_SENT_AT[username] = now
    hours = age_seconds / 3600
    text = (
        "⚠️ התראת מקור ישן\n"
        f"@{username} מחזיר פוסטים, אבל הפוסט האחרון בן בערך {hours:.1f} שעות.\n"
        f"מקור שהחזיר: {latest.source_name or 'לא ידוע'}.\n"
        "זה בדרך כלל אומר שהכותב לא פרסם לאחרונה, או שה-feed שמחזיר את המידע תקוע/לא מתעדכן."
    )
    try:
        telegram_api(
            "sendMessage",
            {
                "chat_id": CONTROL_CHAT_ID,
                "text": text,
                "disable_web_page_preview": True,
            },
            max_attempts=1,
        )
        logging.warning("⚠️ נשלחה התראת מקור ישן עבור @%s: האחרון לפני %.0f שניות.", username, age_seconds)
    except Exception as exc:
        logging.warning("⚠️ התראת מקור ישן נכשלה עבור @%s: %s", username, exc)


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
        FEED_NO_POSTS_FAILURE_COUNTS.pop(username, None)
        latest_age = max(0.0, time.time() - float(posts[0].published_ts or 0.0)) if posts[0].published_ts else 0.0
        if RSS_ENABLE_STALE_FALLBACK and fallback_templates and latest_age >= RSS_STALE_FALLBACK_SECONDS:
            fallback_posts, fallback_errors, fallback_timeouts = collect_posts_from_feed_templates(username, fallback_templates)
            if fallback_posts and float(fallback_posts[0].published_ts or 0.0) > float(posts[0].published_ts or 0.0):
                logging.info(
                    "🔁 RSS: המקור הראשי עבור @%s ישן/תקוע, נלקח מקור גיבוי %s עם פוסט חדש יותר.",
                    username,
                    fallback_posts[0].source_name,
                )
                send_rss_stale_latest_alert_if_needed(username, fallback_posts)
                return fallback_posts
            if fallback_errors or fallback_timeouts:
                logging.debug(
                    "RSS: ניסיון גיבוי בגלל מקור ישן עבור @%s לא החזיר מקור חדש יותר. errors=%s timeouts=%s",
                    username,
                    "; ".join(fallback_errors[:4]),
                    ", ".join(fallback_timeouts[:4]),
                )
        send_rss_stale_latest_alert_if_needed(username, posts)
        return posts

    fallback_errors: list[str] = []
    fallback_timeouts: list[str] = []
    if fallback_templates:
        fallback_posts, fallback_errors, fallback_timeouts = collect_posts_from_feed_templates(username, fallback_templates)
        if fallback_posts:
            FEED_NO_POSTS_FAILURE_COUNTS.pop(username, None)
            send_rss_stale_latest_alert_if_needed(username, fallback_posts)
            primary_issue_parts = []
            if feed_errors:
                primary_issue_parts.append("errors: " + "; ".join(feed_errors[:4]))
            if timed_out_sources:
                primary_issue_parts.append("timeouts: " + ", ".join(timed_out_sources[:4]))
            logging.info(
                "🔁 RSS: מקור גיבוי הופעל עבור @%s. נמצאו %s פוסטים דרך %s",
                username,
                len(fallback_posts),
                fallback_posts[0].source_name,
            )
            if primary_issue_parts:
                logging.debug("RSS: פרטי מקור הגיבוי עבור @%s: %s", username, " | ".join(primary_issue_parts))
            return fallback_posts

    if not posts:
        no_posts_failures = FEED_NO_POSTS_FAILURE_COUNTS.get(username, 0) + 1
        FEED_NO_POSTS_FAILURE_COUNTS[username] = no_posts_failures
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
        if FEED_NO_POSTS_WARNING_AFTER_FAILURES > 0 and no_posts_failures >= FEED_NO_POSTS_WARNING_AFTER_FAILURES:
            log_feed_issue(
                username,
                "RSS: לא נמצאו פוסטים עבור @%s אחרי %s בדיקות רצופות. נבדקו %s מקורות. ינסה שוב בשקט.",
                username,
                no_posts_failures,
                len(checked_templates),
            )
        send_rss_control_alert_if_needed(username, no_posts_failures, len(checked_templates), issue_text)
    return posts


def fetch_posts_safely(username: str) -> tuple[str, list[Post]]:
    started = time.perf_counter()
    try:
        posts = fetch_posts(username)
        daily_stat_add_timing("scan_seconds", time.perf_counter() - started)
        return username, posts
    except Exception as exc:
        daily_stat_add_timing("scan_seconds", time.perf_counter() - started)
        logging.warning("⚠️ שליפת פוסטים נכשלה עבור @%s: %s", username, exc)
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


def app_data_dir() -> Path:
    global APP_DATA_DIR_CACHE
    if APP_DATA_DIR_CACHE is not None:
        return APP_DATA_DIR_CACHE
    candidates: list[Path] = []
    if BOT_DATA_DIR:
        candidates.append(Path(BOT_DATA_DIR))
    data_path = Path("/data")
    if data_path.exists():
        candidates.append(data_path)
    candidates.append(Path(__file__).resolve().parent)
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            test_path = candidate / ".football_bot_write_test"
            test_path.write_text("ok", encoding="utf-8")
            test_path.unlink(missing_ok=True)
            APP_DATA_DIR_CACHE = candidate
            return candidate
        except Exception:
            continue
    APP_DATA_DIR_CACHE = Path(__file__).resolve().parent
    return APP_DATA_DIR_CACHE


def app_data_path(filename: str) -> Path:
    target = app_data_dir() / filename
    legacy = Path(__file__).resolve().parent / filename
    if target != legacy and not target.exists() and legacy.exists():
        try:
            shutil.copy2(legacy, target)
        except Exception as exc:
            logging.debug("לא הצליח להעתיק קובץ מצב ישן אל תיקיית הדאטה: %s", exc)
    return target


def shabbat_cache_path() -> Path:
    return app_data_path(SHABBAT_CACHE_FILE)


def control_state_path() -> Path:
    return app_data_path(CONTROL_STATE_FILE)


def load_control_state() -> dict[str, Any]:
    path = control_state_path()
    if not path.exists():
        return {"paused": False, CONTROL_STATE_DIMARZIO_REENABLED_KEY: True}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"paused": False, CONTROL_STATE_DIMARZIO_REENABLED_KEY: True}
        data["paused"] = bool(data.get("paused", False))
        if not data.get(CONTROL_STATE_DIMARZIO_REENABLED_KEY):
            raw_disabled = data.get("disabled_base_accounts", [])
            if isinstance(raw_disabled, list):
                data["disabled_base_accounts"] = [account for account in raw_disabled if account != "DiMarzio"]
            data[CONTROL_STATE_DIMARZIO_REENABLED_KEY] = True
        return data
    except Exception:
        return {"paused": False, CONTROL_STATE_DIMARZIO_REENABLED_KEY: True}


def enabled_optional_accounts_from_state(state: dict[str, Any] | None = None) -> list[str]:
    state = state or load_control_state()
    raw_accounts = state.get("enabled_optional_accounts", list(DEFAULT_ENABLED_OPTIONAL_ACCOUNTS))
    if not isinstance(raw_accounts, list):
        raw_accounts = []
    allowed = set(OPTIONAL_CONTROLLED_ACCOUNTS)
    enabled = set(raw_accounts)
    return [username for username in OPTIONAL_CONTROLLED_ACCOUNTS if username in allowed and username in enabled]


def account_enabled_at_from_state(state: dict[str, Any] | None = None) -> dict[str, float]:
    state = state or load_control_state()
    raw = state.get("account_enabled_at", {})
    if not isinstance(raw, dict):
        return {}
    allowed = set(X_ACCOUNTS) | set(OPTIONAL_CONTROLLED_ACCOUNTS)
    result: dict[str, float] = {}
    for username, value in raw.items():
        if username not in allowed:
            continue
        try:
            timestamp = float(value or 0.0)
        except (TypeError, ValueError):
            continue
        if timestamp > 0:
            result[str(username)] = timestamp
    return result


def mark_account_enabled_at(state: dict[str, Any], username: str) -> dict[str, float]:
    enabled_at = account_enabled_at_from_state(state)
    enabled_at[username] = time.time()
    return enabled_at


def remove_account_enabled_at(state: dict[str, Any], username: str) -> dict[str, float]:
    enabled_at = account_enabled_at_from_state(state)
    enabled_at.pop(username, None)
    return enabled_at


def account_enabled_since(username: str, state: dict[str, Any] | None = None) -> float:
    return float(account_enabled_at_from_state(state).get(username, 0.0) or 0.0)


def disabled_base_accounts_from_state(state: dict[str, Any] | None = None) -> list[str]:
    state = state or load_control_state()
    raw_accounts = state.get("disabled_base_accounts", [])
    if not isinstance(raw_accounts, list):
        raw_accounts = []
    allowed = set(X_ACCOUNTS)
    disabled = set(raw_accounts) | LOCKED_DISABLED_BASE_ACCOUNTS
    return [username for username in X_ACCOUNTS if username in allowed and username in disabled]


def active_x_accounts() -> list[str]:
    disabled_base = set(disabled_base_accounts_from_state())
    accounts = [username for username in X_ACCOUNTS if username not in disabled_base]
    for username in enabled_optional_accounts_from_state():
        if username not in accounts:
            accounts.append(username)
    return accounts


def save_control_state(paused: bool | None = None, **updates: Any) -> None:
    global CANONICAL_ENTITY_ALIAS_CACHE
    state = load_control_state()
    if paused is not None:
        state["paused"] = paused
    state.update(updates)
    if "team_tier_overrides" in updates or "custom_team_catalog" in updates:
        CANONICAL_ENTITY_ALIAS_CACHE = None
    path = control_state_path()
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)


def is_control_paused() -> bool:
    return bool(load_control_state().get("paused", False))


def _control_until_active(state: dict[str, Any], key: str) -> bool:
    return float(state.get(key, 0.0) or 0.0) > time.time()


def strict_filter_active(state: dict[str, Any] | None = None) -> bool:
    state = state or load_control_state()
    return bool(state.get("strict_filter", False)) or _control_until_active(state, "strict_filter_until")


def elite_only_mode_active(state: dict[str, Any] | None = None) -> bool:
    state = state or load_control_state()
    return bool(state.get("elite_only", False)) or _control_until_active(state, "elite_only_until")


def _control_mode_status_text(state: dict[str, Any], key: str) -> str:
    # המצבים האלה כבר לא זמניים לשעתיים. הם נשמרים כמצב קבוע עד שלוחצים שוב/מבטלים הכל.
    bool_key = key.removesuffix("_until")
    if bool(state.get(bool_key, False)):
        return "פעיל"
    # תמיכה לאחור בקובץ מצב ישן שהיה בו until.
    until = float(state.get(key, 0.0) or 0.0)
    remaining = until - time.time()
    if remaining <= 0:
        return "כבוי"
    minutes = max(1, int(math.ceil(remaining / 60)))
    return f"פעיל לעוד {minutes} דק׳"


def night_mode_control_active(state: dict[str, Any] | None = None) -> bool:
    state = state or load_control_state()
    return bool(state.get("night_mode", False)) or _control_until_active(state, "night_mode_until")


CONTROL_FILTER_KEYS = (
    "block_rumors",
    "block_national",
    "block_injuries",
    "block_social",
    "only_herewego",
    "only_top5",
    "only_real_barca",
)


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
        status = "כבוי קבוע" if username in LOCKED_DISABLED_BASE_ACCOUNTS else ("כבוי" if username in disabled_base else "פעיל")
        keyboard.append([{"text": f"{label}: {status}", "callback_data": f"football_base_account:{username}"}])
    for username in OPTIONAL_CONTROLLED_ACCOUNTS:
        label = OPTIONAL_CONTROLLED_ACCOUNT_LABELS.get(username, username)
        status = "פעיל" if username in enabled_optional else "כבוי"
        keyboard.append([{"text": f"{label}: {status}", "callback_data": f"football_account:{username}"}])
    return stable_reply_markup(keyboard)


def writers_management_reply_markup(paused: bool) -> dict[str, Any]:
    markup = control_reply_markup(paused)
    keyboard = list(markup.get("inline_keyboard", []))
    keyboard.append([{"text": stable_button_label("⬅️ חזרה לראשי"), "callback_data": "football_quick_main"}])
    return {"inline_keyboard": keyboard}


def _flag_status(state: dict[str, Any], key: str) -> str:
    return "פעיל" if bool(state.get(key, False)) else "כבוי"


def _onoff_label(text: str, state: dict[str, Any], key: str) -> str:
    return f"{text}: {_flag_status(state, key)}"


CONTROL_BUTTON_TEXT_WIDTH = int(os.environ.get("CONTROL_BUTTON_TEXT_WIDTH", "34"))
CONTROL_BUTTON_PAD = "\u2800"


def stable_button_label(text: str) -> str:
    """Pad one-button rows so Telegram keeps a steady keyboard width."""
    label = text or ""
    visible_len = len(re.sub(r"[\ufe0f\u200e\u200f\u202a-\u202e\u2066-\u2069]", "", label))
    if visible_len >= CONTROL_BUTTON_TEXT_WIDTH:
        return label
    missing = CONTROL_BUTTON_TEXT_WIDTH - visible_len
    left_pad = CONTROL_BUTTON_PAD * (missing // 2)
    right_pad = CONTROL_BUTTON_PAD * (missing - (missing // 2))
    return f"{left_pad}{label}{right_pad}"


def stable_reply_markup(keyboard: list[list[dict[str, str]]]) -> dict[str, Any]:
    stable_keyboard: list[list[dict[str, str]]] = []
    for row in keyboard:
        if len(row) == 1 and "text" in row[0]:
            button = dict(row[0])
            button["text"] = stable_button_label(str(button.get("text", "")))
            stable_keyboard.append([button])
        else:
            stable_keyboard.append(row)
    return {"inline_keyboard": stable_keyboard}


def quick_control_reply_markup() -> dict[str, Any]:
    keyboard = [
        [
            {"text": "👤 בדוק כתב ספציפי", "callback_data": "football_choose_account_latest"},
        ],
        [
            {"text": "🔎 בדיקה וניטור", "callback_data": "football_menu_monitor"},
        ],
        [
            {"text": "👥 ניהול כתבים", "callback_data": "football_menu_writers"},
        ],
        [
            {"text": "🏟️ ניהול קבוצות", "callback_data": "football_menu_teams"},
        ],
        [
            {"text": "🛡️ הגדרות וסינון", "callback_data": "football_menu_filter"},
        ],
        [
            {"text": "📊 סטטיסטיקות", "callback_data": "football_menu_stats"},
        ],
        [
            {"text": "📊 סיכום היום עכשיו", "callback_data": "football_daily_report_now"},
        ],
        [
            {"text": "ℹ️ הסבר כפתורים", "callback_data": "football_buttons_help"},
        ],
    ]
    return stable_reply_markup(keyboard)


def monitor_menu_reply_markup() -> dict[str, Any]:
    keyboard = [
        [{"text": "🔄 בדוק את כל הכתבים עכשיו", "callback_data": "football_check_all_accounts_now"}],
        [{"text": "👥 כתבים פעילים בפועל", "callback_data": "football_active_accounts_status"}],
        [{"text": "📡 בדיקת RSS", "callback_data": "football_rss_status"}],
        [{"text": "🤖 בדיקת Gemini", "callback_data": "football_gemini_status"}],
        [{"text": "♻️ שחרור קירור Gemini", "callback_data": "football_gemini_clear_local_cooldown"}],
        [{"text": gemini_guard_button_label(), "callback_data": "football_gemini_toggle_quota_guard"}],
        [{"text": "📬 פוסט אחרון שנשלח", "callback_data": "football_last_sent_post"}],
        [{"text": "↩️ למה לא נשלח", "callback_data": "football_last_blocked"}],
        [{"text": "🧠 כפילות אחרונה", "callback_data": "football_last_duplicate"}],
        [{"text": "ℹ️ הסבר בדיקה וניטור", "callback_data": "football_category_help:monitor"}],
        [{"text": "⬅️ חזרה לראשי", "callback_data": "football_quick_main"}],
    ]
    return stable_reply_markup(keyboard)


def filter_menu_reply_markup() -> dict[str, Any]:
    state = load_control_state()
    keyboard = [
        [
            {"text": f"🌙 מצב לילה: {_control_mode_status_text(state, 'night_mode_until')}", "callback_data": "football_toggle_mode:night_mode"},
        ],
        [
            {"text": f"⭐ רק גדולות: {_control_mode_status_text(state, 'elite_only_until')}", "callback_data": "football_toggle_mode:elite_only"},
        ],
        [
            {"text": f"🛡️ סינון קשוח: {_control_mode_status_text(state, 'strict_filter_until')}", "callback_data": "football_toggle_mode:strict_filter"},
        ],
        [
            {"text": _onoff_label("🚨 חסימת שמועות", state, "block_rumors"), "callback_data": "football_toggle_filter:block_rumors"},
        ],
        [
            {"text": _onoff_label("🌍 חסימת נבחרות", state, "block_national"), "callback_data": "football_toggle_filter:block_national"},
        ],
        [
            {"text": _onoff_label("🩺 חסימת פציעות", state, "block_injuries"), "callback_data": "football_toggle_filter:block_injuries"},
        ],
        [
            {"text": _onoff_label("📸 חסימת חברתי", state, "block_social"), "callback_data": "football_toggle_filter:block_social"},
        ],
        [
            {"text": _onoff_label("🟢 רק Here We Go", state, "only_herewego"), "callback_data": "football_toggle_filter:only_herewego"},
        ],
        [
            {"text": _onoff_label("🏅 רק טופ 5", state, "only_top5"), "callback_data": "football_toggle_filter:only_top5"},
        ],
        [
            {"text": _onoff_label("🔵⚪ רק ריאל וברצלונה", state, "only_real_barca"), "callback_data": "football_toggle_filter:only_real_barca"},
        ],
    ]
    if elite_only_mode_active(state) or strict_filter_active(state) or night_mode_control_active(state) or any(bool(state.get(k, False)) for k in CONTROL_FILTER_KEYS):
        keyboard.append([{"text": "🔓 לבטל את כל הסינונים", "callback_data": "football_clear_temp_modes"}])
    keyboard.append([{"text": "ℹ️ הסבר הגדרות וסינון", "callback_data": "football_category_help:filter"}])
    keyboard.append([{"text": "⬅️ חזרה לראשי", "callback_data": "football_quick_main"}])
    return stable_reply_markup(keyboard)


def stats_menu_reply_markup() -> dict[str, Any]:
    keyboard = [
        [{"text": "🏆 הכתב הכי פעיל היום", "callback_data": "football_stat_active_writer"}],
        [{"text": "✅ כמה נשלחו היום", "callback_data": "football_stat_sent_today"}],
        [{"text": "🚫 כמה נחסמו היום", "callback_data": "football_stat_blocked_today"}],
        [{"text": "📊 אחוז הצלחה היום", "callback_data": "football_stat_success_rate"}],
        [{"text": "⏳ פוסטים ישנים מדי היום", "callback_data": "football_stat_old_posts"}],
        [{"text": "📋 כמה פוסטים כל כתב פרסם", "callback_data": "football_stat_posts_by_writer"}],
        [{"text": "🧱 טופ 10 סיבות חסימה", "callback_data": "football_stat_top_blocks"}],
        [{"text": "😅 איזה כתב נחסם הכי הרבה", "callback_data": "football_stat_most_blocked_writer"}],
        [{"text": "📚 הפוסט הארוך ביותר היום", "callback_data": "football_stat_longest_post"}],
        [{"text": "✂️ הפוסט הקצר ביותר היום", "callback_data": "football_stat_shortest_post"}],
        [{"text": "⚡ זמן סריקה ממוצע", "callback_data": "football_stat_avg_scan"}],
        [{"text": "🧠 זמן תרגום ממוצע", "callback_data": "football_stat_avg_translation"}],
        [{"text": "❌ כמה פעמים Gemini נכשל", "callback_data": "football_stat_gemini_failures"}],
        [{"text": "ℹ️ הסבר סטטיסטיקות", "callback_data": "football_category_help:stats"}],
        [{"text": "⬅️ חזרה לראשי", "callback_data": "football_quick_main"}],
    ]
    return stable_reply_markup(keyboard)


def teams_menu_reply_markup() -> dict[str, Any]:
    keyboard = [
        [{"text": "👀 צפייה ברשימות", "callback_data": "football_teams_group:view"}],
        [{"text": "⚙️ פעולות", "callback_data": "football_teams_group:actions"}],
        [{"text": "⬅️ חזרה לראשי", "callback_data": "football_quick_main"}],
    ]
    return stable_reply_markup(keyboard)


def teams_view_menu_reply_markup() -> dict[str, Any]:
    keyboard = [
        [{"text": "⭐ דרג א - קבוצות גדולות", "callback_data": "football_teams_list:tier1"}],
        [{"text": "✅ דרג ב - דיווחים סופיים", "callback_data": "football_teams_list:tier2"}],
        [{"text": "⚽ דרג ג - שאר ליגות בכירות", "callback_data": "football_teams_list:tier3"}],
        [{"text": "🌍 נבחרות", "callback_data": "football_teams_list:national"}],
        [{"text": "⬅️ חזרה לניהול קבוצות", "callback_data": "football_menu_teams"}],
    ]
    return stable_reply_markup(keyboard)


def teams_actions_menu_reply_markup() -> dict[str, Any]:
    keyboard = [
        [{"text": "➕ הוסף קבוצה/נבחרת", "callback_data": "football_teams_action:add"}],
        [{"text": "➖ הסר קבוצה/נבחרת", "callback_data": "football_teams_action:remove"}],
        [{"text": "🔁 העבר דרג", "callback_data": "football_teams_action:move"}],
        [{"text": "⬅️ חזרה לניהול קבוצות", "callback_data": "football_menu_teams"}],
    ]
    return stable_reply_markup(keyboard)


def team_tier_choice_reply_markup(action: str) -> dict[str, Any]:
    keyboard = [
        [{"text": "⭐ דרג א - קבוצות גדולות", "callback_data": f"football_teams_pick_tier:{action}:tier1"}],
        [{"text": "✅ דרג ב - דיווחים סופיים", "callback_data": f"football_teams_pick_tier:{action}:tier2"}],
        [{"text": "⚽ דרג ג - שאר ליגות בכירות", "callback_data": f"football_teams_pick_tier:{action}:tier3"}],
        [{"text": "🌍 נבחרות", "callback_data": f"football_teams_pick_tier:{action}:national"}],
        [{"text": "⬅️ חזרה לניהול קבוצות", "callback_data": "football_menu_teams"}],
    ]
    return stable_reply_markup(keyboard)


def team_after_action_reply_markup(tier: str = "") -> dict[str, Any]:
    keyboard: list[list[dict[str, str]]] = []
    if tier in TEAM_TIER_LABELS:
        keyboard.append([{"text": f"👀 צפה ב{TEAM_TIER_LABELS[tier]}", "callback_data": f"football_teams_list:{tier}"}])
    keyboard.extend(
        [
            [{"text": "➕ הוסף עוד", "callback_data": "football_teams_action:add"}],
            [{"text": "🏟️ חזרה לניהול קבוצות", "callback_data": "football_menu_teams"}],
        ]
    )
    return stable_reply_markup(keyboard)


CONTROL_TEST_ACCOUNT_ORDER = [
    "FabrizioRomano",
    "David_Ornstein",
    "DiMarzio",
    "JacobsBen",
    "NicoSchira",
    "ffpolo",
    "AranchaMOBILE",
    "Plettigoal",
    "MatteMoretto",
    "FabriceHawkins",
    "gerardromero",
    "MonfortCarlos",
    "JLSanchez78",
    "jfelixdiaz",
]


def all_control_test_accounts() -> list[str]:
    # הרשימה הקבועה במסך "בדוק כתב ספציפי".
    # היא כוללת בדיוק את הכתבים שמוגדרים בלוח הבקרה, גם אם כתב מסוים כבוי כרגע.
    # פתיחת התפריט אינה מבצעת שליפה ואינה משתמשת ב-Gemini.
    return [username for username in CONTROL_TEST_ACCOUNT_ORDER if username not in LOCKED_DISABLED_BASE_ACCOUNTS]


def recent_24h_posts(posts: list[Post]) -> list[Post]:
    """Posts whose published time is within the last 24 hours.

    RSS mirrors often return a fixed page of old posts. For button statistics we
    count only real posts from the last 24 hours, not every item returned by RSS.
    """
    cutoff = time.time() - 24 * 60 * 60
    return [post for post in posts if float(getattr(post, "published_ts", 0.0) or 0.0) >= cutoff]


def recent_24h_count(posts: list[Post]) -> int:
    return len(recent_24h_posts(posts))


TEAM_TIER_LABELS = {
    "tier1": "דרג א - קבוצות גדולות",
    "tier2": "דרג ב - דיווחים סופיים",
    "tier3": "דרג ג - שאר ליגות בכירות",
    "national": "נבחרות",
}

TEAM_TIER_ALIASES = {
    "א": "tier1", "דרג א": "tier1", "גדולות": "tier1", "tier1": "tier1",
    "ב": "tier2", "דרג ב": "tier2", "סופי": "tier2", "סופיים": "tier2", "tier2": "tier2",
    "ג": "tier3", "דרג ג": "tier3", "ליגות בכירות": "tier3", "שאר ליגות בכירות": "tier3", "tier3": "tier3",
    "נבחרות": "national", "נבחרת": "national", "national": "national",
}

TEAM_CATALOG: dict[str, dict[str, Any]] = {
    "real madrid": {"name": "ריאל מדריד", "tier": "tier1", "aliases": ["Real Madrid", "RMA", "ריאל מדריד"]},
    "barcelona": {"name": "ברצלונה", "tier": "tier1", "aliases": ["Barcelona", "Barca", "Barça", "FC Barcelona", "ברצלונה", "בארסה"]},
    "manchester city": {"name": "מנצ'סטר סיטי", "tier": "tier1", "aliases": ["Manchester City", "Man City", "MCFC", "מנצ'סטר סיטי"]},
    "manchester united": {"name": "מנצ'סטר יונייטד", "tier": "tier1", "aliases": ["Manchester United", "Man United", "Man Utd", "MUFC", "מנצ'סטר יונייטד"]},
    "liverpool": {"name": "ליברפול", "tier": "tier1", "aliases": ["Liverpool", "LFC", "ליברפול"]},
    "chelsea": {"name": "צ'לסי", "tier": "tier1", "aliases": ["Chelsea", "CFC", "צ'לסי"]},
    "arsenal": {"name": "ארסנל", "tier": "tier1", "aliases": ["Arsenal", "AFC", "ארסנל"]},
    "bayern munich": {"name": "באיירן מינכן", "tier": "tier1", "aliases": ["Bayern Munich", "FC Bayern", "Bayern", "FCB", "באיירן מינכן", "באיירן"]},
    "psg": {"name": "פריז סן ז'רמן", "tier": "tier1", "aliases": ["Paris Saint-Germain", "PSG", "פריז סן ז'רמן", "פ.ס.ז"]},
    "juventus": {"name": "יובנטוס", "tier": "tier1", "aliases": ["Juventus", "Juve", "יובנטוס"]},
    "ac milan": {"name": "מילאן", "tier": "tier1", "aliases": ["AC Milan", "Milan", "ACM", "מילאן", "איי סי מילאן"]},
    "inter": {"name": "אינטר", "tier": "tier1", "aliases": ["Inter", "Inter Milan", "Internazionale", "אינטר", "אינטר מילאנו"]},
    "borussia dortmund": {"name": "דורטמונד", "tier": "tier1", "aliases": ["Borussia Dortmund", "Dortmund", "BVB", "דורטמונד"]},
    "atletico madrid": {"name": "אתלטיקו מדריד", "tier": "tier1", "aliases": ["Atletico Madrid", "Atlético Madrid", "Atleti", "ATM", "אתלטיקו מדריד"]},
    "tottenham": {"name": "טוטנהאם", "tier": "tier2", "aliases": ["Tottenham", "Spurs", "THFC", "טוטנהאם", "ספרס"]},
    "newcastle": {"name": "ניוקאסל", "tier": "tier2", "aliases": ["Newcastle", "Newcastle United", "NUFC", "ניוקאסל"]},
    "aston villa": {"name": "אסטון וילה", "tier": "tier2", "aliases": ["Aston Villa", "AVFC", "אסטון וילה"]},
    "west ham": {"name": "ווסטהאם", "tier": "tier2", "aliases": ["West Ham", "West Ham United", "WHUFC", "ווסטהאם"]},
    "everton": {"name": "אברטון", "tier": "tier2", "aliases": ["Everton", "EFC", "אברטון"]},
    "brighton": {"name": "ברייטון", "tier": "tier2", "aliases": ["Brighton", "BHAFC", "ברייטון"]},
    "roma": {"name": "רומא", "tier": "tier2", "aliases": ["Roma", "רומא"]},
    "napoli": {"name": "נאפולי", "tier": "tier2", "aliases": ["Napoli", "נאפולי"]},
    "atalanta": {"name": "אטאלנטה", "tier": "tier2", "aliases": ["Atalanta", "אטאלנטה", "אטלנטה"]},
    "lazio": {"name": "לאציו", "tier": "tier2", "aliases": ["Lazio", "לאציו"]},
    "fiorentina": {"name": "פיורנטינה", "tier": "tier2", "aliases": ["Fiorentina", "פיורנטינה"]},
    "bayer leverkusen": {"name": "באייר לברקוזן", "tier": "tier2", "aliases": ["Bayer Leverkusen", "Leverkusen", "B04", "לברקוזן"]},
    "marseille": {"name": "מארסיי", "tier": "tier2", "aliases": ["Marseille", "Olympique Marseille", "OM", "מארסיי", "מרסיי"]},
    "lyon": {"name": "ליון", "tier": "tier2", "aliases": ["Lyon", "Olympique Lyon", "OL", "ליון"]},
    "monaco": {"name": "מונאקו", "tier": "tier2", "aliases": ["Monaco", "AS Monaco", "ASM", "מונאקו"]},
    "ajax": {"name": "אייאקס", "tier": "tier2", "aliases": ["Ajax", "אייאקס"]},
    "benfica": {"name": "בנפיקה", "tier": "tier2", "aliases": ["Benfica", "SL Benfica", "בנפיקה"]},
    "porto": {"name": "פורטו", "tier": "tier2", "aliases": ["Porto", "FC Porto", "פורטו"]},
    "sporting": {"name": "ספורטינג", "tier": "tier2", "aliases": ["Sporting CP", "Sporting Lisbon", "ספורטינג", "ספורטינג ליסבון"]},
    "galatasaray": {"name": "גלאטסראיי", "tier": "tier2", "aliases": ["Galatasaray", "גלאטסראיי"]},
    "fenerbahce": {"name": "פנרבחצ'ה", "tier": "tier2", "aliases": ["Fenerbahce", "Fenerbahçe", "פנרבחצ'ה"]},
    "flamengo": {"name": "פלמנגו", "tier": "tier2", "aliases": ["Flamengo", "CR Flamengo", "פלמנגו"]},
    "boca juniors": {"name": "בוקה ג'וניורס", "tier": "tier2", "aliases": ["Boca Juniors", "בוקה ג'וניורס"]},
    "river plate": {"name": "ריבר פלייט", "tier": "tier2", "aliases": ["River Plate", "ריבר פלייט"]},
    "inter miami": {"name": "אינטר מיאמי", "tier": "tier2", "aliases": ["Inter Miami", "Inter Miami CF", "אינטר מיאמי"]},
}

TEAM_CATALOG.update({
    "bournemouth": {"name": "בורנמות", "tier": "tier3", "aliases": ["Bournemouth", "AFC Bournemouth", "בורנמות"]},
    "brentford": {"name": "ברנטפורד", "tier": "tier3", "aliases": ["Brentford", "ברנטפורד"]},
    "fulham": {"name": "פולהאם", "tier": "tier3", "aliases": ["Fulham", "פולהאם"]},
    "wolves": {"name": "וולבס", "tier": "tier3", "aliases": ["Wolves", "Wolverhampton", "וולבס"]},
    "crystal palace": {"name": "קריסטל פאלאס", "tier": "tier3", "aliases": ["Crystal Palace", "קריסטל פאלאס"]},
    "nottingham forest": {"name": "נוטינגהאם פורסט", "tier": "tier3", "aliases": ["Nottingham Forest", "Forest", "נוטינגהאם", "נוטינגהאם פורסט"]},
    "leeds": {"name": "לידס", "tier": "tier3", "aliases": ["Leeds", "Leeds United", "לידס"]},
    "sunderland": {"name": "סנדרלנד", "tier": "tier3", "aliases": ["Sunderland", "סנדרלנד"]},
    "leicester": {"name": "לסטר", "tier": "tier3", "aliases": ["Leicester", "Leicester City", "לסטר"]},
    "southampton": {"name": "סאות'המפטון", "tier": "tier3", "aliases": ["Southampton", "סאות'המפטון"]},
    "burnley": {"name": "ברנלי", "tier": "tier3", "aliases": ["Burnley", "ברנלי"]},
    "bologna": {"name": "בולוניה", "tier": "tier3", "aliases": ["Bologna", "בולוניה"]},
    "torino": {"name": "טורינו", "tier": "tier3", "aliases": ["Torino", "טורינו"]},
    "udinese": {"name": "אודינזה", "tier": "tier3", "aliases": ["Udinese", "אודינזה"]},
    "sassuolo": {"name": "ססואולו", "tier": "tier3", "aliases": ["Sassuolo", "ססואולו"]},
    "como": {"name": "קומו", "tier": "tier3", "aliases": ["Como", "קומו"]},
    "parma": {"name": "פארמה", "tier": "tier3", "aliases": ["Parma", "פארמה"]},
    "verona": {"name": "ורונה", "tier": "tier3", "aliases": ["Verona", "Hellas Verona", "ורונה"]},
    "venezia": {"name": "ונציה", "tier": "tier3", "aliases": ["Venezia", "Venezia FC", "Venice", "ונציה"]},
    "genoa": {"name": "גנואה", "tier": "tier3", "aliases": ["Genoa", "גנואה"]},
    "cagliari": {"name": "קליארי", "tier": "tier3", "aliases": ["Cagliari", "קליארי"]},
    "lecce": {"name": "לצ'ה", "tier": "tier3", "aliases": ["Lecce", "לצ'ה"]},
    "girona": {"name": "ג'ירונה", "tier": "tier3", "aliases": ["Girona", "ג'ירונה"]},
    "getafe": {"name": "חטאפה", "tier": "tier3", "aliases": ["Getafe", "חטאפה"]},
    "osasuna": {"name": "אוססונה", "tier": "tier3", "aliases": ["Osasuna", "אוססונה"]},
    "mallorca": {"name": "מיורקה", "tier": "tier3", "aliases": ["Mallorca", "מיורקה"]},
    "rayo vallecano": {"name": "ראיו וייקאנו", "tier": "tier3", "aliases": ["Rayo Vallecano", "Rayo", "ראיו", "ראיו וייקאנו"]},
    "celta vigo": {"name": "סלטה ויגו", "tier": "tier3", "aliases": ["Celta Vigo", "Celta", "סלטה", "סלטה ויגו"]},
    "espanyol": {"name": "אספניול", "tier": "tier3", "aliases": ["Espanyol", "אספניול"]},
    "nice": {"name": "ניס", "tier": "tier3", "aliases": ["Nice", "OGC Nice", "ניס"]},
    "strasbourg": {"name": "שטרסבורג", "tier": "tier3", "aliases": ["Strasbourg", "שטרסבורג"]},
    "toulouse": {"name": "טולוז", "tier": "tier3", "aliases": ["Toulouse", "טולוז"]},
    "freiburg": {"name": "פרייבורג", "tier": "tier3", "aliases": ["Freiburg", "פרייבורג"]},
    "wolfsburg": {"name": "וולפסבורג", "tier": "tier3", "aliases": ["Wolfsburg", "וולפסבורג"]},
    "werder bremen": {"name": "ורדר ברמן", "tier": "tier3", "aliases": ["Werder Bremen", "ורדר ברמן"]},
    "hoffenheim": {"name": "הופנהיים", "tier": "tier3", "aliases": ["Hoffenheim", "הופנהיים"]},
    "mainz": {"name": "מיינץ", "tier": "tier3", "aliases": ["Mainz", "מיינץ"]},
    "union berlin": {"name": "אוניון ברלין", "tier": "tier3", "aliases": ["Union Berlin", "אוניון ברלין"]},
    "levante": {"name": "לבאנטה", "tier": "tier3", "aliases": ["Levante", "לבאנטה"]},
    "malaga": {"name": "מלאגה", "tier": "tier3", "aliases": ["Malaga", "Málaga", "מלאגה"]},
    "racing santander": {"name": "ראסינג סנטנדר", "tier": "tier3", "aliases": ["Racing Santander", "Racing", "ראסינג", "ראסינג סנטנדר", "ראסטינג"]},
})

KNOWN_UNTRACKED_DESTINATION_CLUB_ALIASES = (
    "Aalborg", "Aberdeen", "Al Ahli", "Al Ettifaq", "Al Hilal", "Al Ittihad", "Al Nassr",
    "Al Qadsiah", "Al Shabab", "Alanyaspor", "Alaves", "Anderlecht", "Angers",
    "Antalyaspor", "Athletic Bilbao", "Athletic Club", "Augsburg", "Auxerre",
    "AZ Alkmaar", "Basel", "Besiktas", "Blackburn",
    "Bordeaux", "Borussia Monchengladbach", "Brescia", "Bristol City", "Brugge",
    "Cardiff", "Catanzaro",
    "Ceara", "Cesena", "Club Brugge", "Coventry", "Cruzeiro", "Cruz Azul",
    "CSKA Moscow", "Deportivo La Coruna", "Derby County", "Dinamo Zagreb",
    "Dynamo Kyiv", "Elche", "Estudiantes", "Feyenoord", "Fortaleza", "Gent",
    "Eintracht Frankfurt", "Goztepe", "Granada", "Gremio", "Hamburg", "Hannover", "Hertha Berlin",
    "Hull City", "Independiente", "Ipswich", "Jagiellonia", "Juve Stabia", "Kaiserslautern",
    "Karlsruhe", "Kayserispor", "Koln", "Konyaspor", "Las Palmas", "Leganes",
    "Lech Poznan", "Lens", "Levante", "Lille", "Lokomotiv Moscow", "Malaga", "Middlesbrough",
    "Millwall", "Modena", "Monza", "Nantes", "Norwich", "Olympiacos", "PAOK",
    "Panathinaikos", "Palermo", "Pisa", "Portsmouth", "Potenza", "Preston", "QPR",
    "Racing Santander", "Rangers", "RB Leipzig", "Real Betis", "Real Oviedo", "Real Sociedad", "Real Valladolid",
    "Rosario Central", "Rotherham", "Rubin Kazan", "Sampdoria", "Santos",
    "Sao Paulo", "Schalke", "Sevilla", "Sheffield Wednesday", "Shakhtar Donetsk",
    "Spartak Moscow", "Sparta Prague", "Stoke City", "Stuttgart", "Swansea", "Trabzonspor",
    "Universitario", "Universitario de Deportes", "Valencia", "Vasco da Gama",
    "Velez", "Villarreal", "Watford", "Wigan", "Wrexham", "Young Boys", "Zenit",
)

NATIONAL_TEAM_HEBREW_NAMES = [
    # 48 נבחרות מונדיאל 2026, ועוד איטליה וישראל.
    "מקסיקו", "דרום אפריקה", "דרום קוריאה", "צ'כיה",
    "קנדה", "קטאר", "שווייץ", "בוסניה",
    "ברזיל", "מרוקו", "האיטי", "סקוטלנד",
    "ארצות הברית", "אוסטרליה", "טורקיה", "פרגוואי",
    "גרמניה", "קוראסאו", "חוף השנהב", "אקוודור",
    "הולנד", "יפן", "שבדיה", "תוניסיה",
    "בלגיה", "מצרים", "ניו זילנד", "איראן",
    "ספרד", "כף ורדה", "ערב הסעודית", "אורוגוואי",
    "צרפת", "סנגל", "עיראק", "נורבגיה",
    "ארגנטינה", "אלג'יריה", "אוסטריה", "ירדן",
    "פורטוגל", "קולומביה", "אוזבקיסטן", "קונגו",
    "אנגליה", "קרואטיה", "גאנה", "פנמה",
    "איטליה", "ישראל",
]

for country in NATIONAL_TEAM_HEBREW_NAMES:
    TEAM_CATALOG[f"national:{country}"] = {"name": country, "tier": "national", "aliases": [country]}

CENTRAL_PLAYER_AFFILIATIONS: tuple[dict[str, Any], ...] = (
    {"team_key": "real madrid", "aliases": ("Kylian Mbappe", "Kylian Mbappé", "Mbappe", "Mbappé", "קיליאן אמבפה", "אמבפה")},
    {"team_key": "real madrid", "aliases": ("Vinicius Junior", "Vinícius Júnior", "Vinicius Jr", "Vini Jr", "ויניסיוס", "ויניסיוס ג'וניור")},
    {"team_key": "real madrid", "aliases": ("Jude Bellingham", "Bellingham", "ג'וד בלינגהאם", "בלינגהאם")},
    {"team_key": "real madrid", "aliases": ("Rodrygo", "Rodrygo Goes", "רודריגו")},
    {"team_key": "real madrid", "aliases": ("Trent Alexander-Arnold", "Alexander-Arnold", "TAA", "טרנט אלכסנדר-ארנולד", "אלכסנדר-ארנולד")},
    {"team_key": "barcelona", "aliases": ("Lamine Yamal", "Yamal", "לאמין ימאל", "ימאל")},
    {"team_key": "barcelona", "aliases": ("Raphinha", "Raphael Dias Belloli", "ראפיניה")},
    {"team_key": "manchester city", "aliases": ("Erling Haaland", "Haaland", "ארלינג הולאנד", "הולאנד")},
    {"team_key": "manchester city", "aliases": ("Rodri", "Rodrigo Hernandez", "Rodrigo Hernández", "רודרי")},
    {"team_key": "manchester city", "aliases": ("Phil Foden", "Foden", "פיל פודן", "פודן")},
    {"team_key": "manchester city", "aliases": ("Bernardo Silva", "ברנרדו סילבה")},
    {"team_key": "liverpool", "aliases": ("Mohamed Salah", "Mo Salah", "Salah", "מוחמד סלאח", "סלאח")},
    {"team_key": "liverpool", "aliases": ("Virgil van Dijk", "Van Dijk", "וירג'יל ואן דייק", "ואן דייק")},
    {"team_key": "liverpool", "aliases": ("Florian Wirtz", "Wirtz", "פלוריאן וירץ", "וירץ")},
    {"team_key": "arsenal", "aliases": ("Bukayo Saka", "Saka", "בוקאיו סאקה", "סאקה")},
    {"team_key": "arsenal", "aliases": ("Martin Odegaard", "Martin Ødegaard", "Odegaard", "Ødegaard", "מרטין אודגור", "אודגור")},
    {"team_key": "chelsea", "aliases": ("Cole Palmer", "Palmer", "קול פאלמר", "פאלמר")},
    {"team_key": "manchester united", "aliases": ("Bruno Fernandes", "ברונו פרננדש")},
    {"team_key": "bayern munich", "aliases": ("Harry Kane", "Kane", "הארי קיין", "קיין")},
    {"team_key": "bayern munich", "aliases": ("Jamal Musiala", "Musiala", "ג'מאל מוסיאלה", "מוסיאלה")},
    {"team_key": "psg", "aliases": ("Ousmane Dembele", "Ousmane Dembélé", "Dembele", "Dembélé", "אוסמן דמבלה", "דמבלה")},
    {"team_key": "psg", "aliases": ("Khvicha Kvaratskhelia", "Kvaratskhelia", "קווארצחליה", "חביצה קווארצחליה")},
    {"team_key": "psg", "aliases": ("Vitinha", "ויטיניה")},
    {"team_key": "inter", "aliases": ("Lautaro Martinez", "Lautaro Martínez", "Lautaro", "לאוטרו מרטינס", "לאוטרו")},
    {"team_key": "ac milan", "aliases": ("Rafael Leao", "Rafael Leão", "Leao", "Leão", "רפאל לאאו", "לאאו")},
    {"team_key": "atletico madrid", "aliases": ("Julian Alvarez", "Julián Álvarez", "Alvarez", "Álvarez", "חוליאן אלבארס", "אלבארס")},
    {"team_key": "newcastle", "aliases": ("Alexander Isak", "Isak", "אלכסנדר איסאק", "איסאק")},
    {"team_key": "inter miami", "aliases": ("Lionel Messi", "Messi", "לאו מסי", "ליאו מסי", "מסי")},
    {"team_key": "juventus", "aliases": ("Dusan Vlahovic", "Dušan Vlahović", "Vlahovic", "Vlahović", "דושאן ולאחוביץ'", "ולאחוביץ'")},
    {"team_key": "juventus", "aliases": ("Kenan Yildiz", "Kenan Yıldız", "Yildiz", "Yıldız", "קנאן ילדיז", "ילדיז")},
    {"team_key": "napoli", "aliases": ("Kevin De Bruyne", "De Bruyne", "דה בריינה", "קווין דה בריינה")},
    {"team_key": "napoli", "aliases": ("Scott McTominay", "McTominay", "סקוט מקטומיניי", "מקטומיניי")},
    {"team_key": "roma", "aliases": ("Paulo Dybala", "Dybala", "פאולו דיבאלה", "דיבאלה")},
    {"team_key": "atalanta", "aliases": ("Ademola Lookman", "Lookman", "אדמולה לוקמן", "לוקמן")},
)


def normalize_team_key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def resolve_team_catalog_key(name: str) -> str | None:
    wanted = normalize_team_key(name)
    for key, item in all_team_catalog_items().items():
        names = [str(item.get("name", "")), *[str(alias) for alias in item.get("aliases", [])]]
        if any(normalize_team_key(candidate) == wanted for candidate in names):
            return key
    return None


def is_reasonable_hebrew_team_name(name: str) -> bool:
    cleaned = re.sub(r"\s+", " ", (name or "").strip())
    return bool(2 <= len(cleaned) <= 60 and re.search(r"[\u0590-\u05ff]", cleaned))


def ensure_custom_team_key(name: str, tier: str) -> str | None:
    existing = resolve_team_catalog_key(name)
    if existing:
        return existing
    if tier not in TEAM_TIER_LABELS or not is_reasonable_hebrew_team_name(name):
        return None
    key = "custom:" + hashlib.sha1(normalize_team_key(name).encode("utf-8", errors="ignore")).hexdigest()[:16]
    overrides = managed_team_overrides()
    custom = load_control_state().get("custom_team_catalog", {})
    if not isinstance(custom, dict):
        custom = {}
    custom[key] = {"name": re.sub(r"\s+", " ", name.strip()), "tier": tier, "aliases": [re.sub(r"\s+", " ", name.strip())]}
    overrides[key] = tier
    save_control_state(custom_team_catalog=custom, team_tier_overrides=overrides)
    return key


def all_team_catalog_items(state: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    state = state or load_control_state()
    catalog = dict(TEAM_CATALOG)
    custom = state.get("custom_team_catalog", {})
    if isinstance(custom, dict):
        for key, value in custom.items():
            if isinstance(value, dict) and str(value.get("name", "")).strip():
                catalog[str(key)] = value
    return catalog


def managed_team_overrides(state: dict[str, Any] | None = None) -> dict[str, str]:
    raw = (state or load_control_state()).get("team_tier_overrides", {})
    return raw if isinstance(raw, dict) else {}


def effective_team_tier(key: str, state: dict[str, Any] | None = None) -> str:
    catalog = all_team_catalog_items(state)
    value = str(managed_team_overrides(state).get(key, catalog.get(key, {}).get("tier", "")))
    return value if value in TEAM_TIER_LABELS else ""


def team_catalog_keys_for_tier(tier: str, state: dict[str, Any] | None = None) -> list[str]:
    state = state or load_control_state()
    catalog = all_team_catalog_items(state)
    return sorted([key for key in catalog if effective_team_tier(key, state) == tier], key=lambda key: str(catalog[key].get("name", key)))


def team_tier_list_text(tier: str) -> str:
    keys = team_catalog_keys_for_tier(tier)
    catalog = all_team_catalog_items()
    label = TEAM_TIER_LABELS.get(tier, "רשימת קבוצות")
    lines = [f"🏟️ {label}", "", f"סה״כ: {len(keys)}"]
    for index, key in enumerate(keys, 1):
        item = catalog[key]
        aliases = [str(alias) for alias in item.get("aliases", [])[:2] if str(alias) != str(item.get("name", ""))]
        suffix = f" ({', '.join(aliases)})" if aliases else ""
        lines.append(f"{index}. {item.get('name', key)}{suffix}")
    return "\n".join(lines)


def teams_help_text(_mode: str = "") -> str:
    return (
        "🏟️ ניהול קבוצות\n\n"
        "הכול עובד בכפתורים:\n"
        "1. בוחרים הוסף, הסר או העבר.\n"
        "2. אם צריך, בוחרים דרג יעד.\n"
        "3. מקלידים רק את שם הקבוצה או הנבחרת.\n\n"
        "אפשר להקליד שם מדויק בעברית או באנגלית. אם השם בעברית ולא קיים במאגר, הוא יתווסף כקבוצה/נבחרת מותאמת אישית."
    )


def apply_team_management_change(action: str, name: str, tier: str = "") -> tuple[str, str]:
    key = resolve_team_catalog_key(name)
    if not key and action in {"add", "move"}:
        key = ensure_custom_team_key(name, tier)
    if not key:
        return f"⚠️ השם לא נמצא במאגר\n\nשם שנשלח: {name}\nאפשר לכתוב שם מדויק בעברית כדי להוסיף אותו כמותאם אישית.", ""
    catalog = all_team_catalog_items()
    team_name = str(catalog.get(key, {}).get("name", key))
    overrides = managed_team_overrides()
    if action == "remove":
        old_tier = effective_team_tier(key)
        overrides[key] = "removed"
        save_control_state(team_tier_overrides=overrides, pending_team_action="", pending_team_tier="")
        return f"✅ הקבוצה הוסרה בהצלחה\n\nשם: {team_name}\nמיקום קודם: {TEAM_TIER_LABELS.get(old_tier, 'לא ידוע')}", old_tier
    if tier not in TEAM_TIER_LABELS:
        return "⚠️ דרג לא מוכר", ""
    overrides[key] = tier
    save_control_state(team_tier_overrides=overrides, pending_team_action="", pending_team_tier="")
    if action == "add":
        title = "✅ הקבוצה נוספה בהצלחה"
    else:
        title = "✅ הקבוצה הועברה בהצלחה"
    return f"{title}\n\nשם: {team_name}\nמיקום: {TEAM_TIER_LABELS[tier]}", tier


def handle_team_management_command(text: str) -> tuple[str, str] | None:
    state = load_control_state()
    pending_action = str(state.get("pending_team_action", "") or "")
    pending_tier = str(state.get("pending_team_tier", "") or "")
    cleaned = text.strip()
    if pending_action in {"add", "move", "remove"}:
        return apply_team_management_change(pending_action, cleaned, pending_tier)
    if not cleaned.startswith(("הוסף קבוצה", "הסר קבוצה", "העבר קבוצה")):
        return None
    parts = [part.strip() for part in cleaned.split("|")]
    action = parts[0]
    if action.startswith("הסר"):
        if len(parts) < 2:
            return teams_help_text("remove"), ""
        return apply_team_management_change("remove", parts[1])
    if len(parts) < 3:
        return teams_help_text("add"), ""
    tier = TEAM_TIER_ALIASES.get(normalize_team_key(parts[2]))
    if not tier:
        return "⚠️ דרג לא מוכר\n\nאפשר לכתוב: דרג א, דרג ב, דרג ג, נבחרות", ""
    return apply_team_management_change("add" if action.startswith("הוסף") else "move", parts[1], tier)


def managed_team_patterns_for_tier(tier: str) -> tuple[str, ...]:
    aliases: list[str] = []
    state = load_control_state()
    catalog = all_team_catalog_items(state)
    for key in team_catalog_keys_for_tier(tier, state):
        item = catalog[key]
        aliases.extend(str(alias) for alias in item.get("aliases", []) if str(alias).strip())
        name = str(item.get("name", "")).strip()
        if name:
            aliases.append(name)
    if not aliases:
        return ()
    escaped = sorted({re.escape(alias) for alias in aliases}, key=len, reverse=True)
    return (r"(?:%s)" % "|".join(escaped),)


def matches_managed_team_tier(tier: str, text: str) -> bool:
    return _matches_any(managed_team_patterns_for_tier(tier), text)


def _team_alias_boundary_pattern(alias: str) -> str:
    raw = str(alias or "").strip()
    if not raw:
        return r"$^"
    parts = [part for part in re.split(r"[\s\-]+", raw) if part]
    escaped = r"[\s\-]+".join(re.escape(part) for part in parts) if parts else re.escape(raw)
    return rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"


def destination_text_matches_tracked_team(text: str) -> bool:
    source = str(text or "").strip()
    if not source:
        return False
    return any(matches_managed_team_tier(tier, source) for tier in ("tier1", "tier2", "tier3", "national"))


def known_untracked_destination_aliases() -> tuple[str, ...]:
    tracked_names: set[str] = set()
    for item in all_team_catalog_items().values():
        tracked_names.add(normalize_team_key(str(item.get("name", ""))))
        tracked_names.update(normalize_team_key(str(alias)) for alias in item.get("aliases", []) if str(alias).strip())
    aliases = [
        alias for alias in KNOWN_UNTRACKED_DESTINATION_CLUB_ALIASES
        if normalize_team_key(alias) and normalize_team_key(alias) not in tracked_names
    ]
    return tuple(sorted(set(aliases), key=len, reverse=True))


def explicit_untracked_destination_club(post: Post) -> str:
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    if not cleaned:
        return ""
    if not (
        _matches_any(TRANSFER_OR_FUTURE_PATTERNS, cleaned)
        or _matches_any(STRONG_PLAYER_MOVE_PATTERNS, cleaned)
        or _matches_any(CLEAR_PLAYER_DEPARTURE_PATTERNS, cleaned)
    ):
        return ""
    for alias in known_untracked_destination_aliases():
        alias_pattern = _team_alias_boundary_pattern(alias)
        destination_patterns = (
            rf"\b(?:to|for|with|at)\s+{alias_pattern}\b",
            rf"\b(?:join|joins|joining|joined|sign|signs|signed|signing|move|moves|moved|moving|transfer|transfers|transferred|loan|loaned|lands|landed)\s+(?:to|for|with|at)?\s*{alias_pattern}\b",
            rf"\b(?:set to join|set to sign|will join|will sign|agreed to join|close to joining|close to signing)\s+{alias_pattern}\b",
            rf"\b(?:accepted|accepts|accept|agreed|agrees|reached agreement|has agreement|have agreement)\s+(?:personal terms\s+)?(?:with\s+)?{alias_pattern}\b",
            rf"\b(?:accepted|accepts|accept|received|gets|got)\s+{alias_pattern}\s+(?:proposal|offer|bid|approach)\b",
            rf"\b(?:proposal|offer|bid|approach)\s+(?:from|by)\s+{alias_pattern}\b",
            rf"\b(?:agreement|deal|verbal agreement|full agreement|contract agreement)\s+(?:with|at)\s+{alias_pattern}\b",
            rf"{alias_pattern}\s+(?:have|has)?\s*(?:asked|requested|opened talks|approached|made an offer|submitted an offer|want|wants|seek|seeks)\b",
            rf"{alias_pattern}\s+(?:proposal|offer|bid|approach)\b",
        )
        if any(re.search(pattern, cleaned, re.IGNORECASE | re.UNICODE) for pattern in destination_patterns):
            if not destination_text_matches_tracked_team(alias):
                return alias
    generic_destination = re.search(
        r"\b(?:to|join(?:s|ing|ed)?|sign(?:s|ing|ed)?\s+(?:for|with)?|move(?:s|d|ing)?\s+to|loan(?:ed)?\s+to|lands?\s+at)\s+"
        r"(?P<dest>(?:[A-Z][A-Za-zÀ-ÿ'’.-]{2,}|FC|CF|SC|AC)(?:\s+(?:[A-Z][A-Za-zÀ-ÿ'’.-]{2,}|FC|CF|SC|AC|United|City|Town|County|Calcio|Deportes|Sporting|Club)){0,4})",
        cleaned,
        re.IGNORECASE | re.UNICODE,
    )
    if generic_destination:
        dest = re.sub(r"\s+", " ", generic_destination.group("dest").strip(" .,:;()[]"))
        clubish = re.search(r"\b(?:FC|CF|SC|AC|United|City|Town|County|Calcio|Deportes|Sporting|Club)\b", dest, re.IGNORECASE)
        if clubish and not destination_text_matches_tracked_team(dest):
            return dest
    return ""


def is_explicit_untracked_destination_club(post: Post) -> bool:
    return bool(explicit_untracked_destination_club(post))


def central_player_alias_matches(alias: str, text: str) -> bool:
    alias = str(alias or "").strip()
    if not alias:
        return False
    if re.search(r"[A-Za-z0-9]", alias):
        pattern = r"(?<![A-Za-z0-9_])" + re.escape(alias) + r"(?![A-Za-z0-9_])"
    elif re.search(r"[\u0590-\u05ff]", alias):
        pattern = r"(?<![\u0590-\u05ff])" + re.escape(alias) + r"(?![\u0590-\u05ff])"
    else:
        pattern = re.escape(alias)
    return bool(re.search(pattern, text or "", re.IGNORECASE))


def central_player_affiliation_tiers(text: str) -> set[str]:
    tiers: set[str] = set()
    source = html.unescape(text or "")
    if not source:
        return tiers
    for item in CENTRAL_PLAYER_AFFILIATIONS:
        team_key = str(item.get("team_key", "")).strip()
        if team_key not in all_team_catalog_items():
            continue
        aliases = item.get("aliases", ())
        if not isinstance(aliases, (list, tuple, set)):
            aliases = (aliases,)
        if any(central_player_alias_matches(str(alias), source) for alias in aliases):
            tier = effective_team_tier(team_key)
            if tier:
                tiers.add(tier)
    return tiers


def has_central_player_affiliation(text: str, tiers: set[str] | None = None) -> bool:
    matched_tiers = central_player_affiliation_tiers(text)
    return bool(matched_tiers if tiers is None else matched_tiers.intersection(tiers))


def fetch_control_posts(username: str) -> tuple[str, list[Post], Exception | None]:
    try:
        return username, fetch_posts(username), None
    except Exception as exc:
        logging.warning("⚠️ בדיקת RSS ידנית נכשלה עבור @%s: %s", username, exc)
        return username, [], exc


def fetch_control_posts_for_accounts(accounts: list[str]) -> dict[str, tuple[list[Post], Exception | None]]:
    results: dict[str, tuple[list[Post], Exception | None]] = {username: ([], None) for username in accounts}
    if not accounts:
        return results
    workers = min(current_max_parallel_account_checks(), max(1, len(accounts)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(fetch_control_posts, username): username for username in accounts}
        for future in as_completed(future_map):
            username, posts, error = future.result()
            results[username] = (posts, error)
    return results


def live_recent_snapshot_from_rss() -> dict[str, int]:
    snapshot: dict[str, int] = {}
    accounts = all_control_test_accounts()
    for username, (posts, error) in fetch_control_posts_for_accounts(accounts).items():
        snapshot[username] = 0 if error else len(recent_24h_posts(posts))
    daily_stat_replace_table("fetched_recent_24h_snapshot", snapshot)
    return snapshot


def account_latest_menu_reply_markup() -> dict[str, Any]:
    keyboard: list[list[dict[str, str]]] = []
    accounts = all_control_test_accounts()
    for username in accounts:
        label = _hebrew_account_label(username)
        keyboard.append([{
            "text": label,
            "callback_data": f"football_test_latest_account:{username}",
        }])
    keyboard.append([{"text": "ℹ️ הסבר בדיקת כתב", "callback_data": "football_category_help:account_latest"}])
    keyboard.append([{"text": "⬅️ חזרה לראשי", "callback_data": "football_quick_main"}])
    return stable_reply_markup(keyboard)


def send_control_menu(text: str, reply_markup: dict[str, Any], message_id: Any = None) -> None:
    if not CONTROL_CHAT_ID:
        return
    payload = {
        "chat_id": CONTROL_CHAT_ID,
        "text": rtl(text),
        "reply_markup": reply_markup,
        "disable_web_page_preview": True,
    }
    if message_id:
        try:
            telegram_api("editMessageText", {**payload, "message_id": int(message_id)}, max_attempts=1, timeout=TELEGRAM_BUTTON_FAST_TIMEOUT_SECONDS)
            save_control_state(quick_control_message_id=message_id)
            return
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                return
            logging.warning("⚠️ תפריט שליטה: עריכת ההודעה נכשלה ולא נשלחה הודעה חדשה כדי לא ליצור כפילות: %s", exc)
            return
    response = telegram_api("sendMessage", payload, max_attempts=1, timeout=TELEGRAM_BUTTON_FAST_TIMEOUT_SECONDS)
    new_message_id = response.get("result", {}).get("message_id") if isinstance(response, dict) else None
    if new_message_id:
        save_control_state(quick_control_message_id=new_message_id)

def send_control_panel(paused: bool, action_done: str = "", force_new: bool = False) -> None:
    if not CONTROL_CHAT_ID:
        return
    if not CONTROL_PANEL_MESSAGES_ENABLED:
        logging.debug("לוח שליטה: הודעת לוח לא נשלחה לערוץ השקט כי CONTROL_PANEL_MESSAGES_ENABLED כבוי.")
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
            telegram_api("editMessageText", {**payload, "message_id": int(message_id)}, max_attempts=1, timeout=TELEGRAM_BUTTON_FAST_TIMEOUT_SECONDS)
            return
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                return
            logging.warning("⚠️ לוח שליטה: עדכון ההודעה נכשל, שולח לוח חדש: %s", exc)
    response = telegram_api("sendMessage", payload, max_attempts=1, timeout=TELEGRAM_BUTTON_FAST_TIMEOUT_SECONDS)
    new_message_id = response.get("result", {}).get("message_id")
    if new_message_id:
        save_control_state(paused, control_message_id=new_message_id)


def send_quick_control_panel(action_done: str = "", force_new: bool = False) -> None:
    if not CONTROL_CHAT_ID or not CONTROL_PANEL_MESSAGES_ENABLED:
        return
    text = action_done or "כלים מהירים לבוט הכדורגל."
    state = load_control_state()
    message_id = state.get("quick_control_message_id")
    payload = {
        "chat_id": CONTROL_CHAT_ID,
        "text": text,
        "reply_markup": quick_control_reply_markup(),
    }
    if message_id and not force_new:
        try:
            telegram_api("editMessageText", {**payload, "message_id": int(message_id)}, max_attempts=1, timeout=TELEGRAM_BUTTON_FAST_TIMEOUT_SECONDS)
            return
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                return
            logging.warning("⚠️ לוח כלים מהירים: עדכון ההודעה נכשל, שולח חדש: %s", exc)
    response = telegram_api("sendMessage", payload, max_attempts=1, timeout=TELEGRAM_BUTTON_FAST_TIMEOUT_SECONDS)
    new_message_id = response.get("result", {}).get("message_id")
    if new_message_id:
        save_control_state(quick_control_message_id=new_message_id)


def answer_control_callback(callback_id: str, text: str = "") -> None:
    """Acknowledge Telegram button clicks without delaying menu edits.

    Telegram shows a loading spinner on inline buttons until answerCallbackQuery is
    received. Network retries here can make the whole menu feel slow, so this is
    intentionally sent in a tiny background thread with one short attempt.
    The actual menu edit continues immediately.
    """
    if not callback_id:
        return

    def _send_ack() -> None:
        try:
            telegram_api(
                "answerCallbackQuery",
                {"callback_query_id": callback_id, "text": text, "show_alert": False},
                max_attempts=1,
                timeout=TELEGRAM_BUTTON_FAST_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logging.debug("Telegram callback ack failed quickly: %s", exc)

    Thread(target=_send_ack, daemon=True).start()


def _control_list_text(title: str, items: list[dict[str, Any]], empty: str) -> str:
    lines = [title, ""]
    if not items:
        lines.append(empty)
        return "\n".join(lines)
    for index, item in enumerate(items[-5:], 1):
        source = _hebrew_account_label(str(item.get("source", "") or ""))
        reason = hebrew_block_reason(str(item.get("reason", "") or "סיבה לא ידועה"))
        preview = str(item.get("preview", "") or "")
        link = str(item.get("link", "") or "")
        lines.append(f"{index}. כתב: {source}")
        lines.append(f"   סיבה: {reason}")
        if preview:
            lines.append(f"   תקציר: {preview[:180]}")
        if link:
            lines.append(f"   קישור לפוסט: {link}")
        if index != min(5, len(items[-5:])):
            lines.append("")
    return "\n".join(lines)


def send_control_text(text: str, message_id: Any = None, reply_markup: dict[str, Any] | None = None) -> None:
    if not CONTROL_CHAT_ID:
        return
    formatted = rtl(text)
    payload = {
        "chat_id": CONTROL_CHAT_ID,
        "text": trim(formatted, 3900),
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    if message_id:
        try:
            telegram_api("editMessageText", {**payload, "message_id": int(message_id)}, max_attempts=1, timeout=TELEGRAM_BUTTON_FAST_TIMEOUT_SECONDS)
            return
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                return
            logging.warning("⚠️ טקסט שליטה: עריכת ההודעה נכשלה ולא נשלחה הודעה חדשה כדי לא ליצור כפילות: %s", exc)
            return
    telegram_api("sendMessage", payload, max_attempts=1, timeout=TELEGRAM_BUTTON_FAST_TIMEOUT_SECONDS)


def send_control_html(text: str) -> None:
    if not CONTROL_CHAT_ID:
        return
    formatted = rtl(text)
    telegram_api(
        "sendMessage",
        {
            "chat_id": CONTROL_CHAT_ID,
            "text": trim(formatted, 4096),
            "disable_web_page_preview": True,
            "parse_mode": "HTML",
        },
        max_attempts=1,
    )


def run_latest_account_control_test(username: str) -> None:
    if not CONTROL_CHAT_ID:
        return
    label = _hebrew_account_label(username)
    try:
        posts = fetch_posts(username)
    except Exception as exc:
        send_control_text(f"🧪 בדיקת {label} נכשלה בשליפת RSS:\n{short_error(exc, 500)}")
        return
    if not posts:
        send_control_text(f"🧪 בדיקת {label}: לא נמצאו פוסטים במקורות ה-RSS כרגע.")
        return
    post = posts[0]
    # בדיקת כפתור ידנית: שולחים את הפוסט האחרון של הכתב לערוץ השקט
    # גם אם הסינון הרגיל היה חוסם אותו. כפילות וסיבות חסימה אינן נבדקות כאן.
    try:
        translated, quoted_translated, quoted_author_translated = translate_post_for_send(post)
        message = build_message(post, translated, quoted_translated, quoted_author_translated, include_video_link=False)
        post_dt = datetime.fromtimestamp(post.published_ts, ZoneInfo(SHABBAT_TIMEZONE)) if post.published_ts else None
        post_when = post_dt.strftime("%d/%m/%Y %H:%M:%S") if post_dt else "לא ידוע"
        header = html.escape(rtl(f"🧪 בדיקת {label} אחרון - נשלח בכוח לערוץ השקט"))
        source = html.escape(rtl(f"תאריך הפוסט לפי שעון ישראל: {post_when} | מקור RSS: {post.source_name} | קישור: {post.link}"))
        send_control_html(f"<b>{header}</b>\n{source}\n\n{message}")
        logging.info("🧪 בדיקת כתב: הפוסט האחרון של @%s נשלח בכוח לערוץ השקט ללא סינון וללא בדיקת כפילות. קישור: %s", username, post.link)
    except Exception as exc:
        send_control_text(
            f"🧪 בדיקת {label}: הפוסט נמצא, אבל התרגום/השליחה לערוץ השקט נכשלו.\n"
            f"סיבה: {short_error(exc, 600)}\n"
            f"קישור: {post.link}"
        )


def run_latest_fabrizio_control_test() -> None:
    run_latest_account_control_test("FabrizioRomano")


def check_all_accounts_now_text() -> str:
    lines = [
        "🔄 בדיקת כל 14 הכתבים עכשיו",
        "",
        "הבדיקה הזו עושה RSS בלבד. אין שימוש ב-Gemini ואין שליחת פוסטים.",
        "המספרים כאן הם רק פוסטים שפורסמו ב-24 השעות האחרונות לפי זמן הפרסום של הפוסט.",
        "חשוב: זה אומר שהפוסט נמצא ב-RSS. הוא עדיין יכול לא להישלח בגלל שכבר נשלח/סומן, כפילות, גיל, או סינון תוכן.",
        "",
    ]
    accounts = all_control_test_accounts()
    total_recent_posts = 0
    ok_count = 0
    recent_snapshot: dict[str, int] = {}
    fetched_by_account = fetch_control_posts_for_accounts(accounts)
    for username in accounts:
        label = _hebrew_account_label(username)
        posts, error = fetched_by_account.get(username, ([], None))
        if error:
            recent_snapshot[username] = 0
            lines.append(f"❌ {label}: תקלה בשליפה - {short_error(error, 160)}")
            continue
        recent = recent_24h_posts(posts)
        recent_snapshot[username] = len(recent)
        total_recent_posts += len(recent)
        ok_count += 1
        if recent:
            latest_dt = datetime.fromtimestamp(recent[0].published_ts, ZoneInfo(SHABBAT_TIMEZONE)).strftime("%H:%M %d/%m/%Y")
            latest = f"{latest_dt} | {recent[0].link}"
        elif posts:
            source = posts[0].source_name or "לא ידוע"
            age_hours = max(0.0, (time.time() - float(posts[0].published_ts or 0.0)) / 3600) if posts[0].published_ts else 0.0
            latest = f"מקור RSS עובד אבל ישן/תקוע: אחרון לפני {age_hours:.1f} שעות | מקור: {source}"
        else:
            latest = "אין פוסטים כרגע"
        lines.append(f"✅ {label}: {len(recent)} פוסטים ביממה האחרונה | אחרון: {latest}")
    daily_stat_replace_table("fetched_recent_24h_snapshot", recent_snapshot)
    lines.extend(["", f"סיכום: {ok_count}/{len(accounts)} כתבים פעילים נבדקו. נמצאו יחד {total_recent_posts} פוסטים מהיממה האחרונה."])
    return "\n".join(lines)


def rss_status_text() -> str:
    lines = [
        "📡 בדיקת RSS לכל 14 הכתבים",
        "",
        "הבדיקה הזו בודקת מקורות RSS בלבד ולא משתמשת ב-Gemini.",
        "היא מציגה גם כתבים שכרגע כבויים, כדי שתוכל לראות אם הבעיה היא בכתב או במקור RSS.",
        "",
    ]
    accounts = all_control_test_accounts()
    ok_count = 0
    recent_total = 0
    fetched_by_account = fetch_control_posts_for_accounts(accounts)
    for username in accounts:
        label = _hebrew_account_label(username)
        posts, error = fetched_by_account.get(username, ([], None))
        if error:
            lines.append(f"❌ {label}: תקלה במקורות RSS - {short_error(error, 140)}")
            continue
        recent = recent_24h_posts(posts)
        recent_total += len(recent)
        if posts:
            ok_count += 1
            source = posts[0].source_name or "לא ידוע"
            if recent:
                latest_dt = datetime.fromtimestamp(recent[0].published_ts, ZoneInfo(SHABBAT_TIMEZONE)).strftime("%H:%M %d/%m/%Y")
                lines.append(f"✅ {label}: RSS תקין | {len(recent)} פוסטים ביממה | מקור אחרון: {source} | אחרון: {latest_dt}")
            else:
                age_hours = max(0.0, (time.time() - float(posts[0].published_ts or 0.0)) / 3600) if posts[0].published_ts else 0.0
                lines.append(f"⚠️ {label}: מקור RSS עובד אבל ישן/תקוע | אחרון לפני {age_hours:.1f} שעות | מקור: {source}")
        else:
            lines.append(f"⚠️ {label}: RSS עובד/נבדק, אבל לא החזיר פוסטים כרגע")
    lines.append("")
    lines.append(f"תוצאה: {ok_count}/{len(accounts)} כתבים החזירו פוסטים כלשהם. פוסטים מהיממה האחרונה: {recent_total}.")
    return "\n".join(lines)


def gemini_requests_paused_until_refill(state: dict[str, Any] | None = None) -> bool:
    state = state or load_control_state()
    return bool(state.get(GEMINI_QUOTA_GUARD_STATE_KEY, False))


def set_gemini_requests_pause(paused: bool, reason: str = "") -> None:
    updates: dict[str, Any] = {GEMINI_QUOTA_GUARD_STATE_KEY: bool(paused)}
    if paused:
        updates["gemini_requests_paused_reason"] = reason or "מכסה נגמרה / הגנה ידנית"
        updates["gemini_requests_paused_at"] = time.time()
    else:
        updates["gemini_requests_paused_reason"] = ""
        updates["gemini_requests_paused_at"] = 0.0
    save_control_state(**updates)


def gemini_guard_button_label() -> str:
    if gemini_requests_paused_until_refill():
        return "♻️ שחרור Gemini אחרי שהתמלא"
    return "⛔ עצור בקשות Gemini עד האיפוס"


def gemini_quota_guard_text(paused: bool) -> str:
    if paused:
        return (
            "⛔ הגנת Gemini הופעלה\n\n"
            "מעכשיו הבוט לא ישלח שום בקשה אמיתית ל-Gemini, גם אם מגיע פוסט שעבר סינון.\n"
            "זה מונע שריפת בקשות כשאין מכסה, כי גם ניסיון כושל נחשב בקשה.\n\n"
            "כשהמכסה מתמלאת שוב או אחרי שהוספת מפתח תקין ב-Railway, לחץ על:\n"
            "♻️ שחרור Gemini אחרי שהתמלא"
        )
    return (
        "♻️ Gemini שוחרר אחרי שהתמלא\n\n"
        "נוקו קירורים מקומיים והבוט רשאי שוב לשלוח בקשות אמיתיות ל-Gemini.\n"
        "אם המכסה עדיין לא התמלאה, הכשל הבא יפעיל שוב הגנה ויעצור בקשות."
    )


def gemini_toggle_quota_guard() -> str:
    now_paused = gemini_requests_paused_until_refill()
    if now_paused:
        set_gemini_requests_pause(False)
        return gemini_clear_local_cooldowns(clear_pause=False) + "\n\n" + gemini_quota_guard_text(False)
    set_gemini_requests_pause(True, "עצירה ידנית מהכפתור")
    global GEMINI_DISABLED_UNTIL, GEMINI_COOLDOWN_IS_QUOTA, GEMINI_FAILURE_LOGGED
    GEMINI_DISABLED_UNTIL = 10 ** 12
    GEMINI_COOLDOWN_IS_QUOTA = True
    GEMINI_FAILURE_LOGGED = True
    return gemini_quota_guard_text(True)


def gemini_clear_local_cooldowns(clear_pause: bool = True) -> str:
    global GEMINI_DISABLED_UNTIL, GEMINI_COOLDOWN_IS_QUOTA, GEMINI_FAILURE_LOGGED
    with GEMINI_KEY_LOCK:
        count = len(GEMINI_KEY_COOLDOWNS)
        GEMINI_KEY_COOLDOWNS.clear()
    GEMINI_DISABLED_UNTIL = 0.0
    GEMINI_COOLDOWN_IS_QUOTA = False
    GEMINI_FAILURE_LOGGED = False
    if clear_pause:
        set_gemini_requests_pause(False)
    return f"♻️ שוחרר קירור Gemini מקומי ל-{count} מפתחות."


def gemini_status_text() -> str:
    refresh_gemini_api_keys_from_env()
    now = time.time()
    with GEMINI_KEY_LOCK:
        loaded = len(GEMINI_API_KEYS)
        cooled = sum(1 for key in GEMINI_API_KEYS if GEMINI_KEY_COOLDOWNS.get(key, 0.0) > now)
        longest_wait = max([GEMINI_KEY_COOLDOWNS.get(key, 0.0) - now for key in GEMINI_API_KEYS if GEMINI_KEY_COOLDOWNS.get(key, 0.0) > now] or [0])
    available_count = max(0, loaded - cooled)
    global_wait = max(0, int(GEMINI_DISABLED_UNTIL - now)) if GEMINI_DISABLED_UNTIL and GEMINI_DISABLED_UNTIL < 10**11 else 0
    paused_until_refill = gemini_requests_paused_until_refill()
    bucket = _daily_stats_bucket()
    failures_today = sum(int(v or 0) for v in (bucket.get("gemini_failures", {}) or {}).values())
    status = "עצור עד שחרור ידני" if paused_until_refill else ("תקין מקומית" if loaded and (available_count > 0) and not global_wait else ("בקירור מקומי" if loaded else "אין מפתחות טעונים"))
    return (
        "🤖 בדיקת Gemini מקומית\n\n"
        f"מצב: {status}\n"
        f"מפתחות טעונים: {loaded}\n"
        f"מפתחות פנויים מקומית: {available_count}\n"
        f"מפתחות בקירור מקומי: {cooled}\n"
        f"הגנת מכסה עד שחרור: {'פעילה' if paused_until_refill else 'כבויה'}\n"
        f"כשלי Gemini שנרשמו היום: {failures_today}\n"
        f"מודל תרגום: {GEMINI_MODEL}\n"
        + (f"\nקירור כללי נשאר: {global_wait} שניות" if global_wait else "")
        + (f"\nהמתנה ארוכה ביותר למפתח: {int(longest_wait)} שניות" if longest_wait else "")
        + "\n\nהבדיקה הזו לא שולחת בקשה ל-Gemini ולא מבזבזת קרדיט.\n"
        "אם נגמרה מכסה: הפעל עצירת בקשות Gemini. כשהמכסה מתמלאת או כשמוסיפים מפתח חדש, לחץ שחרור Gemini אחרי שהתמלא."
    )


def active_accounts_status_text() -> str:
    state = load_control_state()
    active = active_x_accounts()
    active_set = set(active)
    disabled_base = set(disabled_base_accounts_from_state(state))
    enabled_optional = set(enabled_optional_accounts_from_state(state))
    enabled_at = account_enabled_at_from_state(state)

    def since_text(username: str) -> str:
        timestamp = enabled_at.get(username, 0.0)
        if not timestamp:
            return ""
        when = datetime.fromtimestamp(timestamp, ZoneInfo(SHABBAT_TIMEZONE)).strftime("%H:%M %d/%m/%Y")
        return f" | הופעל בכפתור: {when}"

    lines = [
        "👥 כתבים פעילים בפועל",
        "",
        "הבדיקה הזו לא עושה RSS ולא משתמשת ב-Gemini. היא מציגה את רשימת הסריקה לפי מצב הכפתורים שנשמר.",
        "",
        f"ייכנסו לסריקה עכשיו: {len(active)} כתבים",
        ", ".join(_hebrew_account_label(username) for username in active) if active else "אין כתבים פעילים",
        "",
        "כתבים ראשיים:",
    ]
    for username in X_ACCOUNTS:
        status = "כבוי קבוע" if username in LOCKED_DISABLED_BASE_ACCOUNTS else ("כבוי" if username in disabled_base else "פעיל")
        marker = "✅" if username in active_set else "⛔"
        lines.append(f"{marker} {_hebrew_account_label(username)}: {status}{since_text(username)}")

    lines.extend(["", "כתבים אופציונליים:"])
    for username in OPTIONAL_CONTROLLED_ACCOUNTS:
        status = "פעיל" if username in enabled_optional else "כבוי"
        marker = "✅" if username in active_set else "⛔"
        lines.append(f"{marker} {_hebrew_account_label(username)}: {status}{since_text(username)}")
    return "\n".join(lines)


def last_sent_post_text() -> str:
    state = load_control_state()
    item = state.get("last_sent_post")
    if not isinstance(item, dict):
        return "📬 פוסט אחרון שנשלח\n\nעדיין לא נשמר פוסט אחרון שנשלח מאז העדכון הזה."
    ts = float(item.get("ts", 0) or 0)
    when = datetime.fromtimestamp(ts, ZoneInfo(SHABBAT_TIMEZONE)).strftime("%H:%M %d/%m/%Y") if ts else "לא ידוע"
    return (
        "📬 פוסט אחרון שנשלח\n\n"
        f"כתב: {_hebrew_account_label(str(item.get('username', '')))}\n"
        f"שעה: {when}\n"
        f"קישור: {item.get('link', '')}"
    )


def simple_stat_text(kind: str) -> str:
    bucket = _daily_stats_bucket()
    sent_total = sum(count for _key, count in _top_daily_items("sent", 1000))
    skipped_total = sum(count for _key, count in _top_daily_items("skips", 1000))
    if kind in {"active_writer", "posts_by_writer"}:
        recent_snapshot = live_recent_snapshot_from_rss()
    else:
        recent_snapshot = bucket.get("fetched_recent_24h_snapshot", {})
    if not isinstance(recent_snapshot, dict) or not recent_snapshot:
        recent_snapshot = bucket.get("fetched_recent_24h", {})
    if not isinstance(recent_snapshot, dict):
        recent_snapshot = {}
    if kind == "active_writer":
        items = sorted(((str(key), int(value or 0)) for key, value in recent_snapshot.items()), key=lambda item: item[1], reverse=True)[:10]
        if not items:
            return "🏆 הכתב הכי פעיל ביממה האחרונה\n\nאין עדיין נתונים מהיממה האחרונה."
        username, count = items[0]
        return f"🏆 הכתב הכי פעיל ביממה האחרונה\n\n{_hebrew_account_label(username)} עם {count} פוסטים שפורסמו ב-24 השעות האחרונות לפי בדיקת RSS חיה.\n\nזה לא אומר שכולם יישלחו: אחרי זה עדיין יש סינון, כפילויות ובדיקת פוסטים שכבר סומנו."
    if kind == "success_rate":
        total = sent_total + skipped_total
        pct = round((sent_total / total) * 100, 1) if total else 0
        return f"📊 אחוז הצלחה היום\n\nנשלחו: {sent_total}\nנחסמו: {skipped_total}\nאחוז שליחה מתוך פוסטים שנבדקו: {pct}%"
    if kind == "sent_today":
        return f"✅ כמה נשלחו היום\n\nנשלחו היום: {sent_total}"
    if kind == "blocked_today":
        return f"🚫 כמה נחסמו היום\n\nנחסמו לפני תרגום/שליחה: {skipped_total}"
    if kind == "old_posts":
        count = int((bucket.get("skip_reasons", {}) or {}).get(BLOCK_REASON_HEBREW.get("old_post", "פוסט ישן מדי"), 0) or 0)
        return f"⏳ פוסטים ישנים מדי\n\nנרשמו היום: {count}\nחלון הגיל שמותר לשליחה כרגע: {max_post_age_text()}.\nבזמן ההפעלה הראשוני הם לא נכנסים לדוח 'למה לא נשלח' כדי שלא יהיה רעש התחלה."
    if kind == "posts_by_writer":
        lines = []
        for i, username in enumerate(all_control_test_accounts(), 1):
            lines.append(f"{i}. {_hebrew_account_label(username)} - {int(recent_snapshot.get(username, 0) or 0)}")
        return "📋 כמה פוסטים כל כתב פרסם ביממה האחרונה\n\nלפי בדיקת RSS חיה, באותה דרך של כפתור בדיקת כל הכתבים.\n\n" + "\n".join(lines)
    if kind == "top_blocks":
        items = _top_daily_items("skip_reasons", 10)
        if not items:
            return "🧱 טופ 10 סיבות חסימה\n\nאין עדיין חסימות."
        return "🧱 טופ 10 סיבות חסימה\n\n" + "\n".join(f"{i}. {r} - {c}" for i,(r,c) in enumerate(items,1))
    if kind == "most_blocked_writer":
        items = _top_daily_items("skips", 10)
        if not items:
            return "😅 הכתב שנחסם הכי הרבה\n\nאין עדיין נתונים."
        u,c=items[0]
        return f"😅 הכתב שנחסם הכי הרבה\n\n{_hebrew_account_label(u)} - {c} חסימות"
    if kind == "gemini_failures":
        items = _top_daily_items("gemini_failures", 10)
        total = sum(count for _key, count in items)
        if not items:
            return "❌ כמה פעמים Gemini נכשל\n\nלא נרשמו היום כשלי Gemini."
        return "❌ כמה פעמים Gemini נכשל היום\n\n" + f"סה״כ: {total}\n" + "\n".join(f"{i}. {reason} - {count}" for i,(reason,count) in enumerate(items,1))
    if kind in {"longest_post", "shortest_post"}:
        return daily_stat_post_length_text(kind)
    if kind == "avg_scan":
        avg, count, max_seconds = daily_stat_average_seconds("scan_seconds")
        if not count:
            return "⚡ זמן סריקה ממוצע\n\nעדיין לא נשמרו סריקות היום."
        return f"⚡ זמן סריקה ממוצע\n\nממוצע: {avg:.2f} שניות לכתב\nמדידות: {count}\nהכי איטי היום: {max_seconds:.2f} שניות"
    if kind == "avg_translation":
        avg, count, max_seconds = daily_stat_average_seconds("translation_seconds")
        if not count:
            return "🧠 זמן תרגום ממוצע\n\nעדיין לא נשמרו תרגומים מוצלחים היום."
        return f"🧠 זמן תרגום ממוצע\n\nממוצע: {avg:.2f} שניות לפוסט שנשלח\nמדידות: {count}\nהכי איטי היום: {max_seconds:.2f} שניות"
    return build_daily_quality_report_text()

def category_help_text(category: str) -> str:
    if category == "monitor":
        return (
            "ℹ️ הסבר בדיקה וניטור\n\n"
            "הקטגוריה הזו מיועדת לבדיקות מצב בלבד. הכפתורים כאן לא מתרגמים פוסטים ולא משתמשים ב-Gemini.\n\n"
            "🔄 בדוק את כל הכתבים עכשיו — עושה שליפת RSS לכל הכתבים הפעילים ומחזיר כמה פוסטים נמצאו. לא שולח פוסטים ולא מפעיל תרגום.\n"
            "👥 כתבים פעילים בפועל — מציג מי באמת נכנס לסריקה לפי מצב הכפתורים שנשמר. לא עושה RSS ולא משתמש ב-Gemini.\n"
            "📬 פוסט אחרון שנשלח — מציג את הפוסט האחרון שהבוט שמר כשליחה. לא עושה שליפה חדשה.\n"
            "↩️ למה לא נשלח — מציג חסימות אחרונות.\n"
            "🧠 כפילות אחרונה — מציג כפילויות שנחסמו.\n"
            "📡 RSS תקין — בודק אם מקורות ה-RSS מחזירים פוסטים. לא משתמש ב-Gemini.\n"
            "🤖 Gemini תקין — בודק רק אם מפתחות טעונים וזמינים מקומית. אין בקשה אמיתית ל-Gemini ואין בזבוז קרדיט.\n"
            "🏆/📊/✅/🚫/⏳ — מציגים נתונים שכבר נשמרו בדוח היומי."
        )
    if category == "filter":
        return (
            "ℹ️ הסבר הגדרות וסינון\n\n"
            "כאן נמצאים הכפתורים שמשנים בפועל את מה שהבוט שולח. גם הכפתורים האלה לא משתמשים ב-Gemini; הם רק משנים מצב בקובץ הבקרה.\n\n"
            "🌙 מצב לילה — מפעיל מצב שקט עד 07:00 לפי שעון ישראל.\n"
            "⭐ רק גדולות — מגביל זמנית לדיווחים חזקים על קבוצות גדולות.\n"
            "🛡️ סינון קשוח — מחמיר את הסינון לשעתיים.\n"
            "🚨/🌍/🩺/📸 — חסימת שמועות, נבחרות, פציעות או פוסטים חברתיים.\n"
            "🟢 רק Here We Go — שולח רק דיווחים חזקים מאוד מסוג Here We Go.\n"
            "🏅 רק טופ 5 — מגביל לליגות הבכירות.\n"
            "🔵⚪ רק ריאל וברצלונה — כפתור אחד שמפעיל/מכבה סינון לשתי הקבוצות ביחד."
        )
    if category == "stats":
        return (
            "ℹ️ הסבר סטטיסטיקות\n\n"
            "הקטגוריה הזו מציגה נתונים שכבר נאספו ונשמרו. היא לא מפעילה Gemini ולא שולחת פוסטים.\n\n"
            "📈 סיכום היום עכשיו — דוח מלא בעברית על הפעילות היום.\n"
            "🏆 הכתב הכי פעיל — מי החזיר הכי הרבה פוסטים ב-RSS.\n"
            "📋 כמה פוסטים כל כתב פרסם — פירוט לפי כתבים.\n"
            "🧱 טופ סיבות חסימה — למה פוסטים נחסמו.\n"
            "😅 מי נחסם הכי הרבה — לפי הסטטיסטיקה היומית.\n"
            "מדדי הזמן, כשלי Gemini והפוסט הארוך/קצר נאספים בזמן אמת מתוך הסריקות והשליחות בפועל."
        )
    if category == "teams":
        return teams_help_text("menu")
    if category == "account_latest":
        return (
            "ℹ️ הסבר בדיקת כתב ספציפי\n\n"
            "הרשימה מציגה רק את הכתבים הפעילים כרגע בבוט. פתיחת הרשימה לא עושה שליפה ולא משתמשת ב-Gemini.\n\n"
            "לחיצה על כתב כן שולפת RSS רק לאותו כתב, ואז שולחת את הפוסט האחרון שלו לערוץ השקט בלבד. "
            "רק בשלב השליחה בפועל יכול להיות שימוש ב-Gemini לצורך תרגום ההודעה.\n\n"
            "כפתור החזרה מחזיר למסך הראשי באותה הודעה."
        )
    return control_buttons_help_text()

def control_buttons_help_text() -> str:
    return (
        "ℹ️ הסבר כפתורים מורחב\n\n"
        "המסך הראשי מחולק לקטגוריות, ובנוסף יש בו בדיקת כתב ספציפי, סיכום היום עכשיו והסבר כפתורים.\n\n"
        "🔎 בדיקה וניטור\n"
        "כאן יש בדיקות מיידיות: בדיקת כל הכתבים הפעילים, בדיקת כתב ספציפי, RSS, Gemini, פוסט אחרון שנשלח ונתוני פעילות בסיסיים.\n"
        "בדיקת כתב ספציפי שולחת את הפוסט האחרון שלו לערוץ השקט בלבד, בכוח, גם אם הסינון הרגיל היה חוסם אותו. זה מיועד לבדיקה בלבד ולא לערוץ הראשי.\n\n"
        "🛡️ הגדרות וסינון\n"
        "כאן נמצאים המצבים שמשנים בפועל את מה שהבוט שולח: מצב לילה, רק גדולות, סינון קשוח, חסימת שמועות, חסימת נבחרות, חסימת פציעות, חסימת פוסטים חברתיים, רק Here We Go, רק טופ 5, רק ברצלונה ורק ריאל.\n"
        "רק ברצלונה ורק ריאל הם שני כפתורי הקבוצות היחידים. הפעלה של אחד מהם מכבה את השני כדי שלא תהיה סתירה.\n\n"
        "📊 סטטיסטיקות\n"
        "כאן יש נתוני פעילות: כמה נשלח, כמה נחסם, מי הכתב הכי פעיל, טופ סיבות חסימה, מי נחסם הכי הרבה ועוד. הדוח היומי נשמר לקובץ מקומי וממשיך גם אחרי הפעלה מחדש באותו שרת.\n\n"
        "🏟️ ניהול קבוצות\n"
        "מציג את דרגי הקבוצות והנבחרות. הוספה, הסרה והעברה נעשות בכפתורים; מקלידים ידנית רק את שם הקבוצה או הנבחרת.\n\n"
        "📊 סיכום היום עכשיו\n"
        "שולח מיד דוח מלא בעברית על היום הנוכחי.\n\n"
        "↩️ למה לא נשלח\n"
        "מציג את 5 החסימות האחרונות. פוסטים ישנים מדי כן ידווחו, אבל בזמן ההפעלה הראשוני הם מוסתרים כדי שלא יהיה רעש התחלה.\n\n"
        "🧠 כפילות אחרונה\n"
        "מציג כפילויות אחרונות שהבוט חסם.\n\n"
        "🔓 ביטול כל הסינונים הזמניים\n"
        "מכבה מצב לילה, רק גדולות, סינון קשוח וכל כפתורי הסינון, ומחזיר את הבוט למצב רגיל."
    )

def next_morning_timestamp() -> float:
    now_dt = datetime.now(ZoneInfo(SHABBAT_TIMEZONE))
    target = now_dt.replace(hour=7, minute=0, second=0, microsecond=0)
    if target <= now_dt:
        target += timedelta(days=1)
    return target.timestamp()


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
    if data == "football_quick_main":
        if callback_id:
            answer_control_callback(callback_id, "חזרה לראשי")
        send_control_menu("כלים מהירים לבוט הכדורגל.", quick_control_reply_markup(), message.get("message_id"))
    elif data == "football_menu_monitor":
        if callback_id:
            answer_control_callback(callback_id, "פותח בדיקה וניטור")
        send_control_menu("🔎 בדיקה וניטור\nבחר פעולה. הכל כאן ללא Gemini וללא שליחת פוסטים.", monitor_menu_reply_markup(), message.get("message_id"))
    elif data == "football_menu_writers":
        if callback_id:
            answer_control_callback(callback_id, "פותח ניהול כתבים")
        send_control_menu("👥 ניהול כתבים\nכאן מפעילים או מכבים כתבים. הרשימה הזו היא המקור לרשימת הסריקה בפועל.", writers_management_reply_markup(is_control_paused()), message.get("message_id"))
    elif data == "football_menu_filter":
        if callback_id:
            answer_control_callback(callback_id, "פותח הגדרות וסינון")
        send_control_menu("🛡️ הגדרות וסינון\nהסינונים נשמרים קבוע עד שמכבים אותם. אין כאן שימוש ב-Gemini.", filter_menu_reply_markup(), message.get("message_id"))
    elif data == "football_menu_stats":
        if callback_id:
            answer_control_callback(callback_id, "פותח סטטיסטיקות")
        send_control_menu("📊 סטטיסטיקות\nנתונים שנאספו ונשמרו. אין כאן שימוש ב-Gemini.", stats_menu_reply_markup(), message.get("message_id"))
    elif data == "football_menu_teams":
        if callback_id:
            answer_control_callback(callback_id, "פותח ניהול קבוצות")
        save_control_state(pending_team_action="", pending_team_tier="")
        send_control_menu("🏟️ ניהול קבוצות\nבחר צפייה או פעולה.", teams_menu_reply_markup(), message.get("message_id"))
    elif data == "football_teams_group:view":
        if callback_id:
            answer_control_callback(callback_id, "פותח רשימות")
        send_control_menu("👀 צפייה ברשימות\nבחר דרג.", teams_view_menu_reply_markup(), message.get("message_id"))
    elif data == "football_teams_group:actions":
        if callback_id:
            answer_control_callback(callback_id, "פותח פעולות")
        send_control_menu("⚙️ פעולות ניהול\nבחר פעולה. רק את שם הקבוצה מקלידים ידנית.", teams_actions_menu_reply_markup(), message.get("message_id"))
    elif data.startswith("football_teams_list:"):
        tier = data.split(":", 1)[1]
        if callback_id:
            answer_control_callback(callback_id, "מציג רשימה")
        send_control_text(team_tier_list_text(tier), message.get("message_id"), teams_menu_reply_markup())
    elif data.startswith("football_teams_action:"):
        action = data.split(":", 1)[1]
        if action == "remove":
            save_control_state(pending_team_action="remove", pending_team_tier="")
            if callback_id:
                answer_control_callback(callback_id, "כתוב שם להסרה")
            send_control_text("➖ הסרת קבוצה/נבחרת\n\nעכשיו כתוב רק את השם המדויק להסרה.", message.get("message_id"), teams_actions_menu_reply_markup())
        elif action in {"add", "move"}:
            if callback_id:
                answer_control_callback(callback_id, "בחר דרג")
            title = "הוספה" if action == "add" else "העברת דרג"
            send_control_menu(f"{'➕' if action == 'add' else '🔁'} {title}\nבחר דרג יעד, ואז תתבקש להקליד שם.", team_tier_choice_reply_markup(action), message.get("message_id"))
        else:
            if callback_id:
                answer_control_callback(callback_id, "פעולה לא מוכרת")
    elif data.startswith("football_teams_pick_tier:"):
        _prefix, action, tier = data.split(":", 2)
        if action not in {"add", "move"} or tier not in TEAM_TIER_LABELS:
            if callback_id:
                answer_control_callback(callback_id, "בחירה לא מוכרת")
            return
        save_control_state(pending_team_action=action, pending_team_tier=tier)
        if callback_id:
            answer_control_callback(callback_id, "כתוב שם")
        action_he = "להוספה" if action == "add" else "להעברה"
        send_control_text(f"✍️ כתוב שם {action_he}\n\nדרג יעד: {TEAM_TIER_LABELS[tier]}\nעכשיו כתוב רק את שם הקבוצה או הנבחרת.", message.get("message_id"), teams_actions_menu_reply_markup())
    elif data.startswith("football_teams_help:"):
        mode = data.split(":", 1)[1]
        if callback_id:
            answer_control_callback(callback_id, "מציג הסבר")
        send_control_text(teams_help_text(mode), message.get("message_id"), teams_menu_reply_markup())
    elif data == "football_choose_account_latest":
        if callback_id:
            answer_control_callback(callback_id, "בחר כתב")
        send_control_menu("👤 בדוק כתב ספציפי\nמוצגים כל 14 הכתבים שמוגדרים בבוט, כולל כתבים שכרגע כבויים. הבחירה תשלח את הפוסט האחרון של הכתב לערוץ השקט בלבד.", account_latest_menu_reply_markup(), message.get("message_id"))
    elif data.startswith("football_test_latest_account:"):
        username = data.split(":", 1)[1]
        if username not in all_control_test_accounts():
            if callback_id:
                answer_control_callback(callback_id, "כתב לא מוכר")
            return
        if callback_id:
            answer_control_callback(callback_id, f"בודק את {_hebrew_account_label(username)}")
        run_latest_account_control_test(username)
    elif data == "football_check_all_accounts_now":
        if callback_id:
            answer_control_callback(callback_id, "בודק את כל הכתבים")
        send_control_text(check_all_accounts_now_text(), message.get("message_id"), monitor_menu_reply_markup())
    elif data == "football_active_accounts_status":
        if callback_id:
            answer_control_callback(callback_id, "מציג כתבים פעילים")
        send_control_text(active_accounts_status_text(), message.get("message_id"), monitor_menu_reply_markup())
    elif data == "football_rss_status":
        if callback_id:
            answer_control_callback(callback_id, "בודק RSS")
        send_control_text(rss_status_text(), message.get("message_id"), monitor_menu_reply_markup())
    elif data == "football_gemini_status":
        if callback_id:
            answer_control_callback(callback_id, "בודק Gemini")
        send_control_text(gemini_status_text(), message.get("message_id"), monitor_menu_reply_markup())
    elif data == "football_gemini_toggle_quota_guard":
        if callback_id:
            answer_control_callback(callback_id, "מעדכן הגנת Gemini")
        send_control_text(gemini_toggle_quota_guard(), message.get("message_id"), monitor_menu_reply_markup())
    elif data == "football_gemini_clear_local_cooldown":
        if callback_id:
            answer_control_callback(callback_id, "משחרר קירור מקומי")
        send_control_text(gemini_clear_local_cooldowns(), message.get("message_id"), monitor_menu_reply_markup())
    elif data == "football_last_sent_post":
        if callback_id:
            answer_control_callback(callback_id, "מציג פוסט אחרון")
        send_control_text(last_sent_post_text(), message.get("message_id"), monitor_menu_reply_markup())
    elif data.startswith("football_stat_"):
        kind = data.replace("football_stat_", "", 1)
        if callback_id:
            answer_control_callback(callback_id, "מציג נתון")
        send_control_text(simple_stat_text(kind), message.get("message_id"), stats_menu_reply_markup())
    elif data.startswith("football_toggle_mode:"):
        key = data.split(":", 1)[1]
        if key not in {"night_mode", "elite_only", "strict_filter"}:
            if callback_id:
                answer_control_callback(callback_id, "מצב לא מוכר")
            return
        state = load_control_state()
        new_value = not bool(state.get(key, False))
        save_control_state(**{key: new_value, f"{key}_until": 0.0})
        if callback_id:
            answer_control_callback(callback_id, "עודכן")
        send_control_menu("🛡️ הגדרות וסינון - עודכן\nהמצב נשמר קבוע עד שמכבים אותו.", filter_menu_reply_markup(), message.get("message_id"))
    elif data.startswith("football_toggle_filter:"):
        key = data.split(":", 1)[1]
        if key not in CONTROL_FILTER_KEYS:
            if callback_id:
                answer_control_callback(callback_id, "סינון לא מוכר")
            return
        state = load_control_state()
        new_value = not bool(state.get(key, False))
        updates = {key: new_value}
        save_control_state(**updates)
        if callback_id:
            answer_control_callback(callback_id, "עודכן")
        send_control_menu("🛡️ הגדרות וסינון - עודכן", filter_menu_reply_markup(), message.get("message_id"))
    elif data == "football_bot_off":
        save_control_state(True)
        logging.info("⏸️ לוח שליטה: הבוט הושהה דרך הכפתור.")
        if callback_id:
            answer_control_callback(callback_id, "הבוט כובה")
        send_control_panel(True, "הפעולה בוצעה בהצלחה: הבוט כובה.")
    elif data == "football_bot_on":
        save_control_state(False, resume_min_ts=time.time() - CONTROL_RESUME_BACKLOG_SECONDS)
        logging.info("▶️ לוח שליטה: הבוט הופעל מחדש דרך הכפתור.")
        if callback_id:
            answer_control_callback(callback_id, "הבוט הופעל")
        send_control_panel(False, "\u05d4\u05e4\u05e2\u05d5\u05dc\u05d4 \u05d1\u05d5\u05e6\u05e2\u05d4 \u05d1\u05d4\u05e6\u05dc\u05d7\u05d4: \u05d4\u05d1\u05d5\u05d8 \u05d4\u05d5\u05e4\u05e2\u05dc.")
    elif data == "football_elite_only_2h":
        save_control_state(elite_only=True, elite_only_until=0.0)
        if callback_id:
            answer_control_callback(callback_id, "רק גדולות הופעל קבוע")
        send_control_menu("🛡️ הגדרות וסינון - עודכן", filter_menu_reply_markup(), message.get("message_id"))
    elif data == "football_strict_filter_2h":
        save_control_state(strict_filter=True, strict_filter_until=0.0)
        if callback_id:
            answer_control_callback(callback_id, "סינון קשוח הופעל קבוע")
        send_control_menu("🛡️ הגדרות וסינון - עודכן", filter_menu_reply_markup(), message.get("message_id"))
    elif data == "football_night_mode_until_morning":
        save_control_state(night_mode=True, night_mode_until=0.0)
        if callback_id:
            answer_control_callback(callback_id, "מצב לילה הופעל קבוע")
        send_control_menu("🛡️ הגדרות וסינון - עודכן", filter_menu_reply_markup(), message.get("message_id"))
    elif data == "football_daily_report_now":
        if callback_id:
            answer_control_callback(callback_id, "שולח סיכום עכשיו")
        send_control_text(build_daily_quality_report_text(), message.get("message_id"), quick_control_reply_markup())
    elif data == "football_test_latest_fabrizio":
        if callback_id:
            answer_control_callback(callback_id, "בודק את פבריציו האחרון")
        run_latest_fabrizio_control_test()
    elif data == "football_last_blocked":
        if callback_id:
            answer_control_callback(callback_id, "מציג חסימות אחרונות")
        state = load_control_state()
        blocked_posts = list(state.get("last_blocked_posts", [])) if isinstance(state.get("last_blocked_posts", []), list) else []
        blocked_posts = [item for item in blocked_posts if isinstance(item, dict)][-5:]
        send_control_text(_control_list_text("↩️ למה לא נשלח - 5 אחרונים", blocked_posts, "אין חסימות שמורות כרגע."), message.get("message_id"), monitor_menu_reply_markup())
    elif data == "football_last_duplicate":
        if callback_id:
            answer_control_callback(callback_id, "מציג כפילויות אחרונות")
        state = load_control_state()
        send_control_text(_control_list_text("🧠 כפילויות אחרונות", list(state.get("last_duplicate_posts", [])) if isinstance(state.get("last_duplicate_posts", []), list) else [], "אין כפילויות שמורות כרגע."), message.get("message_id"), monitor_menu_reply_markup())
    elif data.startswith("football_category_help:"):
        category = data.split(":", 1)[1]
        if callback_id:
            answer_control_callback(callback_id, "מציג הסבר קטגוריה")
        markup = (
            monitor_menu_reply_markup() if category == "monitor" else
            filter_menu_reply_markup() if category == "filter" else
            stats_menu_reply_markup() if category == "stats" else
            teams_menu_reply_markup() if category == "teams" else
            account_latest_menu_reply_markup() if category == "account_latest" else
            quick_control_reply_markup()
        )
        send_control_text(category_help_text(category), message.get("message_id"), markup)
    elif data == "football_buttons_help":
        if callback_id:
            answer_control_callback(callback_id, "מציג הסבר כפתורים")
        send_control_text(control_buttons_help_text(), message.get("message_id"), quick_control_reply_markup())
    elif data == "football_clear_temp_modes":
        save_control_state(
            elite_only=False, strict_filter=False, night_mode=False,
            elite_only_until=0.0, strict_filter_until=0.0, night_mode_until=0.0,
            **{key: False for key in CONTROL_FILTER_KEYS},
        )
        if callback_id:
            answer_control_callback(callback_id, "כל הסינונים בוטלו")
        logging.info("🔓 לוח שליטה: כל הסינונים בוטלו.")
        send_control_menu("🛡️ הגדרות וסינון - כל הסינונים בוטלו", filter_menu_reply_markup(), message.get("message_id"))
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
            enabled_at = remove_account_enabled_at(state, username)
            action_text = f"{label} כובה"
            logging.info("⏸️ לוח שליטה: הכתב האופציונלי @%s כובה בכפתור ולא ייסרק.", username)
        else:
            enabled.add(username)
            enabled_at = mark_account_enabled_at(state, username)
            action_text = f"{label} הופעל"
            logging.info("▶️ לוח שליטה: הכתב האופציונלי @%s הופעל בכפתור וייכנס לסריקה.", username)
        save_control_state(enabled_optional_accounts=[account for account in OPTIONAL_CONTROLLED_ACCOUNTS if account in enabled], account_enabled_at=enabled_at)
        if callback_id:
            answer_control_callback(callback_id, action_text)
        suffix = " פוסטים שיפורסמו אחרי ההפעלה ייבדקו בסריקה הבאה." if username in enabled else ""
        send_control_menu(f"👥 ניהול כתבים\nהפעולה בוצעה בהצלחה: {action_text}.{suffix}", writers_management_reply_markup(is_control_paused()), message.get("message_id"))
    elif data.startswith("football_base_account:"):
        username = data.split(":", 1)[1]
        if username not in X_ACCOUNTS:
            if callback_id:
                answer_control_callback(callback_id, "כתב לא מוכר")
            return
        if username in LOCKED_DISABLED_BASE_ACCOUNTS:
            if callback_id:
                answer_control_callback(callback_id, "הכתב נשאר כבוי לפי ההגדרה")
            send_control_menu("👥 ניהול כתבים\nג'אנלוקה די מארציו נשאר כבוי ולא ייכנס לסריקה.", writers_management_reply_markup(is_control_paused()), message.get("message_id"))
            return
        state = load_control_state()
        disabled = set(disabled_base_accounts_from_state(state))
        label = CONTROLLED_BASE_ACCOUNT_LABELS.get(username, ACCOUNT_DISPLAY_NAMES.get(username, username))
        if username in disabled:
            disabled.remove(username)
            enabled_at = mark_account_enabled_at(state, username)
            action_text = f"{label} הופעל"
            logging.info("▶️ לוח שליטה: הכתב @%s הופעל מחדש בכפתור.", username)
        else:
            disabled.add(username)
            enabled_at = remove_account_enabled_at(state, username)
            action_text = f"{label} כובה"
            logging.info("⏸️ לוח שליטה: הכתב @%s כובה בכפתור ולא ייסרק עד להפעלה מחדש.", username)
        save_control_state(disabled_base_accounts=[account for account in X_ACCOUNTS if account in disabled], account_enabled_at=enabled_at)
        if callback_id:
            answer_control_callback(callback_id, action_text)
        suffix = " פוסטים שיפורסמו אחרי ההפעלה ייבדקו בסריקה הבאה." if username not in disabled else ""
        send_control_menu(f"👥 ניהול כתבים\nהפעולה בוצעה בהצלחה: {action_text}.{suffix}", writers_management_reply_markup(is_control_paused()), message.get("message_id"))


def process_channel_post_update(update: dict[str, Any]) -> None:
    message = update.get("channel_post") or update.get("edited_channel_post") or {}
    if not isinstance(message, dict):
        return
    chat = message.get("chat", {}) or {}
    chat_id = str(chat.get("id", ""))
    if CONTROL_CHAT_ID and chat_id == CONTROL_CHAT_ID:
        return
    if chat_id not in set(TELEGRAM_CHAT_IDS):
        return
    text = str(message.get("text") or message.get("caption") or "").strip()
    if not text:
        return
    try:
        state = load_state()
        message_id = str(message.get("message_id", ""))
        update_source = "channel_edit" if update.get("edited_channel_post") else "channel"
        remember_channel_news_text(text, state, message_id=message_id, source=update_source, chat_id=chat_id)
        save_state(state)
        logging.info(
            "🧠 זיכרון כפילויות מהערוץ: נשמרה %s %s ל-12 שעות | טקסט: %s",
            "עריכה" if update_source == "channel_edit" else "הודעה",
            message_id or "unknown",
            re.sub(r"\s+", " ", text)[:260],
        )
    except Exception as exc:
        logging.debug("זיכרון כפילויות מהערוץ נכשל: %s", exc)


def process_control_text_update(update: dict[str, Any]) -> None:
    message = update.get("message") or update.get("channel_post") or update.get("edited_channel_post") or {}
    if not isinstance(message, dict):
        return
    chat = message.get("chat", {}) or {}
    chat_id = str(chat.get("id", ""))
    if CONTROL_CHAT_ID and chat_id != CONTROL_CHAT_ID:
        return
    text = str(message.get("text") or "").strip()
    if not text:
        return
    result = handle_team_management_command(text)
    if result is None:
        return
    response, tier = result
    send_control_text(response, None, team_after_action_reply_markup(tier))


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
        logging.debug("לוח שליטה: webhook נוקה, מאזין לכפתורים דרך polling.")
    except Exception as exc:
        logging.debug("לוח שליטה: לא הצליח לנקות webhook לפני polling: %s", exc)


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
            send_quick_control_panel(force_new=True)
        except Exception as exc:
            logging.debug("לוח שליטה: אתחול נכשל: %s", exc)
    else:
        try:
            ensure_control_panel_once_if_requested()
        except Exception as exc:
            logging.debug("לוח שליטה: יצירת לוח חסר נכשלה: %s", exc)
        logging.debug("לוח שליטה: שליחה בהפעלה כבויה; כפתורים קיימים עדיין יעבדו.")
    while True:
        try:
            response = telegram_api(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": int(os.environ.get("CONTROL_GETUPDATES_TIMEOUT", "10")),
                    "allowed_updates": ["callback_query", "message", "channel_post", "edited_channel_post"],
                },
            )
            for update in response.get("result", []):
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                save_control_state(control_update_offset=offset)
                process_control_update(update)
                process_control_text_update(update)
                process_channel_post_update(update)
        except Exception as exc:
            if is_getupdates_conflict(exc):
                logging.debug("לוח שליטה: התנגשות getUpdates, מנסה לנקות webhook.")
                now = time.time()
                if now - last_conflict_cleanup > 30:
                    last_conflict_cleanup = now
                    try:
                        telegram_api("deleteWebhook", {"drop_pending_updates": True}, max_attempts=1)
                    except Exception as cleanup_exc:
                        logging.warning("⚠️ לוח שליטה: ניקוי התנגשות נכשל: %s", cleanup_exc)
                time.sleep(CONTROL_POLL_SECONDS)
                continue
            logging.warning("⚠️ לוח שליטה: האזנה לכפתורים נכשלה: %s", exc)
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
        logging.warning("⚠️ מצב שבת: לא הצליח לשמור cache זמני שבת: %s", exc)


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
            logging.info("🕯️ מצב שבת: זמני שבת עודכנו")
        except Exception as exc:
            logging.warning("⚠️ מצב שבת: Hebcal לא זמין, משתמש בזמני גיבוי: %s", exc)
            return fallback_shabbat_now(now)
    return any(start <= now <= end for start, end in windows)


def mark_existing_posts_seen(state: dict[str, list[str]]) -> None:
    logging.info("🕯️ מצב שבת: מסמן פוסטים קיימים כנצפו בלי לשלוח")
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

MATCH_CONTEXT_NOISE_PATTERNS = (
    r"\b(?:line[- ]?up|starting XI|XI|predicted XI|probable XI|team news|training|trained|arrived|arrival|stadium|hotel|warm[- ]?up|walkout|dressing room|locker room|pre[- ]?match|post[- ]?match|press conference|mixed zone|reaction|reacts|asked about|on his performance|World Cup mode|matchday|kick[- ]?off)\b",
    r"הרכב|ההרכב|הרכבים|פותח|פותחים|צפוי לפתוח|צפויים לפתוח|אימון|התאמן|התאמנו|הגעה|הגיעו|אצטדיון|מלון|חימום|חדר הלבשה|לפני המשחק|אחרי המשחק|מסיבת עיתונאים|תגובה|נשאל על|מצב משחק|יום משחק|שריקת פתיחה",
)

AUDIENCE_OR_QUESTION_PATTERNS = (
    r"\b(?:who was your|your player of the match|what do you think|thoughts\?|would you|should he|should they|poll|vote|votes?|voting|question|who wins?|who goes through)\b",
    r"מי היה|מה דעתכם|מה אתם חושבים|הייתם|צריך לדעתכם|סקר|הצביעו|הצבעה|הצבעות|שאלה|מי עולה|מי מנצח",
)

LINEUP_OR_TEAMSHEET_PATTERNS = (
    r"\b(?:official\s+)?(?:line[- ]?ups?|starting XI|starting eleven|probable XI|predicted XI|team sheets?|teamsheet|confirmed XI)\b",
    r"הרכבים?\s+רשמיים|ההרכבים?\s+הרשמיים|הרכב\s+רשמי|ההרכב\s+הרשמי|הרכב\s+פותח|פותחים\s+ב|ההרכבים?\s+למשחק",
)

POLL_OR_AUDIENCE_PATTERNS = (
    r"\b(?:poll|vote|votes?|voting|who wins?|who goes through|question)\b|(?:\d{1,3}%.*\d{1,3}%|votes?\s*[•-])",
    r"סקר|הצביעו|הצבעה|הצבעות|מי עולה|מי מנצח|\d{1,3}%.*\d{1,3}%|\d[\d,\.]*\s+הצבעות",
)

WORLD_CUP_BRACKET_NOISE_PATTERNS = (
    r"\b(?:World Cup|FIFA World Cup)\b.{0,120}\b(?:round of 32|round of 16|last 32|last 16|knockout|qualified|qualifies|advanced|advances|vs\.?|v)\b",
    r"\b(?:round of 32|round of 16|last 32|last 16|knockout|qualified|qualifies|advanced|advances|vs\.?|v)\b.{0,120}\b(?:World Cup|FIFA World Cup)\b",
    r"\b(?:World Cup|FIFA World Cup)\b.{0,160}\b(?:eliminated|knocked out|out of the tournament|crashed out|through to|goes through|set up a clash|will face|face each other|fixture confirmed|bracket|qualified for the knockout)\b",
    r"\b(?:eliminated|knocked out|out of the tournament|crashed out|through to|goes through|set up a clash|will face|face each other|fixture confirmed|bracket|qualified for the knockout)\b.{0,160}\b(?:World Cup|FIFA World Cup)\b",
    r"(?:מונדיאל|גביע העולם).{0,120}(?:שמינית|שלב\s+32|נוקאאוט|העפיל|העפילה|העפילו|נגד|🆚|מי עולה)",
    r"(?:שמינית|שלב\s+32|נוקאאוט|העפיל|העפילה|העפילו|נגד|🆚|מי עולה).{0,120}(?:מונדיאל|גביע העולם)",
    r"(?:מונדיאל|גביע העולם).{0,160}(?:הודח|הודחה|הודחו|מודחת|מודחות|עלתה|עלו|עולה|עולות|הבטיחה מקום|הבטיחו מקום|נקבע|נקבעו|תפגוש|יפגשו|ייפגשו|מי מול מי|המשחק בין|העפילה לשלב|עלתה לשלב)",
    r"(?:הודח|הודחה|הודחו|מודחת|מודחות|עלתה|עלו|עולה|עולות|הבטיחה מקום|הבטיחו מקום|נקבע|נקבעו|תפגוש|יפגשו|ייפגשו|מי מול מי|המשחק בין|העפילה לשלב|עלתה לשלב).{0,160}(?:מונדיאל|גביע העולם)",
)

LIVE_GOAL_OR_MATCH_MOMENT_PATTERNS = (
    r"\b(?:scores?|scored|goal|goals|equalis(?:e|z)r|winner|brace|hat[- ]trick|first goal|debut goal|world cup debut|match debut|against giants?)\b",
    r"\u05db\u05d1\u05e9|\u05db\u05d1\u05e9\u05d4|\u05e9\u05e2\u05e8|\u05e9\u05e2\u05e8\u05d9\u05dd|\u05e9\u05d5\u05d5\u05d9\u05d5\u05df|\u05e9\u05e2\u05e8 \u05e0\u05d9\u05e6\u05d7\u05d5\u05df|\u05e6\u05de\u05d3|\u05e9\u05dc\u05d5\u05e9\u05e2\u05e8|\u05e9\u05e2\u05e8 \u05d1\u05db\u05d5\u05e8\u05d4|\u05d1\u05db\u05d5\u05e8\u05ea \u05d4\u05de\u05d5\u05e0\u05d3\u05d9\u05d0\u05dc|\u05d1\u05d1\u05db\u05d5\u05e8\u05d4|\u05e0\u05d2\u05d3 \u05e2\u05e0\u05e7\u05d9\u05d5\u05ea|\u05dc\u05d0 \u05d4\u05d0\u05de\u05d9\u05df",
)

MEDIA_ONLY_OR_PROMO_PATTERNS = (
    r"\b(?:video|watch video|watch here|watch now|photo|pictures?|gallery|highlights?|clip|full video|new video)\b",
    r"וידאו|וידיאו|צפו|תמונה|תמונות|גלריה|תקציר|קליפ|הסרטון המלא|וידאו חדש",
)

CONTEXTLESS_TEASER_PATTERNS = (
    r"^\s*(?:👀|👇|⤵️|⬇️|🆕|🔜|soon|more to follow|details soon|breakthrough|here we go)?[\s\W]*(?:[A-Z][A-Za-z .'-]{2,30}|Milan|Juventus|Barcelona|Real Madrid|Chelsea|Arsenal|Liverpool|PSG|Bayern|Portugal|Spain|Italy)?\s*$",
    r"^\s*(?:👀|👇|⤵️|⬇️|🆕|🔜|\u05d1\u05e7\u05e8\u05d5\u05d1|\u05e4\u05e8\u05d8\u05d9\u05dd \u05d1\u05e7\u05e8\u05d5\u05d1|\u05de\u05d9\u05dc\u05d0\u05df|\u05d9\u05d5\u05d1\u05e0\u05d8\u05d5\u05e1|\u05d1\u05e8\u05e6\u05dc\u05d5\u05e0\u05d4|\u05e8\u05d9\u05d0\u05dc \u05de\u05d3\u05e8\u05d9\u05d3|\u05e6'\u05dc\u05e1\u05d9|\u05d0\u05e8\u05e1\u05e0\u05dc|\u05dc\u05d9\u05d1\u05e8\u05e4\u05d5\u05dc|\u05d1\u05d0\u05d9\u05d9\u05e8\u05df|\u05e4\u05d5\u05e8\u05d8\u05d5\u05d2\u05dc|\u05e1\u05e4\u05e8\u05d3|\u05d0\u05d9\u05d8\u05dc\u05d9\u05d4)\s*$",
)

VAGUE_STATUS_NEEDS_QUOTE_PATTERNS = (
    r"\b(?:breakthrough|close to full agreement|close to agreement|final details|not a done deal|not closed yet|deal not done|advanced but not done)\b",
    r"\u05e4\u05e8\u05d9\u05e6\u05ea \u05d3\u05e8\u05da|\u05e7\u05e8\u05d5\u05d1 \u05dc\u05d4\u05e1\u05db\u05de\u05d4|\u05d4\u05e1\u05db\u05de\u05d4 \u05de\u05dc\u05d0\u05d4|\u05e4\u05e8\u05d8\u05d9\u05dd \u05d0\u05d7\u05e8\u05d5\u05e0\u05d9\u05dd|\u05e2\u05d3\u05d9\u05d9\u05df \u05dc\u05d0 \u05e2\u05e1\u05e7\u05d4 \u05e1\u05d2\u05d5\u05e8\u05d4",
)

UNCLEAR_SUBJECT_NEWS_PATTERNS = (
    r"\b(?:he|him|his|they|them|it|this|that|the player|the coach|the club|told him|told them|close to agreement|final details|not a done deal|deal not done|breakthrough|more to follow|details soon)\b",
    r"הוא|אותו|אותם|הם|זה|הזה|השחקן|המאמן|המועדון|אמר לו|אמר להם|קרוב להסכמה|פרטים אחרונים|עדיין לא עסקה|לא עסקה סגורה|פריצת דרך|פרטים בקרוב",
)

UNCLEAR_SUBJECT_NEWS_VERB_PATTERNS = (
    r"\b(?:agree|agreed|agreement|sign|join|move|transfer|bid|offer|talks|negotiations|deal|contract|medical|leave|replace|called up|close|done)\b",
    r"סיכם|סיכום|הסכמה|יחתום|חתם|מצטרף|יצטרף|מעבר|העברה|הצעה|שיחות|מגעים|עסקה|חוזה|בדיקות רפואיות|יעזוב|מחליף|זומן|קרוב|נסגר",
)

UNCLEAR_GENERIC_SUBJECT_TOKENS = {
    "פרטים", "אחרונים", "נותרים", "עדיין", "עסקה", "סגורה", "קרוב", "הסכמה", "מלאה",
    "שיחות", "מגעים", "הצעה", "דיווח", "מקורות", "שחקן", "מאמן", "מועדון", "קבוצה",
    "הוא", "אותו", "אותם", "זה", "הזה", "חדש", "חדשה", "בקרוב",
}

UNCLEAR_GENERIC_LATIN_SUBJECT_TOKENS = {
    "breakthrough", "close", "full", "agreement", "final", "details", "remain", "still", "done",
    "deal", "player", "coach", "club", "team", "sources", "exclusive", "new", "soon", "more",
}


def primary_text_has_clear_subject(post: Post) -> bool:
    primary = clean_for_ai_translation(html.unescape(post.text or ""))
    if not primary:
        return False
    primary_post = clone_post_with_text(post, primary)
    if contains_tracked_club_or_israeli_league(primary_post):
        return True
    if _matches_any(BIG_CLUB_RUMOR_PATTERNS, primary) or _matches_any(POPULAR_OR_RECENT_UCL_CLUB_PATTERNS, primary):
        return True
    for replacements in (TEAM_REPLACEMENTS, PLAYER_REPLACEMENTS, HANDLE_REPLACEMENTS):
        for source, target in replacements.items():
            for value in (source, target):
                value = str(value or "").strip()
                if len(value) >= 4 and re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", primary, re.IGNORECASE):
                    return True
    for match in re.finditer(r"\b[A-Z][A-Za-zÀ-ÿ'’.-]{2,}(?:\s+[A-Z][A-Za-zÀ-ÿ'’.-]{2,}){1,3}\b", primary):
        words = [word.lower().strip("-'’") for word in re.findall(r"[A-Za-zÀ-ÿ'’.-]{2,}", match.group(0))]
        meaningful_words = [word for word in words if word not in UNCLEAR_GENERIC_LATIN_SUBJECT_TOKENS]
        if len(meaningful_words) >= 2:
            return True
    hebrew_names = re.findall(r"[א-ת][א-ת'׳-]{2,}", primary)
    meaningful = [
        token for token in hebrew_names
        if _normalize_news_duplicate_token(token) not in NEWS_DUP_STOPWORDS
        and _normalize_news_duplicate_token(token) not in UNCLEAR_GENERIC_SUBJECT_TOKENS
    ]
    return len(meaningful) >= 2


def is_unclear_subject_news_post(post: Post) -> bool:
    primary = clean_for_ai_translation(html.unescape(post.text or ""))
    if not primary:
        return False
    if primary_text_has_clear_subject(post):
        return False
    if not (_matches_any(UNCLEAR_SUBJECT_NEWS_PATTERNS, primary) or _matches_any(VAGUE_STATUS_NEEDS_QUOTE_PATTERNS, primary)):
        return False
    return _matches_any(UNCLEAR_SUBJECT_NEWS_VERB_PATTERNS, primary) or len(_news_duplicate_tokens(primary)) <= 5


def is_contextless_teaser_post(post: Post) -> bool:
    primary = clean_for_ai_translation(html.unescape(post.text or ""))
    if not primary:
        return True
    if has_quoted_context_for_decision(post):
        return False
    tokens = _news_duplicate_tokens(primary) if "_news_duplicate_tokens" in globals() else set(re.findall(r"\w+", primary))
    return bool(len(tokens) <= 2 and _matches_any(CONTEXTLESS_TEASER_PATTERNS, primary))


def has_quoted_context_for_decision(post: Post) -> bool:
    quote = clean_for_ai_translation(html.unescape(post.quoted_text or ""))
    if not quote:
        return False
    quote_post = clone_post_with_text(post, quote)
    if contains_tracked_club_or_israeli_league(quote_post):
        return True
    signature = news_event_signature(quote_post) if "news_event_signature" in globals() else {"entities": [], "tokens": []}
    return bool(len(signature.get("entities", [])) >= 1 and len(signature.get("tokens", [])) >= 4)


def is_vague_status_without_primary_context(post: Post) -> bool:
    primary = clean_for_ai_translation(html.unescape(post.text or ""))
    if not primary:
        return False
    if not _matches_any(VAGUE_STATUS_NEEDS_QUOTE_PATTERNS, primary):
        return False
    primary_only = clone_post_with_text(post, primary)
    if contains_tracked_club_or_israeli_league(primary_only):
        return False
    return not has_quoted_context_for_decision(post)


def is_live_goal_or_match_moment_post(post: Post) -> bool:
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    if not cleaned:
        return False
    if _matches_any(MATCH_NEWS_RESCUE_PATTERNS, cleaned):
        return False
    return _matches_any(LIVE_GOAL_OR_MATCH_MOMENT_PATTERNS, cleaned)


def is_match_result_or_engagement_post(post: Post) -> bool:
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    if not cleaned:
        return False
    if _matches_any(MATCH_NEWS_RESCUE_PATTERNS, cleaned):
        return False
    has_match_result = _matches_any(MATCH_RESULT_OR_ENGAGEMENT_PATTERNS, cleaned)
    has_score = bool(re.search(r"\b\d+\s*[-:]\s*\d+\b", cleaned))
    return bool(has_match_result or has_score)


def is_match_context_noise_post(post: Post) -> bool:
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    if not cleaned or _matches_any(MATCH_NEWS_RESCUE_PATTERNS, cleaned):
        return False
    return _matches_any(MATCH_CONTEXT_NOISE_PATTERNS, cleaned) or _matches_any(AUDIENCE_OR_QUESTION_PATTERNS, cleaned)


def is_lineup_or_teamsheet_post(post: Post) -> bool:
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    return bool(cleaned and _matches_any(LINEUP_OR_TEAMSHEET_PATTERNS, cleaned))


def is_poll_or_audience_post(post: Post) -> bool:
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    return bool(cleaned and _matches_any(POLL_OR_AUDIENCE_PATTERNS, cleaned))


def has_news_action_signal(post: Post) -> bool:
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    return bool(
        _matches_any(TRANSFER_OR_FUTURE_PATTERNS, cleaned)
        or _matches_any(STRONG_PLAYER_MOVE_PATTERNS, cleaned)
        or _matches_any(COACH_IMPORTANT_PATTERNS, cleaned)
        or _matches_any(INJURY_OR_FITNESS_UPDATE_PATTERNS, cleaned)
        or _matches_any(FINAL_OR_NEAR_FINAL_PATTERNS, cleaned)
        or _matches_any(ADMIN_PERSON_EXIT_OR_STATUS_PATTERNS, cleaned)
    )


def is_world_cup_bracket_or_qualification_noise(post: Post) -> bool:
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    if not cleaned:
        return False
    if _matches_any(INJURY_OR_FITNESS_UPDATE_PATTERNS, cleaned):
        return False
    if (
        _matches_any(TRANSFER_OR_FUTURE_PATTERNS, cleaned)
        or _matches_any(COACH_IMPORTANT_PATTERNS, cleaned)
        or _matches_any(ADMIN_PERSON_EXIT_OR_STATUS_PATTERNS, cleaned)
    ):
        return False
    return _matches_any(WORLD_CUP_BRACKET_NOISE_PATTERNS, cleaned)


def has_small_total_transfer_fee(post: Post) -> bool:
    text = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    if not text or MIN_TRANSFER_FEE_MILLIONS_TO_SEND <= 0:
        return False
    lowered = text.lower()
    if re.search(r"\b(?:salary|wages|per season|per year|annual|release clause|clause)\b|שכר|לעונה|לשנה|שנתי|סעיף\s+שחרור", lowered, re.IGNORECASE):
        return False
    if not re.search(r"\b(?:fee|package|deal worth|transfer fee|for|from)\b|תמורת|דמי\s+העברה|עסקה|בונוסים\s+כלולים|מ-|\bfrom\b", text, re.IGNORECASE):
        return False
    amount_patterns = (
        r"(?i)(?:€|£|\$)\s*(\d+(?:[.,]\d+)?)\s*(?:m|million|מיליון)?",
        r"(?i)\b(\d+(?:[.,]\d+)?)\s*(?:m|million|מיליון)\s*(?:€|£|\$|אירו|יורו|ליש\"?ט|דולר)?",
    )
    for pattern in amount_patterns:
        for match in re.finditer(pattern, text):
            try:
                amount = float(match.group(1).replace(",", "."))
            except Exception:
                continue
            if 0 < amount < MIN_TRANSFER_FEE_MILLIONS_TO_SEND:
                return True
    return False


def is_minor_destination_from_big_club_source(post: Post) -> bool:
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    if not cleaned:
        return False
    big_source_names = r"(?:Inter|AS Roma|Roma|Juventus|AC Milan|Milan|Chelsea|Manchester City|Man City|Manchester United|Man United|Barcelona|Real Madrid)"
    big_hebrew_source_names = r"(?:אינטר|רומא|AS רומא|יובנטוס|מילאן|צ'לסי|מנצ'סטר סיטי|מנצ'סטר יונייטד|ברצלונה|ריאל מדריד)"
    lower_destination_queries_big_source = (
        re.search(
            rf"\b(?!{big_source_names}\b)[A-Z][A-Za-zÀ-ÿ'’.-]{{2,}}(?:\s+[A-Z][A-Za-zÀ-ÿ'’.-]{{2,}}){{0,2}}\s+(?:have|has)?\s*(?:asked|requested|want(?:s)?|seek(?:s)?|opened talks with|approached)\s+{big_source_names}\b",
            cleaned,
            re.IGNORECASE,
        )
        or re.search(
            rf"(?:ביקשו|ביקשה|מבקשת|מבקשים|פנו|פנתה|פתחו\s+שיחות).{{0,120}}מ{big_hebrew_source_names}",
            cleaned,
            re.IGNORECASE,
        )
    )
    big_club_querying_source = re.search(
        rf"(?:{big_source_names}|{big_hebrew_source_names}).{{0,100}}(?:asked|requested|want(?:s)?|seek(?:s)?|opened talks with|approached|ביקשו|ביקשה|מבקשת|מבקשים|פנו|פנתה|פתחו\s+שיחות).{{0,100}}(?:{big_source_names}|מ{big_hebrew_source_names})",
        cleaned,
        re.IGNORECASE,
    )
    if lower_destination_queries_big_source and not big_club_querying_source:
        return True
    if has_big_club_as_main_buyer(cleaned):
        return False
    source_big_club = re.search(
        r"\bfrom\s+(?:Inter|AS Roma|Roma|Juventus|AC Milan|Milan|Chelsea|Manchester City|Man City|Manchester United|Man United|Barcelona|Real Madrid)\b|"
        r"מ(?:אינטר|רומא|AS רומא|יובנטוס|מילאן|צ'לסי|מנצ'סטר סיטי|מנצ'סטר יונייטד|ברצלונה|ריאל מדריד)",
        cleaned,
        re.IGNORECASE,
    )
    weak_destination_action = re.search(
        r"\b(?:asked|requested|want(?:s)?|loan|on loan|signs? for|joins?|lands? at|to)\b|"
        r"ביקשו|מבקשת|מעוניינת|בהשאלה|מושאל|חתם\s+ב|נחת\s+ב|לספסל\s+של|ל(?:-|\s)?[א-תA-Za-z]",
        cleaned,
        re.IGNORECASE,
    )
    return bool(source_big_club and weak_destination_action)


def is_media_without_report_post(post: Post) -> bool:
    raw = html.unescape("\n".join([post.text or "", post.quoted_text or ""]))
    cleaned = clean_for_ai_translation(raw)
    if not cleaned:
        return False
    if _matches_any(MATCH_NEWS_RESCUE_PATTERNS, cleaned) or has_news_action_signal(post):
        return False
    tokens = _news_duplicate_tokens(_news_duplicate_clean_text(post)) if "_news_duplicate_tokens" in globals() else set(re.findall(r"\w+", cleaned))
    has_media = bool(post.image_urls or post.has_video or _matches_any(MEDIA_ONLY_OR_PROMO_PATTERNS, cleaned) or has_linkish_text(raw))
    return bool(has_media and len(tokens) <= 7)


def is_name_without_news_action_post(post: Post) -> bool:
    if not primary_text_has_clear_subject(post):
        return False
    if has_news_action_signal(post):
        return False
    cleaned = clean_for_ai_translation(html.unescape(post.text or ""))
    tokens = _news_duplicate_tokens(cleaned)
    return bool(len(tokens) <= 8 or _matches_any(AUDIENCE_OR_QUESTION_PATTERNS, cleaned))


def is_too_short_without_strong_news_post(post: Post) -> bool:
    cleaned = clean_for_ai_translation(html.unescape(post.text or ""))
    tokens = _news_duplicate_tokens(_news_duplicate_clean_text(clone_post_with_text(post, cleaned)))
    if len(tokens) >= 5:
        return False
    if primary_text_has_clear_subject(post) and (
        _matches_any(STRONG_PLAYER_MOVE_PATTERNS, cleaned)
        or (_matches_any(FINAL_OR_NEAR_FINAL_PATTERNS, cleaned) and has_news_action_signal(post))
    ):
        return False
    return bool(len(tokens) <= 4)


def is_unclear_main_club_context_post(post: Post) -> bool:
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    if not cleaned or has_big_club_as_main_buyer(cleaned):
        return False
    if not (_matches_any(FINAL_ONLY_ALLOWED_CLUB_PATTERNS, cleaned) and _matches_any(BIG_CLUB_RUMOR_PATTERNS, cleaned)):
        return False
    weak_big_context = _matches_any(LOW_INTEREST_STAY_RENEWAL_PATTERNS, cleaned) or re.search(
        r"\b(?:were interested|had interest|previously interested|wanted him before|monitored)\b|"
        r"התעניינ[וה]|התעניינה בעבר|רצו בעבר|עקבו בעבר",
        cleaned,
        re.IGNORECASE,
    )
    return bool(weak_big_context)


def is_weak_copy_without_primary_value_post(post: Post) -> bool:
    cleaned = clean_for_ai_translation(html.unescape(post.text or ""))
    if _matches_any(STRONG_PLAYER_MOVE_PATTERNS, cleaned):
        return False
    return bool(re.search(r"\b(?:as reported|as revealed|as told|confirmed since|verified since|no surprise|nothing new)\b|כפי שדווח|כפי שנחשף|מאומת מאז|אין הפתעות|לא חדש", cleaned, re.IGNORECASE))


def is_writer_profile_noise_post(post: Post) -> bool:
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    username = (post.username or "").lower()
    if has_news_action_signal(post) and primary_text_has_clear_subject(post):
        return False
    if username in {"gerardromero", "jijantesfc"}:
        return bool(re.search(r"\b(?:directo|twitch|youtube|live|min\s?\d+|gol|goooo+l|pam!|watchalong)\b|לייב|יוטיוב|דקה\s?\d+|גול", cleaned, re.IGNORECASE))
    if username in {"jfelixdiaz", "jlsanchez78"}:
        return bool(re.search(r"\b(?:opinion|entrevista|interview|top interview|inmorales|debate|chiringuito|asked|thoughts)\b|ראיון|דעה|ויכוח|נשאל|מה דעתכם", cleaned, re.IGNORECASE))
    if username in {"nicoschira", "plettigoal"}:
        noise_cleaned = remove_writer_noise_for_event_matching(cleaned)
        return bool(len(_news_duplicate_tokens(noise_cleaned)) <= 4 and not has_news_action_signal(clone_post_with_text(post, noise_cleaned)))
    return False


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
    r"\b(?:Real Madrid|Barcelona|Barca|Barça|Atletico Madrid|Atlético Madrid|Sevilla|Valencia|Villarreal|Real Sociedad|Athletic Club|Athletic Bilbao|Real Betis|Girona|Celta Vigo|Getafe|Osasuna|Mallorca|Rayo Vallecano|Alaves|Espanyol|Levante|Malaga|Málaga|Racing Santander|Leganes|Granada|Las Palmas|Valladolid)\b",
    r"\b(?:Juventus|Inter Milan|Inter|AC Milan|Milan|Napoli|Roma|Lazio|Atalanta|Fiorentina|Torino|Bologna|Genoa|Cagliari|Como|Lecce|Udinese|Sassuolo|Verona|Parma|Pisa|Cremonese)\b",
    r"\b(?:Bayern Munich|Bayern|Borussia Dortmund|Dortmund|Bayer Leverkusen|Leverkusen|Eintracht Frankfurt|Mainz|Freiburg|Wolfsburg|Union Berlin|Hoffenheim|Werder Bremen|Hamburg|Koln|Köln|St Pauli|Heidenheim|Bochum)\b",
    r"\b(?:PSG|Paris Saint-Germain|Marseille|Monaco|Lyon|Lille|Nice|Lens|Strasbourg|Toulouse|Metz|Auxerre|Angers|Lorient|Paris FC)\b",
    r"ריאל מדריד|ברצלונה|בארסה|אתלטיקו מדריד|מנצ'סטר יונייטד|מנצ'סטר סיטי|ליברפול|ארסנל|צ'לסי|טוטנהאם|ניוקאסל|אסטון וילה|ווסטהאם|ברייטון|אברטון|לסטר|קריסטל פאלאס|וולבס|פולהאם|בורנמות|ברנטפורד|נוטינגהאם|לידס|סנדרלנד|ברנלי",
    r"יובנטוס|אינטר|מילאן|נאפולי|רומא|לאציו|אטאלנטה|פיורנטינה|טורינו|בולוניה|גנואה|קליארי|קומו|לצ'ה|אודינזה|ססואולו|ורונה|פארמה|פיזה|קרמונזה",
    r"באיירן|דורטמונד|לברקוזן|פרנקפורט|מיינץ|פרייבורג|וולפסבורג|אוניון ברלין|הופנהיים|ורדר ברמן|המבורג|קלן|סט פאולי|בוכום",
    r"פ\.ס\.ז|פריז סן ז'רמן|מארסיי|מונאקו|ליון|ליל|ניס|לאנס|שטרסבורג|טולוז|מץ|אוקזר|אנז'ה|לוריין",
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
    r"\b(?:said|told|speaking|spoke)\s+(?:to|with)\s+(?:El\s+Mundo|Marca|AS|COPE|SER|L'Equipe|LEquipe|Sky|ESPN|TNT|DAZN|BBC|The\s+Athletic|Telegraph|Guardian|MailSport)\b",
    r"\b(?:on|via)\s+[A-Z][A-Za-z0-9_.-]{2,}(?:\s+[A-Z][A-Za-z0-9_.-]{2,}){0,3}\s*:",
    r"(?is)[\"“”][^\"“”\n]{5,260}[\"“”].{0,400}[\"“”][^\"“”\n]{5,260}[\"“”]",
    r"ראיון|בראיון|מסיבת\s+עיתונאים|אזור\s+מעורב|דיבר\s+עם|נשאל\s+על|נשאלה\s+על",
    r"(?:אמר|אמרה|אמרו)\s+ל-?@?[A-Za-z0-9_]{3,40}",
    r"(?m)^\s*[א-ת][א-ת'״\".-]+(?:\s+[א-ת][א-ת'״\".-]+){0,5}\s+על\s+[^:\n]{2,120}:\s*[\"“”]",
)

QUOTE_INTERVIEW_FORMAT_PATTERNS = (
    r"(?m)^\s*(?:[A-Z][A-Za-zÀ-ÿ'’.-]+(?:\s+[A-Z][A-Za-zÀ-ÿ'’.-]+){0,5}|@[A-Za-z0-9_]{2,})\s*:\s*[\"“”'‘’]",
    r"\b(?:why choose|why choosing|what about|how do you define|your thoughts on)\b",
    r"\b(?:mystique|unpredictable|comebacks?|historic comebacks?|admire|idol|dream club)\b",
    r"(?m)^\s*(?:[א-ת][א-ת'״\".-]+(?:\s+[א-ת][א-ת'״\".-]+){0,5})\s*:\s*[\"“”'‘’]",
    r"למה\s+לבחור|איך\s+להגדיר|מה\s+דעתך|מיסטיקה|בלתי\s+צפוי|קאמבקים|מעריץ|מועדון\s+חלומות",
)


def is_interview_post(post: Post) -> bool:
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    if not cleaned:
        return False
    if _matches_any(INTERVIEW_BLOCK_PATTERNS, cleaned):
        return True
    if _matches_any(QUOTE_INTERVIEW_FORMAT_PATTERNS, cleaned) and not has_real_transfer_context(cleaned):
        return True
    return False


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
RECENT_NEWS_WINDOW_SECONDS = 12 * 60 * 60
CHANNEL_RECENT_NEWS_STATE_KEY = "__channel_recent_news_events__"
CHANNEL_RECENT_NEWS_WINDOW_SECONDS = 12 * 60 * 60
BOT_SENT_REPLY_STATE_KEY = "__bot_sent_reply_targets__"
BOT_SENT_REPLY_WINDOW_SECONDS = int(os.environ.get("BOT_SENT_REPLY_WINDOW_SECONDS", str(12 * 60 * 60)))
BOT_SENT_REPLY_MAX_ITEMS = int(os.environ.get("BOT_SENT_REPLY_MAX_ITEMS", "250"))
CHANNEL_REPLY_CERTAIN_MIN_SCORE = float(os.environ.get("CHANNEL_REPLY_CERTAIN_MIN_SCORE", "0.58"))
NEWS_BURST_SPAM_WINDOW_SECONDS = int(os.environ.get("NEWS_BURST_SPAM_WINDOW_SECONDS", str(10 * 60)))
NEWS_BURST_SPAM_MIN_EVENTS = int(os.environ.get("NEWS_BURST_SPAM_MIN_EVENTS", "5"))

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
SKIP_SUMMARY_LOG_SECONDS = int(os.environ.get("SKIP_SUMMARY_LOG_SECONDS", "60"))
SKIP_SUMMARY_LAST_LOGGED_AT = 0.0
SKIP_SUMMARY_COUNTS: dict[str, dict[str, Any]] = {}
ACCOUNT_SCAN_SUMMARY_ENABLED = os.environ.get("ACCOUNT_SCAN_SUMMARY_ENABLED", "0") == "1"
ACCOUNT_SCAN_SUMMARY_ON_STARTUP = os.environ.get("ACCOUNT_SCAN_SUMMARY_ON_STARTUP", "1") == "1"
ACCOUNT_SCAN_SUMMARY_SECONDS = int(os.environ.get("ACCOUNT_SCAN_SUMMARY_SECONDS", str(15 * 60)))
ACCOUNT_STALE_LATEST_SECONDS = int(os.environ.get("ACCOUNT_STALE_LATEST_SECONDS", str(6 * 60 * 60)))
ACCOUNT_SCAN_SUMMARY_LAST_LOGGED_AT = 0.0
ACCOUNT_SCAN_SUMMARY: dict[str, dict[str, Any]] = {}

BLOCK_REASON_HEBREW = {
    "old_post": "פוסט ישן מדי",
    "women_or_wnba": "תוכן נשים/WNBA",
    "medical_staff": "דיווח על צוות רפואי",
    "other_sport": "ענף ספורט אחר",
    "youth_or_academy": "נוער/אקדמיה",
    "interview_blocked": "ראיון או ציטוט בלי חדשות העברה",
    "contextless_teaser": "הודעת רמז בלי מידע ברור",
    "vague_status_without_primary_context": "עדכון סטטוס בלי שם/קבוצה ברורים",
    "unclear_subject_news": "דיווח בלי שם/קבוצה ברורים",
    "live_goal_or_match_moment": "עדכון שער או מהלך משחק",
    "match_result_or_engagement": "תוצאה/שאלת מעורבות/עדכון משחק",
    "lineup_or_teamsheet": "הרכבים/הרכב רשמי",
    "poll_or_audience": "סקר/הצבעת קהל",
    "world_cup_bracket_noise": "דיווח מונדיאל סתמי",
    "final_only_club_not_strict_final": "קבוצת דרג ב שמותרת רק בדיווח סופי",
    "tier3_weak_interest": "דרג ג עם התעניינות חלשה",
    "tier3_not_final_enough": "דרג ג דורש דיווח סופי וברור",
    "lower_tier_staff_or_coach_noise": "מאמן/צוות בדרג נמוך לא מספיק חשוב",
    "strict_writer_not_strong_enough": "כתב קשוח: הדיווח לא מספיק חזק",
    "strict_writer_staff_or_coach_noise": "כתב קשוח: דיווח צוות/מאמן לא מספיק חשוב",
    "untracked_destination_club": "יעד המעבר לא נמצא בדרגים",
    "non_elite_loose_transfer_talk": "שמועה/שיחות לקבוצה לא-עלית בלי התקדמות ממשית",
    "minor_destination_from_big_club": "יעד קטן דרך קבוצה גדולה",
    "small_transfer_fee": "עסקה קטנה מתחת לרף",
    "admin_or_backroom_only_barca_real_allowed": "דיווח ניהולי שלא קשור לריאל/ברצלונה",
    "low_interest_stay_renewal": "הישארות/חידוש חוזה לא מספיק מעניין",
    "low_interest_non_europe_contract": "חוזה בליגה לא מספיק מעניינת",
    "low_interest_german_destination": "יעד גרמני לא מספיק מעניין",
    "low_interest_german_update_not_enough": "עדכון גרמני לא מספיק חשוב",
    "minor_or_unclear_injury_not_enough": "פציעה/כשירות לא מספיק חשובה",
    "low_interest_club_strong_move_not_enough": "מעבר בקבוצה לא מספיק מעניינת",
    "vague_big_club_player_idea_without_real_rumour": "רעיון שחקן בלי דיווח אמיתי",
    "match_context_noise": "ספאם סביב משחק/נבחרת בלי חדשות",
    "name_without_news_action": "שם בלי פעולה חדשותית ברורה",
    "media_without_report": "תמונה/וידאו בלי דיווח",
    "too_short_without_strong_news": "הודעה קצרה מדי בלי דיווח חזק",
    "unclear_main_club_context": "לא ברור מי עיקר הדיווח",
    "weak_copy_without_primary_value": "דיווח ממוחזר בלי ערך חדש",
    "burst_spam": "עומס דיווחים על אותו נושא",
    "writer_profile_noise": "רעש אופייני לכתב",
    "temporary_elite_only_mode": "מצב זמני רק גדולות",
    "temporary_strict_filter_mode": "מצב זמני סינון קשוח",
    "temporary_night_mode": "מצב לילה",
    "low_importance": "חשיבות נמוכה",
    "not_connected_to_tracked_club": "לא קשור לקבוצה במעקב",
    "untracked_transfer_or_staff_news": "דיווח העברה/מאמן בלי קבוצה במעקב",
    "non_news_social": "פוסט חברתי/לא חדשותי",
    "official_on_minor": "דיווח רשמי על קבוצה פחות חשובה",
    "media_only": "תמונה/וידאו בלי דיווח חדשותי",
    "duplicate": "כפילות",
    "semantic_duplicate": "כפילות תוכן",
    "recent_duplicate": "כפילות מהזמן האחרון",
    "translation_unavailable": "תרגום לא זמין",
    "send_failed": "כשל בשליחה",
    "control_block_rumors": "סינון כפתור: שמועות כבויות",
    "control_block_national": "סינון כפתור: נבחרות כבויות",
    "control_block_injuries": "סינון כפתור: פציעות כבויות",
    "control_block_social": "סינון כפתור: פוסטים חברתיים כבויים",
    "control_only_herewego": "סינון כפתור: רק Here We Go",
    "control_only_top5": "סינון כפתור: רק טופ 5 ליגות",
    "control_only_real_barca": "סינון כפתור: רק ריאל וברצלונה",
}


def hebrew_block_reason(reason: str) -> str:
    base = (reason or "").split(";", 1)[0].strip()
    if base.startswith("importance:"):
        base = base.split(":", 1)[1]
    translated = BLOCK_REASON_HEBREW.get(base)
    if translated:
        return translated
    # נפילה בטוחה: שלא יופיעו בקבוצת השליטה קודי מערכת באנגלית עם קו תחתון.
    if re.fullmatch(r"[A-Za-z0-9_:-]+", base or ""):
        clean = base.replace("_", " ").replace(":", " - ").strip()
        return f"סיבת מערכת: {clean}" if clean else "סיבה לא ידועה"
    return base or "סיבה לא ידועה"


def remember_control_block_event(reason: str, post: "Post", rendered: str, duplicate: bool = False) -> None:
    try:
        # בזמן 30 הדקות הראשונות אחרי שהבוט עולה, RSS יכול להחזיר הרבה פוסטים ישנים.
        # אותם לא שומרים בכפתור "למה לא נשלח", כדי שלא ידחקו 5 חסימות אמיתיות.
        # אחרי חלון ההפעלה הראשוני כן מדווחים על "פוסט ישן מדי" כרגיל.
        base_reason = (reason or "").split(";", 1)[0].strip()
        if (
            base_reason == "old_post"
            and SUPPRESS_STARTUP_OLD_POST_BLOCK_REPORT_SECONDS > 0
            and time.time() - BOT_STARTED_AT < SUPPRESS_STARTUP_OLD_POST_BLOCK_REPORT_SECONDS
        ):
            return

        state = load_control_state()
        item = {
            "ts": time.time(),
            "source": getattr(post, "username", "unknown") or "unknown",
            "reason": hebrew_block_reason(reason),
            "preview": filtered_post_text_preview(post),
            "link": getattr(post, "link", "") or "",
        }
        blocked = state.get("last_blocked_posts", [])
        if not isinstance(blocked, list):
            blocked = []
        blocked = [existing for existing in blocked if isinstance(existing, dict)]
        blocked.append(item)
        state["last_blocked_posts"] = blocked[-5:]
        if duplicate:
            duplicates = state.get("last_duplicate_posts", [])
            if not isinstance(duplicates, list):
                duplicates = []
            duplicates.append(item)
            state["last_duplicate_posts"] = duplicates[-5:]
        path = control_state_path()
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(path)
    except Exception as exc:
        logging.debug("שמירת חסימה אחרונה ללוח השליטה נכשלה: %s", exc)


def log_skip_once(reason: str, post: "Post", message: str, *args: Any) -> None:
    key = hashlib.sha1(f"{reason}|{post.link or post.post_id}".encode("utf-8", errors="ignore")).hexdigest()
    if key in LOGGED_SKIP_KEYS:
        return
    LOGGED_SKIP_KEYS.add(key)
    if len(LOGGED_SKIP_KEYS) > 2000:
        LOGGED_SKIP_KEYS.clear()
    age_seconds = max(0.0, time.time() - post.published_ts) if getattr(post, "published_ts", 0.0) else 0.0
    source_name = getattr(post, "source_name", "unknown") or "unknown"
    rendered = (message % args) if args else message
    logging.debug("↩️ " + rendered + " | מקור: %s | גיל: %.0fs", source_name, age_seconds)
    record_skip_summary(reason, post, rendered, source_name, age_seconds)
    remember_control_block_event(reason, post, rendered, duplicate=("duplicate" in reason or "כפילות" in rendered))


def daily_quality_stats_path() -> Path:
    return app_data_path(DAILY_QUALITY_STATS_FILE)


def load_daily_quality_stats_from_disk() -> None:
    global DAILY_QUALITY_STATS_LOADED
    if DAILY_QUALITY_STATS_LOADED:
        return
    DAILY_QUALITY_STATS_LOADED = True
    path = daily_quality_stats_path()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            DAILY_QUALITY_STATS.clear()
            DAILY_QUALITY_STATS.update(data)
    except Exception as exc:
        logging.warning("⚠️ לא הצלחתי לקרוא את קובץ הזיכרון של הדוח היומי: %s", exc)


def save_daily_quality_stats_to_disk(force: bool = False) -> None:
    global DAILY_QUALITY_STATS_LAST_SAVE_AT
    if not DAILY_QUALITY_STATS:
        return
    now = time.time()
    if not force and now - DAILY_QUALITY_STATS_LAST_SAVE_AT < DAILY_QUALITY_STATS_SAVE_EVERY_SECONDS:
        return
    DAILY_QUALITY_STATS_LAST_SAVE_AT = now
    try:
        path = daily_quality_stats_path()
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(DAILY_QUALITY_STATS, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)
    except Exception as exc:
        logging.debug("שמירת זיכרון הדוח היומי נכשלה: %s", exc)


def _empty_daily_quality_bucket(today: str) -> dict[str, Any]:
    return {
        "date": today,
        "scanned": {},
        "fetched": {},
        "fetched_recent_24h": {},
        "new": {},
        "sent": {},
        "skips": {},
        "skip_reasons": {},
        "gemini_failures": {},
        "timings": {},
        "post_lengths": {},
    }


def _daily_stats_bucket() -> dict[str, Any]:
    load_daily_quality_stats_from_disk()
    today = datetime.now(ZoneInfo(SHABBAT_TIMEZONE)).strftime("%Y-%m-%d")
    if DAILY_QUALITY_STATS.get("date") != today:
        DAILY_QUALITY_STATS.clear()
        DAILY_QUALITY_STATS.update(_empty_daily_quality_bucket(today))
        save_daily_quality_stats_to_disk(force=True)
    return DAILY_QUALITY_STATS


def daily_stat_increment(section: str, key: str, amount: int = 1) -> None:
    bucket = _daily_stats_bucket()
    table = bucket.setdefault(section, {})
    if not isinstance(table, dict):
        table = {}
        bucket[section] = table
    table[key] = int(table.get(key, 0) or 0) + amount
    save_daily_quality_stats_to_disk(force=False)


def daily_stat_set(section: str, key: str, value: int) -> None:
    bucket = _daily_stats_bucket()
    table = bucket.setdefault(section, {})
    if not isinstance(table, dict):
        table = {}
        bucket[section] = table
    table[key] = int(value or 0)
    save_daily_quality_stats_to_disk(force=False)


def daily_stat_replace_table(section: str, values: dict[str, int]) -> None:
    bucket = _daily_stats_bucket()
    bucket[section] = {str(key): int(value or 0) for key, value in values.items()}
    save_daily_quality_stats_to_disk(force=False)


def daily_stat_add_timing(metric: str, seconds: float) -> None:
    if seconds < 0:
        return
    bucket = _daily_stats_bucket()
    timings = bucket.setdefault("timings", {})
    if not isinstance(timings, dict):
        timings = {}
        bucket["timings"] = timings
    item = timings.setdefault(metric, {"count": 0, "total_seconds": 0.0, "max_seconds": 0.0})
    if not isinstance(item, dict):
        item = {"count": 0, "total_seconds": 0.0, "max_seconds": 0.0}
        timings[metric] = item
    item["count"] = int(item.get("count", 0) or 0) + 1
    item["total_seconds"] = float(item.get("total_seconds", 0.0) or 0.0) + float(seconds)
    item["max_seconds"] = max(float(item.get("max_seconds", 0.0) or 0.0), float(seconds))
    save_daily_quality_stats_to_disk(force=False)


def daily_stat_average_seconds(metric: str) -> tuple[float, int, float]:
    bucket = _daily_stats_bucket()
    timings = bucket.get("timings", {})
    if not isinstance(timings, dict):
        return 0.0, 0, 0.0
    item = timings.get(metric, {})
    if not isinstance(item, dict):
        return 0.0, 0, 0.0
    count = int(item.get("count", 0) or 0)
    total = float(item.get("total_seconds", 0.0) or 0.0)
    max_seconds = float(item.get("max_seconds", 0.0) or 0.0)
    return (total / count if count else 0.0), count, max_seconds


def daily_stat_record_post_length(username: str, link: str, text: str) -> None:
    cleaned = re.sub(r"\s+", " ", html.unescape(text or "")).strip()
    length = len(cleaned)
    if length <= 0:
        return
    bucket = _daily_stats_bucket()
    lengths = bucket.setdefault("post_lengths", {})
    if not isinstance(lengths, dict):
        lengths = {}
        bucket["post_lengths"] = lengths
    preview = trim(cleaned, 220) if "trim" in globals() else cleaned[:220]
    item = {"username": username, "link": link, "length": length, "preview": preview, "ts": time.time()}
    longest = lengths.get("longest")
    shortest = lengths.get("shortest")
    if not isinstance(longest, dict) or length > int(longest.get("length", 0) or 0):
        lengths["longest"] = item
    if not isinstance(shortest, dict) or length < int(shortest.get("length", 10**9) or 10**9):
        lengths["shortest"] = item
    save_daily_quality_stats_to_disk(force=False)


def daily_stat_post_length_text(kind: str) -> str:
    bucket = _daily_stats_bucket()
    lengths = bucket.get("post_lengths", {})
    if not isinstance(lengths, dict):
        lengths = {}
    key = "longest" if kind == "longest_post" else "shortest"
    item = lengths.get(key)
    title = "📚 הפוסט הארוך ביותר היום" if kind == "longest_post" else "✂️ הפוסט הקצר ביותר היום"
    if not isinstance(item, dict):
        return f"{title}\n\nעדיין לא נשמר פוסט שנשלח היום."
    ts = float(item.get("ts", 0.0) or 0.0)
    when = datetime.fromtimestamp(ts, ZoneInfo(SHABBAT_TIMEZONE)).strftime("%H:%M") if ts else "לא ידוע"
    return (
        f"{title}\n\n"
        f"כתב: {_hebrew_account_label(str(item.get('username', '')))}\n"
        f"אורך: {int(item.get('length', 0) or 0)} תווים\n"
        f"שעה: {when}\n"
        f"תקציר: {item.get('preview', '')}\n"
        f"קישור: {item.get('link', '')}"
    )


def daily_stat_skip(username: str, reason_he: str) -> None:
    daily_stat_increment("skips", username, 1)
    daily_stat_increment("skip_reasons", reason_he, 1)


def record_skip_summary(reason: str, post: "Post", rendered: str, source_name: str, age_seconds: float) -> None:
    source = getattr(post, "username", "unknown") or "unknown"
    base_reason = hebrew_block_reason(reason)
    daily_stat_skip(source, base_reason)
    daily_stat_increment("skip_by_writer_reason", f"{source}|{base_reason}", 1)
    if source in EXTRA_STRICT_SOURCE_ACCOUNTS:
        daily_stat_increment("strict_writer_blocks", base_reason, 1)
    key = f"{source}|{base_reason}"
    item = SKIP_SUMMARY_COUNTS.setdefault(
        key,
        {
            "count": 0,
            "source": source,
            "reason": base_reason,
            "latest": "",
            "rss": source_name,
            "age_seconds": age_seconds,
        },
    )
    item["count"] = int(item.get("count", 0) or 0) + 1
    item["latest"] = trim(rendered, 220) if "trim" in globals() else rendered[:220]
    item["rss"] = source_name
    item["age_seconds"] = age_seconds


def flush_skip_summary(force: bool = False) -> None:
    global SKIP_SUMMARY_LAST_LOGGED_AT
    if not SKIP_SUMMARY_COUNTS:
        return
    now = time.time()
    if not force and now - SKIP_SUMMARY_LAST_LOGGED_AT < SKIP_SUMMARY_LOG_SECONDS:
        return
    SKIP_SUMMARY_LAST_LOGGED_AT = now
    items = sorted(SKIP_SUMMARY_COUNTS.values(), key=lambda item: int(item.get("count", 0) or 0), reverse=True)
    parts = []
    for item in items[:12]:
        parts.append(
            f"@{item.get('source', 'unknown')}: {item.get('count', 0)}x {item.get('reason', 'סיבה לא ידועה')}"
        )
    logging.info("↩️ סיכום דילוגים בדקה האחרונה: %s", " | ".join(parts))
    for item in items[:5]:
        logging.debug(
            "↩️ פירוט דילוג לדוגמה: @%s | %s | מקור: %s | גיל: %.0fs | %s",
            item.get("source", "unknown"),
            item.get("reason", "סיבה לא ידועה"),
            item.get("rss", "unknown"),
            float(item.get("age_seconds", 0.0) or 0.0),
            item.get("latest", ""),
        )
    SKIP_SUMMARY_COUNTS.clear()


def _top_daily_items(section: str, limit: int = 5) -> list[tuple[str, int]]:
    bucket = _daily_stats_bucket()
    table = bucket.get(section, {})
    if not isinstance(table, dict):
        return []
    return sorted(((str(key), int(value or 0)) for key, value in table.items()), key=lambda item: item[1], reverse=True)[:limit]


def _hebrew_account_label(username: str) -> str:
    if not username:
        return "כתב לא ידוע"
    return ACCOUNT_DISPLAY_NAMES.get(username, OPTIONAL_CONTROLLED_ACCOUNT_LABELS.get(username, CONTROLLED_BASE_ACCOUNT_LABELS.get(username, username)))


def skip_reason_category_he(reason: str) -> str:
    reason = reason or ""
    if any(token in reason for token in ("כפילות", "עומס דיווחים")):
        return "כפילויות ועומס"
    if any(token in reason for token in ("משחק", "שער", "תוצאה", "נבחרת", "סביבת משחק")):
        return "משחקים ונבחרות"
    if any(token in reason for token in ("חשיבות", "דרג", "קבוצה", "לא מספיק", "מועדון", "ליגה")):
        return "חשיבות וקבוצות"
    if any(token in reason for token in ("ראיון", "ציטוט", "פודקאסט", "תוכן", "סטטיסטיקה", "רעש")):
        return "תוכן לא חדשותי"
    if any(token in reason for token in ("תמונה", "וידאו", "קישור", "קצרה", "רמז", "ברור")):
        return "איכות/בהירות ההודעה"
    if any(token in reason for token in ("נשים", "WNBA", "נוער", "אקדמיה", "צוות רפואי", "ספורט אחר")):
        return "סינון תחום"
    if any(token in reason for token in ("מצב זמני", "מצב לילה")):
        return "מצבים זמניים"
    return "אחר"


def display_skip_reason_he(reason: str) -> str:
    text = str(reason or "").strip()
    lowered = text.lower()
    replacements = {
        "top5 club but no transfer or coach context": "קבוצת טופ 5, אבל בלי הקשר העברה או מאמן",
        "not connected to tracked club": "לא קשור לקבוצה במעקב",
        "final only club not strict final": "קבוצת דרג ב בלי דיווח סופי מספיק",
        "low interest club strong move not enough": "קבוצה פחות חשובה בלי דיווח חזק מספיק",
    }
    for source, target in replacements.items():
        if source in lowered:
            return target
    if re.search(r"[A-Za-z]", text):
        text = text.replace("_", " ")
        text = re.sub(r"\btop5\b", "טופ 5", text, flags=re.IGNORECASE)
        text = re.sub(r"\bclub\b", "קבוצה", text, flags=re.IGNORECASE)
        text = re.sub(r"\btransfer\b", "העברה", text, flags=re.IGNORECASE)
        text = re.sub(r"\bcoach\b", "מאמן", text, flags=re.IGNORECASE)
        text = re.sub(r"\bcontext\b", "הקשר", text, flags=re.IGNORECASE)
        text = re.sub(r"\bduplicate\b", "כפילות", text, flags=re.IGNORECASE)
    return text


def grouped_skip_reason_lines(limit_per_category: int = 4) -> list[str]:
    reason_items = _top_daily_items("skip_reasons", 1000)
    if not reason_items:
        return ["- אין חסימות שנרשמו מאז ההפעלה"]
    grouped: dict[str, list[tuple[str, int]]] = {}
    for reason, count in reason_items:
        reason_he = display_skip_reason_he(reason)
        grouped.setdefault(skip_reason_category_he(reason_he), []).append((reason_he, count))
    lines: list[str] = []
    for category, items in sorted(grouped.items(), key=lambda item: -sum(count for _reason, count in item[1])):
        total = sum(count for _reason, count in items)
        lines.append(f"{category}: {total}")
        for reason, count in items[:limit_per_category]:
            lines.append(f"- {reason}: {count}")
    return lines


def build_daily_quality_report_text() -> str:
    bucket = _daily_stats_bucket()
    sent_total = sum(count for _key, count in _top_daily_items("sent", 1000))
    skipped_total = sum(count for _key, count in _top_daily_items("skips", 1000))
    recent_snapshot = live_recent_snapshot_from_rss()
    if not isinstance(recent_snapshot, dict) or not recent_snapshot:
        recent_snapshot = bucket.get("fetched_recent_24h", {})
    fetched_total = sum(int(value or 0) for value in (recent_snapshot or {}).values()) if isinstance(recent_snapshot, dict) else 0
    new_total = sum(count for _key, count in _top_daily_items("new", 1000))
    scanned_total = sum(count for _key, count in _top_daily_items("scanned", 1000))
    active_accounts_count = len(active_x_accounts())
    report_date = bucket.get("date") or datetime.now(ZoneInfo(SHABBAT_TIMEZONE)).strftime("%Y-%m-%d")
    avg_scan, scan_count, max_scan = daily_stat_average_seconds("scan_seconds")
    avg_translation, translation_count, max_translation = daily_stat_average_seconds("translation_seconds")

    lines = [
        "📊 דוח יומי - בוט כדורגל",
        "━━━━━━━━━━━━",
        f"📅 תאריך: {report_date}",
        "",
        "📌 תמונת מצב",
        "────────────",
        f"✅ הודעות שנשלחו: {sent_total}",
        f"👥 כתבים פעילים: {active_accounts_count}",
        f"🔎 סריקות כתבים שבוצעו: {scanned_total}",
        f"📥 פוסטים מהיממה האחרונה שנמצאו במקורות: {fetched_total}",
        f"🆕 פוסטים חדשים לפני סינון: {new_total}",
        f"↩️ פוסטים שנעצרו לפני תרגום/שליחה: {skipped_total}",
        f"⚡ זמן סריקה ממוצע: {avg_scan:.2f} שניות ({scan_count} מדידות, שיא {max_scan:.2f} שניות)",
        f"🧠 זמן תרגום ממוצע: {avg_translation:.2f} שניות ({translation_count} מדידות, שיא {max_translation:.2f} שניות)",
        "",
        "💰 חיסכון",
        "────────────",
        f"נחסכו בערך {skipped_total} פעולות תרגום/שליחה, כי הפוסטים נעצרו בסינון המוקדם.",
        "",
        "🧠 כתבים שמהם נשלחו הכי הרבה הודעות",
        "────────────",
    ]
    sent_items = _top_daily_items("sent", 5)
    if sent_items:
        for index, (username, count) in enumerate(sent_items, 1):
            lines.append(f"{index}. {_hebrew_account_label(username)} - {count} הודעות")
    else:
        lines.append("- לא נשלחו הודעות היום")

    lines.append("")
    lines.append("🧹 למה פוסטים לא נשלחו")
    lines.append("────────────")
    lines.extend(grouped_skip_reason_lines())
    lines.append("")
    lines.append("💾 הדוח נשמר בזיכרון מקומי, לכן הנתונים נשמרים גם אחרי הפעלה מחדש באותו שרת.")
    return "\n".join(lines)


def send_daily_quality_report_if_due() -> None:
    global DAILY_QUALITY_REPORT_LAST_DATE
    if not DAILY_QUALITY_REPORT_ENABLED or not CONTROL_CHAT_ID:
        return
    now_dt = datetime.now(ZoneInfo(SHABBAT_TIMEZONE))
    today = now_dt.strftime("%Y-%m-%d")
    if DAILY_QUALITY_REPORT_LAST_DATE == today:
        return
    if (now_dt.hour, now_dt.minute) < (DAILY_QUALITY_REPORT_HOUR, DAILY_QUALITY_REPORT_MINUTE):
        return
    try:
        send_control_text(build_daily_quality_report_text(), message.get("message_id"), quick_control_reply_markup())
        save_daily_quality_stats_to_disk(force=True)
        DAILY_QUALITY_REPORT_LAST_DATE = today
        logging.info("📊 דו\"ח יומי נשלח לערוץ השקט.")
    except Exception as exc:
        logging.warning("⚠️ שליחת דו\"ח יומי לערוץ השקט נכשלה: %s", exc)


def record_scan_cycle_summary(scanned: int, with_posts: int, fetched: int, new: int, candidates: int) -> None:
    SCAN_CYCLE_SUMMARY["cycles"] = int(SCAN_CYCLE_SUMMARY.get("cycles", 0) or 0) + 1
    SCAN_CYCLE_SUMMARY["scanned"] = int(SCAN_CYCLE_SUMMARY.get("scanned", 0) or 0) + scanned
    SCAN_CYCLE_SUMMARY["with_posts"] = int(SCAN_CYCLE_SUMMARY.get("with_posts", 0) or 0) + with_posts
    SCAN_CYCLE_SUMMARY["fetched"] = int(SCAN_CYCLE_SUMMARY.get("fetched", 0) or 0) + fetched
    SCAN_CYCLE_SUMMARY["new"] = int(SCAN_CYCLE_SUMMARY.get("new", 0) or 0) + new
    SCAN_CYCLE_SUMMARY["candidates"] = int(SCAN_CYCLE_SUMMARY.get("candidates", 0) or 0) + candidates


def flush_scan_cycle_summary(force: bool = False) -> None:
    global SCAN_CYCLE_SUMMARY_LAST_LOGGED_AT
    if not SCAN_CYCLE_SUMMARY:
        return
    now = time.time()
    if not force and now - SCAN_CYCLE_SUMMARY_LAST_LOGGED_AT < SCAN_CYCLE_SUMMARY_SECONDS:
        return
    SCAN_CYCLE_SUMMARY_LAST_LOGGED_AT = now
    logging.info(
        "🔎 סיכום סריקה: %s סבבים | כתבים פעילים: %s | בדיקות כתבים שבוצעו: %s | בדיקות עם פוסטים: %s | פוסטים שנמצאו: %s | חדשים לפני סינון: %s | מועמדים אחרי סינון: %s",
        SCAN_CYCLE_SUMMARY.get("cycles", 0),
        len(active_x_accounts()),
        SCAN_CYCLE_SUMMARY.get("scanned", 0),
        SCAN_CYCLE_SUMMARY.get("with_posts", 0),
        SCAN_CYCLE_SUMMARY.get("fetched", 0),
        SCAN_CYCLE_SUMMARY.get("new", 0),
        SCAN_CYCLE_SUMMARY.get("candidates", 0),
    )
    SCAN_CYCLE_SUMMARY.clear()


def record_account_scan_summary(username: str, posts: list["Post"], new_count: int) -> None:
    item = ACCOUNT_SCAN_SUMMARY.setdefault(username, {"scans": 0, "fetched": 0, "new": 0, "latest_age": None, "latest_source": ""})
    item["scans"] = int(item.get("scans", 0) or 0) + 1
    item["fetched"] = int(item.get("fetched", 0) or 0) + len(posts)
    item["new"] = int(item.get("new", 0) or 0) + new_count
    if posts:
        latest = posts[0]
        item["latest_age"] = max(0.0, time.time() - latest.published_ts) if latest.published_ts else None
        item["latest_source"] = latest.source_name


def flush_account_scan_summary(force: bool = False) -> None:
    global ACCOUNT_SCAN_SUMMARY_LAST_LOGGED_AT
    if not ACCOUNT_SCAN_SUMMARY:
        return
    if not (ACCOUNT_SCAN_SUMMARY_ENABLED or force):
        ACCOUNT_SCAN_SUMMARY.clear()
        return
    now = time.time()
    if not force and now - ACCOUNT_SCAN_SUMMARY_LAST_LOGGED_AT < ACCOUNT_SCAN_SUMMARY_SECONDS:
        return
    ACCOUNT_SCAN_SUMMARY_LAST_LOGGED_AT = now
    parts = []
    for username, item in sorted(ACCOUNT_SCAN_SUMMARY.items()):
        age_value = item.get("latest_age")
        if age_value is None:
            age_text = "אין פוסט"
        else:
            age_float = float(age_value)
            stale = " ⚠️ מקור ישן/תקוע" if age_float >= ACCOUNT_STALE_LATEST_SECONDS else ""
            age_text = f"אחרון לפני {age_float:.0f}s{stale}"
        parts.append(
            f"@{username}: {item.get('scans', 0)} סריקות, {item.get('fetched', 0)} נמצאו, {item.get('new', 0)} חדשים, {age_text}, מקור {item.get('latest_source') or 'לא ידוע'}"
        )
    logging.info("🔎 אבחון כתבים: %s", " | ".join(parts[:18]))
    ACCOUNT_SCAN_SUMMARY.clear()

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

NEWS_DUP_STOPWORDS.update(
    {
        "transfer", "transfers", "mercato", "calciomercato", "sky", "sport", "sports", "germany", "deutschland",
        "breaking", "exclusive", "update", "updates", "news", "via", "video", "watch", "live",
        "העברות", "העברה", "סקיי", "ספורט", "גרמניה", "חדשות", "עדכון", "וידאו", "וידיאו", "לייב",
    }
)


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


WRITER_NOISE_PATTERNS = (
    r"(?im)^\s*(?:#?(?:transfers?|mercato|calciomercato)|העברות)\s*$",
    r"(?im)^\s*(?:sky\s*sport(?:s)?\s*germany|sky\s*germany|skysportde|סקיי\s+ספורט\s+גרמניה)\s*$",
    r"(?im)\s+(?:#(?:transfers?|mercato|calciomercato)|העברות)\s*$",
    r"(?im)\s+(?:sky\s*sport(?:s)?\s*germany|sky\s*germany|skysportde|סקיי\s+ספורט\s+גרמניה)\s*$",
)


TRAILING_DUPLICATE_TAG_WORD_PATTERNS = (
    r"[A-Za-z][A-Za-z .'-]{2,35}",
    r"[א-ת][א-ת '׳\".-]{2,35}",
)


def remove_writer_noise_for_event_matching(text: str) -> str:
    cleaned = text or ""
    for pattern in WRITER_NOISE_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?<!\w)@[A-Za-z0-9_]{1,20}\s*$", " ", cleaned)
    cleaned = re.sub(r"(?:^|\s)#(?:transfers?|mercato|calciomercato)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?:^|\s)#?העברות\b", " ", cleaned)

    # Some writers, especially Nico Schira, append a bare team tag at the end:
    # "... sell-on clause. Tottenham". If the exact team tag already appears in
    # the report, remove only that trailing duplicate tag for matching purposes.
    for _ in range(3):
        stripped = cleaned.rstrip(" .,!?:;|/-–—\n\r\t")
        match = None
        for pattern in TRAILING_DUPLICATE_TAG_WORD_PATTERNS:
            candidate = re.search(rf"(?:^|\s)({pattern})\s*$", stripped)
            if candidate:
                match = candidate
                break
        if not match:
            break
        tag = re.sub(r"\s+", " ", match.group(1)).strip()
        if len(tag) < 3:
            break
        before = stripped[: match.start(1)]
        if re.search(r"(?<!\w)" + re.escape(tag) + r"(?!\w)", before, re.IGNORECASE):
            cleaned = before.rstrip()
            continue
        break
    return re.sub(r"\s+", " ", cleaned).strip()


def _news_duplicate_clean_text(post: Post) -> str:
    text = html.unescape("\n".join([post.text or "", post.quoted_text or ""]))
    text = normalize_country_flags(text) if "normalize_country_flags" in globals() else text
    text = remove_external_links(text)
    text = convert_hashtags_to_text(text)
    text = remove_writer_noise_for_event_matching(text)
    text = apply_handle_replacements(text)
    text = apply_phrase_replacements(text, TEAM_REPLACEMENTS)
    text = apply_phrase_replacements(text, PLAYER_REPLACEMENTS)
    text = remove_writer_noise_for_event_matching(text)
    text = re.sub(r"(?<!\w)@[A-Za-z0-9_]+", " ", text)
    text = re.sub(r"[🚨✅🔴⚪🟢🔵🟡⚫⭐️📌📍🗣🔥💣🏆🥇📈✍️]", " ", text)
    text = re.sub(r"[^A-Za-z0-9א-ת'׳\- ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def _normalize_news_duplicate_token(token: str) -> str:
    token = (token or "").strip("-'׳").lower()
    token = token.replace("'", "").replace("׳", "").replace("’", "")
    token = token.translate(str.maketrans({"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"}))
    if re.fullmatch(r"[א-ת][א-ת'׳\-]{3,}", token):
        stripped = re.sub(r"^[ובלה](?=[א-ת]{3,})", "", token, count=1)
        if len(stripped) >= 3:
            token = stripped
    return token


def _duplicate_hebrew_name_skeleton(token: str) -> str:
    token = _normalize_news_duplicate_token(token)
    if not re.search(r"[א-ת]", token):
        return ""
    skeleton = re.sub(r"[אהוי]", "", token)
    skeleton = re.sub(r"(.)\1+", r"\1", skeleton)
    return skeleton if len(skeleton) >= 4 else ""


def _duplicate_latin_name_skeleton(token: str) -> str:
    token = re.sub(r"[^a-z]", "", (token or "").lower())
    if len(token) < 5:
        return ""
    skeleton = re.sub(r"[aeiouy]", "", token)
    skeleton = re.sub(r"(.)\1+", r"\1", skeleton)
    return skeleton if len(skeleton) >= 4 else ""


def _duplicate_token_aliases(token: str) -> set[str]:
    aliases = {token}
    skeleton = _duplicate_hebrew_name_skeleton(token)
    if skeleton:
        aliases.add(skeleton)
    latin_skeleton = _duplicate_latin_name_skeleton(token)
    if latin_skeleton:
        aliases.add(latin_skeleton)
    if re.fullmatch(r"[A-Za-z][A-Za-z'’.-]{2,}", token or "") and "transliterate_word" in globals():
        try:
            transliterated = _normalize_news_duplicate_token(transliterate_word(token))
            if len(transliterated) >= 3:
                aliases.add(transliterated)
            transliterated_skeleton = _duplicate_hebrew_name_skeleton(transliterated)
            if transliterated_skeleton:
                aliases.add(transliterated_skeleton)
        except Exception:
            pass
    return aliases


def _news_duplicate_tokens(text: str) -> set[str]:
    raw_tokens = re.findall(r"[A-Za-zא-ת][A-Za-zא-ת'׳\-]{2,}|\d+", text or "")
    tokens: set[str] = set()
    for token in raw_tokens:
        token = _normalize_news_duplicate_token(token)
        if len(token) < 3 or token in NEWS_DUP_STOPWORDS:
            continue
        for alias in _duplicate_token_aliases(token):
            if len(alias) >= 3 and alias not in NEWS_DUP_STOPWORDS:
                tokens.add(alias)
    return tokens


CANONICAL_ENTITY_ALIAS_CACHE: list[tuple[str, str]] | None = None


def _duplicate_phrase_norm(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = normalize_country_flags(text) if "normalize_country_flags" in globals() else text
    text = remove_external_links(text)
    text = apply_handle_replacements(text)
    text = apply_phrase_replacements(text, TEAM_REPLACEMENTS)
    text = apply_phrase_replacements(text, PLAYER_REPLACEMENTS)
    text = apply_phrase_replacements(text, HEBREW_FINAL_FIXES) if "HEBREW_FINAL_FIXES" in globals() else text
    text = re.sub(r"[^A-Za-z0-9\u0590-\u05ff'׳\- ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def _canonical_id(kind: str, value: str) -> str:
    norm = _duplicate_phrase_norm(value)
    norm = re.sub(r"[^A-Za-z0-9\u0590-\u05ff]+", "_", norm).strip("_")
    if not norm:
        norm = hashlib.sha1(str(value or "").encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{kind}:{norm}"


def _canonical_alias_entries() -> list[tuple[str, str]]:
    global CANONICAL_ENTITY_ALIAS_CACHE
    if CANONICAL_ENTITY_ALIAS_CACHE is not None:
        return CANONICAL_ENTITY_ALIAS_CACHE

    entries: list[tuple[str, str]] = []

    def add(kind: str, entity_id: str, aliases: list[str] | tuple[str, ...] | set[str]) -> None:
        for alias in aliases:
            norm = _duplicate_phrase_norm(str(alias or ""))
            if len(norm) < 3:
                continue
            entries.append((norm, entity_id))

    for key, item in all_team_catalog_items().items():
        aliases = [str(item.get("name", "")), key]
        aliases.extend(str(alias) for alias in item.get("aliases", []) or [])
        add("team", "team:" + normalize_team_key(key).replace(" ", "_"), aliases)

    for source, target in TEAM_REPLACEMENTS.items():
        add("team", _canonical_id("team", target), [source, target])

    for source, target in PLAYER_REPLACEMENTS.items():
        add("player", _canonical_id("player", target), [source, target])

    for item in CENTRAL_PLAYER_AFFILIATIONS:
        aliases = item.get("aliases", ())
        if not isinstance(aliases, (list, tuple, set)):
            aliases = (str(aliases),)
        aliases = [str(alias) for alias in aliases if str(alias).strip()]
        if aliases:
            add("player", _canonical_id("player", aliases[0]), aliases)

    # Long aliases first so "Real Madrid" wins before "Madrid".
    deduped = sorted(set(entries), key=lambda item: len(item[0]), reverse=True)
    CANONICAL_ENTITY_ALIAS_CACHE = deduped
    return deduped


def _duplicate_phrase_present(phrase: str, text: str) -> bool:
    phrase = _duplicate_phrase_norm(phrase)
    text = _duplicate_phrase_norm(text)
    return _duplicate_phrase_present_in_normalized_text(phrase, text)


def _duplicate_phrase_present_in_normalized_text(phrase: str, normalized_text: str) -> bool:
    if not phrase or not normalized_text:
        return False
    parts = [re.escape(part) for part in re.split(r"[\s\-]+", phrase) if part]
    if not parts:
        return False
    body = r"[\s\-]+".join(parts)
    hebrew_prefix = r"[\u05d5\u05d1\u05dc\u05de\u05d4]?" if re.match(r"^[\u0590-\u05ff]", phrase) else ""
    return bool(re.search(rf"(?<![A-Za-z0-9\u0590-\u05ff]){hebrew_prefix}{body}(?![A-Za-z0-9\u0590-\u05ff])", normalized_text, re.IGNORECASE))


def _canonical_event_entity_ids(text: str) -> set[str]:
    normalized = _duplicate_phrase_norm(text)
    if not normalized:
        return set()
    found: set[str] = set()
    for alias, entity_id in _canonical_alias_entries():
        if _duplicate_phrase_present_in_normalized_text(alias, normalized):
            found.add(entity_id)
    return found


def _canonical_sets_from_signature(sig: dict[str, Any]) -> tuple[set[str], set[str]]:
    entities = set(sig.get("entities", [])) if isinstance(sig, dict) else set()
    players = {entity for entity in entities if str(entity).startswith("player:")}
    teams = {entity for entity in entities if str(entity).startswith("team:")}
    return players, teams


NEWS_EVENT_FAMILY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("transfer_move", (
        r"\b(?:transfer|move|join|joining|sign|signing|loan|buy|purchase|deal|bid|offer|proposal|talks|negotiations|agreement|personal terms|medical|confident|optimistic|close|closing|final stages|advanced|push|pushing)\b",
        r"העברה|מעבר|מצטרף|יצטרף|חתימה|יחתום|השאלה|רכישה|עסקה|הצעה|שיחות|מגעים|מו\"מ|סיכום|תנאים אישיים|בדיקות רפואיות|בטוחים|בטוחה|אופטימי|אופטימית|קרוב|קרובה|סופי|סופיים|מתקדם|מתקדמת",
    )),
    ("coach_manager", (
        r"\b(?:coach|manager|head coach|shortlist|candidate|appointed|sacked|replacement)\b",
        r"מאמן|מאמנים|מועמד|רשימה|ימונה|מונה|פוטר|מחליף",
    )),
    ("injury_squad", (
        r"\b(?:injury|injured|out|miss|misses|ruled out|squad|called up|call-up|replace|replacement)\b",
        r"פציעה|נפצע|פצוע|ייעדר|יחמיץ|סגל|זומן|זימון|מחליף|להחליף",
    )),
    ("contract_stay", (
        r"\b(?:contract|extension|renewal|stay|stays|remain|release clause)\b",
        r"חוזה|הארכת חוזה|חידוש חוזה|נשאר|יישאר|סעיף שחרור",
    )),
)


def _news_event_families(text: str, tokens: set[str]) -> set[str]:
    families: set[str] = set()
    for label, patterns in NEWS_EVENT_FAMILY_PATTERNS:
        if any(re.search(pattern, text or "", re.IGNORECASE) for pattern in patterns):
            families.add(label)
    if {"bid", "offer", "proposal", "talks", "negotiations", "agreement", "deal", "medical", "confident", "optimistic", "close", "closing", "advanced", "push", "pushing"} & tokens:
        families.add("transfer_move")
    if {"coach", "manager", "candidate", "appointed", "sacked"} & tokens:
        families.add("coach_manager")
    if {"injury", "injured", "squad", "replacement", "replace", "misses"} & tokens:
        families.add("injury_squad")
    if {"contract", "extension", "renewal", "clause"} & tokens:
        families.add("contract_stay")
    return families


def news_event_signature(post: Post) -> dict[str, Any]:
    text = _news_duplicate_clean_text(post)
    tokens = _news_duplicate_tokens(text)
    action_tokens = tokens & NEWS_DUP_ACTION_WORDS
    action_tokens.update(_news_event_families(text, tokens))
    if re.search(r"\b(?:coach|manager|head coach|shortlist|list|talks?|contacts?|candidate|target)\b|מאמן|מאמנים|רשימה|רשימת|בראש רשימת|מגעים|שיחות|מועמד", text, re.IGNORECASE):
        action_tokens.add("coach_or_candidate_context")
    entity_tokens: set[str] = set()
    for source, target in {**TEAM_REPLACEMENTS, **PLAYER_REPLACEMENTS, **HANDLE_REPLACEMENTS}.items():
        for value in (source, target):
            if value and re.search(r"(?<!\w)" + re.escape(value.lower()) + r"(?!\w)", text):
                entity_tokens.update(_news_duplicate_tokens(value.lower()))
    canonical_entities = _canonical_event_entity_ids(text)
    entity_tokens.update(canonical_entities)
    # Add repeated proper-name style tokens from the normalized text as a fallback.
    for token in tokens:
        if len(token) >= 5 and token not in NEWS_DUP_ACTION_WORDS:
            entity_tokens.add(token)
    stage_rank, stage_label = _text_stage_rank(text) if "_text_stage_rank" in globals() else (0, "unknown")
    return {
        "text": text,
        "tokens": sorted(tokens),
        "entities": sorted(entity_tokens),
        "actions": sorted(action_tokens),
        "stage_rank": stage_rank,
        "stage": stage_label,
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
    current_players, current_teams = _canonical_sets_from_signature(current)
    previous_players, previous_teams = _canonical_sets_from_signature(previous)
    player_overlap = len(current_players & previous_players)
    team_overlap = len(current_teams & previous_teams)
    current_actions = set(current.get("actions", []))
    previous_actions = set(previous.get("actions", []))
    action_overlap = len(current_actions & previous_actions)
    family_overlap = _duplicate_family_overlap(current_actions, previous_actions)
    current_numbers = {token for token in current_tokens if re.fullmatch(r"\d+", token)}
    previous_numbers = {token for token in previous_tokens if re.fullmatch(r"\d+", token)}
    number_overlap = len(current_numbers & previous_numbers)
    sequence_score = SequenceMatcher(None, " ".join(sorted(current_tokens)), " ".join(sorted(previous_tokens))).ratio()
    score = max(token_jaccard, sequence_score * 0.75)
    if player_overlap >= 1 and team_overlap >= 2 and family_overlap:
        score = max(score, 0.90)
    elif player_overlap >= 1 and team_overlap >= 1 and family_overlap:
        score = max(score, 0.84)
    elif team_overlap >= 2 and family_overlap and (number_overlap >= 1 or action_overlap >= 1):
        score = max(score, 0.80)
    if entity_overlap >= 2 and (action_overlap >= 1 or number_overlap >= 1 or token_jaccard >= 0.24):
        score = max(score, 0.82)
    if entity_overlap >= 2 and number_overlap >= 1 and token_jaccard >= 0.16:
        score = max(score, 0.86)
    elif entity_overlap >= 3 and token_jaccard >= 0.22:
        score = max(score, 0.78)
    return score


def strict_duplicate_match(
    current: dict[str, Any],
    previous: dict[str, Any],
    score: float,
    local: str = "BORDERLINE",
) -> bool:
    """Return True only when two posts are genuinely the same report."""
    if local == "SAME_DUPLICATE":
        return True
    if local in {"ADVANCED_NEW", "DIFFERENT"}:
        return False

    current_entities = set(current.get("entities", []))
    previous_entities = set(previous.get("entities", []))
    current_actions = set(current.get("actions", []))
    previous_actions = set(previous.get("actions", []))
    current_tokens = set(current.get("tokens", []))
    previous_tokens = set(previous.get("tokens", []))
    current_players, current_teams = _canonical_sets_from_signature(current)
    previous_players, previous_teams = _canonical_sets_from_signature(previous)

    entity_overlap = len(current_entities & previous_entities)
    action_overlap = len(current_actions & previous_actions)
    family_overlap = _duplicate_family_overlap(current_actions, previous_actions)
    player_overlap = len(current_players & previous_players)
    team_overlap = len(current_teams & previous_teams)
    token_overlap = len(current_tokens & previous_tokens)
    number_overlap = len({token for token in current_tokens if token.isdigit()} & {token for token in previous_tokens if token.isdigit()})

    if player_overlap >= 1 and team_overlap >= 2 and family_overlap and score >= 0.50:
        return True
    if player_overlap >= 1 and team_overlap >= 1 and family_overlap and score >= 0.70 and token_overlap >= 5:
        return True
    if team_overlap >= 2 and family_overlap and (number_overlap >= 1 or action_overlap >= 1) and score >= 0.74:
        return True
    if score >= 0.94 and entity_overlap >= 2 and action_overlap >= 1:
        return True
    if score >= 0.90 and entity_overlap >= 3 and (action_overlap >= 1 or number_overlap >= 1):
        return True
    if score >= 0.88 and entity_overlap >= 2 and action_overlap >= 2 and token_overlap >= 7:
        return True
    return False


def cleanup_recent_news_events(state: dict[str, Any], now: float | None = None) -> list[dict[str, Any]]:
    now = now or time.time()
    recent_raw = state.get(RECENT_NEWS_STATE_KEY, [])
    if not isinstance(recent_raw, list):
        recent_raw = []
    recent: list[dict[str, Any]] = []
    for item in recent_raw:
        if isinstance(item, dict) and now - float(item.get("ts", 0) or 0) <= RECENT_NEWS_WINDOW_SECONDS:
            recent.append(item)
    state[RECENT_NEWS_STATE_KEY] = recent[-700:]
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
        if strict_duplicate_match(current, previous, score, local):
            return item
    return None


def remember_recent_news_event(post: Post, state: dict[str, Any], pending: bool = False) -> None:
    recent = cleanup_recent_news_events(state)
    recent.append(
        {
            "ts": time.time(),
            "username": post.username,
            "priority": SOURCE_PRIORITY.get(post.username, 0),
            "link": post.link,
            "pending": bool(pending),
            "ai_text": _ai_duplicate_text_from_post(post) if "_ai_duplicate_text_from_post" in globals() else _news_duplicate_clean_text(post),
            "signature": news_event_signature(post),
        }
    )
    state[RECENT_NEWS_STATE_KEY] = recent[-700:]


def confirm_recent_news_event(post: Post, state: dict[str, Any]) -> None:
    recent = cleanup_recent_news_events(state)
    for item in reversed(recent):
        if isinstance(item, dict) and item.get("link") == post.link and item.get("username") == post.username:
            item["pending"] = False
            item["ts"] = time.time()
            return
    remember_recent_news_event(post, state, pending=False)


def forget_pending_recent_news_event(post: Post, state: dict[str, Any]) -> None:
    recent = cleanup_recent_news_events(state)
    state[RECENT_NEWS_STATE_KEY] = [
        item
        for item in recent
        if not (
            isinstance(item, dict)
            and bool(item.get("pending", False))
            and item.get("link") == post.link
            and item.get("username") == post.username
        )
    ][-700:]


def drop_unconfirmed_recent_news_events(state: dict[str, Any]) -> None:
    recent = cleanup_recent_news_events(state)
    state[RECENT_NEWS_STATE_KEY] = [item for item in recent if not bool(item.get("pending", False))][-700:]


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
    state[CHANNEL_RECENT_NEWS_STATE_KEY] = recent[-700:]
    return state[CHANNEL_RECENT_NEWS_STATE_KEY]


def remember_channel_news_text(text: str, state: dict[str, Any], message_id: str = "", source: str = "channel", chat_id: str = "") -> None:
    post = channel_duplicate_text_to_post(text, message_id)
    if len(post.text) < 12:
        return
    recent = cleanup_channel_recent_news_events(state)
    if message_id:
        recent = [
            item for item in recent
            if not (isinstance(item, dict) and str(item.get("link", "")) == f"channel:{message_id}")
        ]
    signature = news_event_signature(post)
    if not signature.get("tokens"):
        return
    message_ids: dict[str, int] = {}
    if str(chat_id or "").strip() and str(message_id or "").isdigit():
        message_ids[str(chat_id)] = int(str(message_id))
    recent.append(
        {
            "ts": time.time(),
            "username": source,
            "priority": 120,
            "link": post.link,
            "ai_text": post.text,
            "message_ids": message_ids,
            "signature": signature,
        }
    )
    state[CHANNEL_RECENT_NEWS_STATE_KEY] = recent[-700:]


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
        if strict_duplicate_match(current, previous, score, local):
            return item
    return None


def cleanup_bot_sent_reply_targets(state: dict[str, Any], now: float | None = None) -> list[dict[str, Any]]:
    now = now or time.time()
    recent_raw = state.get(BOT_SENT_REPLY_STATE_KEY, [])
    if not isinstance(recent_raw, list):
        recent_raw = []
    recent: list[dict[str, Any]] = []
    for item in recent_raw:
        if isinstance(item, dict) and now - float(item.get("ts", 0) or 0) <= BOT_SENT_REPLY_WINDOW_SECONDS:
            recent.append(item)
    state[BOT_SENT_REPLY_STATE_KEY] = recent[-BOT_SENT_REPLY_MAX_ITEMS:]
    return state[BOT_SENT_REPLY_STATE_KEY]


def remember_bot_sent_reply_target(post: Post, state: dict[str, Any], message_ids_by_chat: dict[str, int]) -> None:
    if not message_ids_by_chat:
        return
    recent = cleanup_bot_sent_reply_targets(state)
    recent.append(
        {
            "ts": time.time(),
            "username": post.username,
            "priority": SOURCE_PRIORITY.get(post.username, 0),
            "link": post.link,
            "message_ids": {str(chat_id): int(message_id) for chat_id, message_id in message_ids_by_chat.items() if message_id},
            "signature": news_event_signature(post),
        }
    )
    state[BOT_SENT_REPLY_STATE_KEY] = recent[-BOT_SENT_REPLY_MAX_ITEMS:]


def channel_reply_target_match_is_certain(post: Post, item: dict[str, Any], score: float, local: str) -> bool:
    if local != "ADVANCED_NEW" or score < CHANNEL_REPLY_CERTAIN_MIN_SCORE:
        return False
    current_sig = news_event_signature(post)
    previous_sig = item.get("signature", {}) if isinstance(item, dict) else {}
    if not isinstance(previous_sig, dict):
        return False
    cur_players, cur_teams = _canonical_sets_from_signature(current_sig)
    prev_players, prev_teams = _canonical_sets_from_signature(previous_sig)
    player_overlap = len(cur_players & prev_players)
    team_overlap = len(cur_teams & prev_teams)
    cur_actions = set(current_sig.get("actions", []))
    prev_actions = set(previous_sig.get("actions", []))
    family_overlap = _duplicate_family_overlap(cur_actions, prev_actions)
    cur_tokens = set(current_sig.get("tokens", []))
    prev_tokens = set(previous_sig.get("tokens", []))
    cur_entities = set(current_sig.get("entities", []))
    prev_entities = set(previous_sig.get("entities", []))
    distinctive_overlap = _near_duplicate_subject_overlap(
        _distinctive_duplicate_tokens(cur_tokens, cur_entities),
        _distinctive_duplicate_tokens(prev_tokens, prev_entities),
    )
    number_overlap = len({token for token in cur_tokens if token.isdigit()} & {token for token in prev_tokens if token.isdigit()})
    if player_overlap >= 1 and team_overlap >= 1 and family_overlap:
        return True
    if player_overlap >= 1 and family_overlap and score >= 0.72:
        return True
    if team_overlap >= 2 and family_overlap and (distinctive_overlap >= 1 or number_overlap >= 1):
        return True
    return False


def find_bot_reply_target_for_post(post: Post, state: dict[str, Any]) -> dict[str, int]:
    best_item: dict[str, Any] | None = None
    best_score = 0.0
    for item in reversed(cleanup_bot_sent_reply_targets(state)):
        if not isinstance(item, dict):
            continue
        message_ids = item.get("message_ids")
        if not isinstance(message_ids, dict) or not message_ids:
            continue
        previous = item.get("signature", {})
        if not isinstance(previous, dict):
            continue
        score = _event_similarity(news_event_signature(post), previous)
        local = local_duplicate_verdict(post, item, score) if "local_duplicate_verdict" in globals() else "BORDERLINE"
        if local != "ADVANCED_NEW":
            continue
        if score > best_score:
            best_item = item
            best_score = score
    if not best_item:
        for item in reversed(cleanup_channel_recent_news_events(state)):
            if not isinstance(item, dict):
                continue
            message_ids = item.get("message_ids")
            if not isinstance(message_ids, dict) or not message_ids:
                continue
            previous = item.get("signature", {})
            if not isinstance(previous, dict):
                continue
            score = _event_similarity(news_event_signature(post), previous)
            local = local_duplicate_verdict(post, item, score) if "local_duplicate_verdict" in globals() else "BORDERLINE"
            if not channel_reply_target_match_is_certain(post, item, score, local):
                continue
            if score > best_score:
                best_item = item
                best_score = score
        if not best_item:
            return {}
    return {str(chat_id): int(message_id) for chat_id, message_id in dict(best_item.get("message_ids", {})).items() if message_id}


def find_recent_burst_spam_event(post: Post, state: dict[str, Any]) -> dict[str, Any] | None:
    current_sig = news_event_signature(post)
    current_tokens = set(current_sig.get("tokens", []))
    current_entities = set(current_sig.get("entities", []))
    current_actions = set(current_sig.get("actions", []))
    current_stage_rank, _stage = _text_stage_rank(str(current_sig.get("text", ""))) if "_text_stage_rank" in globals() else (0, "unknown")
    if current_stage_rank >= 60 or event_detail_richness(post) >= 10:
        return None
    current_distinctive = _distinctive_duplicate_tokens(current_tokens, current_entities)
    if not current_distinctive:
        return None
    now = time.time()
    matches: list[dict[str, Any]] = []
    for item in reversed(cleanup_recent_news_events(state)):
        if not isinstance(item, dict) or now - float(item.get("ts", 0) or 0) > NEWS_BURST_SPAM_WINDOW_SECONDS:
            continue
        previous = item.get("signature", {})
        if not isinstance(previous, dict):
            continue
        prev_tokens = set(previous.get("tokens", []))
        prev_entities = set(previous.get("entities", []))
        prev_actions = set(previous.get("actions", []))
        prev_distinctive = _distinctive_duplicate_tokens(prev_tokens, prev_entities)
        if len(current_distinctive & prev_distinctive) >= 1 and (
            _duplicate_family_overlap(current_actions, prev_actions)
            or _event_similarity(current_sig, previous) >= 0.42
        ):
            matches.append(item)
    if len(matches) >= NEWS_BURST_SPAM_MIN_EVENTS:
        return matches[0]
    return None


def duplicate_event_source_he(item: dict[str, Any] | None) -> str:
    if not isinstance(item, dict):
        return "מקור קודם"
    source = str(item.get("username") or "unknown")
    if source in {"channel", "channel_edit"}:
        return "הודעה שכבר קיימת בערוץ שלך"
    if source == "bot_sent":
        return "הודעה שהבוט כבר שלח לערוץ"
    if source and source != "unknown":
        return f"@{source}"
    return "מקור קודם"


def duplicate_event_debug_he(post: Post, item: dict[str, Any] | None) -> str:
    if not isinstance(item, dict):
        return "לא נמצאו פרטי כפילות"
    score = _event_similarity_score_for_post(post, item) if "_event_similarity_score_for_post" in globals() else 0.0
    local = local_duplicate_verdict(post, item, score) if "local_duplicate_verdict" in globals() else "BORDERLINE"
    cur_sig = news_event_signature(post)
    prev_sig = item.get("signature", {}) if isinstance(item.get("signature", {}), dict) else {}
    cur_entities = set(cur_sig.get("entities", []))
    prev_entities = set(prev_sig.get("entities", []))
    cur_actions = set(cur_sig.get("actions", []))
    prev_actions = set(prev_sig.get("actions", []))
    cur_tokens = set(cur_sig.get("tokens", []))
    prev_tokens = set(prev_sig.get("tokens", []))
    cur_rank, cur_stage = _text_stage_rank(str(cur_sig.get("text", ""))) if "_text_stage_rank" in globals() else (0, "unknown")
    prev_rank, prev_stage = _text_stage_rank(str(prev_sig.get("text", ""))) if "_text_stage_rank" in globals() else (0, "unknown")
    shared_entities = sorted((cur_entities & prev_entities) or (_distinctive_duplicate_tokens(cur_tokens, cur_entities) & _distinctive_duplicate_tokens(prev_tokens, prev_entities)))[:8]
    shared_actions = sorted(cur_actions & prev_actions)[:6]
    return (
        f"סיבה: {duplicate_event_source_he(item)} | דמיון {score:.2f} | החלטה {local} | "
        f"שלב נוכחי {cur_stage}/{cur_rank}, קודם {prev_stage}/{prev_rank} | "
        f"נושא משותף: {', '.join(shared_entities) or 'לא זוהה'} | פעולה: {', '.join(shared_actions) or 'לא זוהתה'}"
    )


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
        if is_interview_post(line_post) or is_other_sport_post(line_post) or is_youth_or_academy_post(line_post):
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
            -event_detail_richness(item[1]),
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
AI_DECISION_CACHE_DIRTY = False


def ai_decision_cache_path() -> Path:
    return app_data_path(AI_DECISION_CACHE_FILE)

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
        logging.info("🧠 נטען cache כפילויות מהדיסק: %s החלטות", len(AI_DECISION_CACHE))
    except Exception as exc:
        logging.warning("⚠️ לא הצליח לטעון cache החלטות כפילות: %s", exc)

def save_ai_decision_cache() -> None:
    global AI_DECISION_CACHE_DIRTY
    if not ENABLE_AI_REQUEST_SAVER:
        return
    if not AI_DECISION_CACHE_DIRTY:
        return
    try:
        path = ai_decision_cache_path()
        temp_path = path.with_suffix(path.suffix + ".tmp")
        ordered = {key: AI_DECISION_CACHE[key] for key in AI_DECISION_CACHE_ORDER[-AI_DECISION_CACHE_MAX_ITEMS:] if key in AI_DECISION_CACHE}
        temp_path.write_text(json.dumps({"items": ordered}, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(path)
        AI_DECISION_CACHE_DIRTY = False
    except Exception as exc:
        logging.warning("⚠️ לא הצליח לשמור cache החלטות כפילות: %s", exc)

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
    "official", "confirmed", "contract", "fee", "package", "salary", "years", "year", "option", "clause", "medical", "loan", "permanent",
    "pick", "picks", "first-round", "second-round", "extension", "waived", "injury", "severity", "return", "date", "deadline",
    "week", "weeks", "day", "days", "month", "months", "tests", "scan", "hamstring", "muscle", "fracture",
    "רשמי", "אישרה", "אישר", "חוזה", "שכר", "חבילה", "בונוסים", "מיליון", "שנים", "שנה", "אופציה", "סעיף", "בדיקות", "רפואיות", "השאלה",
    "בחירה", "דראפט", "הארכת", "שוחרר", "פציעה", "חומרת", "חזרה", "תאריך", "דדליין",
}

INJURY_ADVANCEMENT_DETAIL_WORDS = {
    "severity", "return", "date", "deadline", "week", "weeks", "day", "days", "month", "months",
    "tests", "scan", "fracture", "surgery", "operation", "acl", "tear", "torn", "confirmed",
    "חומרת", "חזרה", "תאריך", "דדליין", "שבוע", "שבועות", "יום", "ימים", "חודש", "חודשים",
    "בדיקות", "סריקה", "שבר", "ניתוח", "קרע", "אושר", "אישר", "אישרה",
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


def _material_number_detail_tokens(text: str) -> set[str]:
    cleaned = (text or "").lower()
    details: set[str] = set()
    for match in re.finditer(r"\b\d+(?:[.,]\d+)?\s?(?:m|million|מיליון|%|percent|אחוזים?)?\b", cleaned, flags=re.IGNORECASE):
        token = re.sub(r"\s+", "", match.group(0).lower())
        if token:
            details.add(token)
    for match in re.finditer(r"\b(?:19|20)\d{2}\b", cleaned):
        details.add(match.group(0))
    return details


GENERIC_DUPLICATE_CONTEXT_TOKENS = {
    "manchester", "united", "real", "madrid", "barcelona", "barca", "arsenal", "chelsea", "liverpool",
    "tottenham", "spurs", "city", "inter", "milan", "juventus", "psg", "bayern", "dortmund", "villa",
    "official", "confirmed", "free", "agent", "players", "player", "club", "clubs", "deal", "transfer",
    "contract", "years", "year", "today", "expected", "chapter", "new", "since", "after", "joins", "leaves",
    "מנצסטר", "יונייטד", "סיטי", "ריאל", "מדריד", "ברצלונה", "בארסה", "ארסנל", "צלסי", "ליברפול",
    "טוטנהאמ", "ספרס", "אינטר", "מילאנ", "יובנטוס", "באיירנ", "דורטמונד", "וילה",
    "רשמי", "רשמית", "שחקן", "שחקנים", "חופשי", "חופשיים", "עוזב", "עוזבים", "עזב", "עזבו", "מועדון",
    "קבוצה", "העברה", "עסקה", "חוזה", "שנים", "שנה", "היום", "צפוי", "צפויים", "חדש", "חדשה",
}


BIG_CLUB_DUPLICATE_TOKEN_GROUPS: tuple[set[str], ...] = (
    {"מנצסטר", "סיטי", "manchester", "city", "mcfc"},
    {"מנצסטר", "יונייטד", "manchester", "united", "mufc"},
    {"ריאל", "מדריד", "real", "madrid", "rma"},
    {"ברצלונה", "בארסה", "barcelona", "barca"},
    {"ליברפול", "liverpool", "lfc"},
    {"ארסנל", "arsenal"},
    {"צלסי", "chelsea"},
    {"טוטנהאמ", "ספרס", "tottenham", "spurs"},
    {"באיירנ", "bayern"},
    {"פסז", "psg", "פריז"},
    {"יובנטוס", "juventus", "juve"},
    {"אינטר", "inter"},
    {"מילאנ", "milan"},
)


def _shared_big_club_groups(cur_tokens: set[str], prev_tokens: set[str]) -> int:
    shared = 0
    for group in BIG_CLUB_DUPLICATE_TOKEN_GROUPS:
        if cur_tokens & group and prev_tokens & group:
            shared += 1
    return shared

DETAIL_RICHNESS_PATTERNS = (
    r"\b(?:€|£|\$|million|m|fee|package|add-ons|sell-on|clause|release clause|contract until|until 20\d{2}|salary|wages|medical|bid|offer|proposal|loan|option|obligation|buy option|permanent)\b",
    r"מיליון|אירו|יורו|ליש\"ט|דולר|סכום|חבילה|בונוסים|אחוזים ממכירה|מכירה עתידית|סעיף|סעיף שחרור|חוזה עד|עד 20\d{2}|שכר|בדיקות רפואיות|הצעה|השאלה|אופציה|חובת רכישה|רכישה",
)


def event_detail_richness(post: Post) -> int:
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    score = 0
    for pattern in DETAIL_RICHNESS_PATTERNS:
        score += len(re.findall(pattern, cleaned, flags=re.IGNORECASE)) * 4
    score += min(12, len(re.findall(r"\b(?:19|20)\d{2}\b|[€£$]\s?\d+|\d+\s?(?:m|million|מיליון|%)", cleaned, flags=re.IGNORECASE)) * 3)
    score += min(10, len(_news_duplicate_tokens(_news_duplicate_clean_text(post))) // 5)
    return score


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


def _duplicate_family_overlap(cur_actions: set[str], prev_actions: set[str]) -> set[str]:
    return {
        action
        for action in (cur_actions & prev_actions)
        if action in {"transfer_move", "coach_manager", "injury_squad", "contract_stay", "coach_or_candidate_context"}
    }


def _near_duplicate_subject_overlap(cur_distinctive: set[str], prev_distinctive: set[str]) -> int:
    overlap = len(cur_distinctive & prev_distinctive)
    if overlap:
        return overlap
    matches = 0
    for cur in cur_distinctive:
        if len(cur) < 5:
            continue
        for prev in prev_distinctive:
            if len(prev) < 5:
                continue
            if SequenceMatcher(None, cur, prev).ratio() >= 0.88:
                matches += 1
                break
    return matches


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
    distinctive_overlap = _near_duplicate_subject_overlap(cur_distinctive, prev_distinctive)
    family_overlap = _duplicate_family_overlap(cur_actions, prev_actions)
    squad_absence_overlap = _squad_absence_subject_overlap(cur_tokens, prev_tokens)
    shared_big_club_groups = _shared_big_club_groups(cur_tokens | cur_entities, prev_tokens | prev_entities)
    number_detail_delta = len(_material_number_detail_tokens(cur_text) - _material_number_detail_tokens(prev_text))
    cur_sig = news_event_signature(current_post)
    prev_sig = previous_item.get("signature", {}) if isinstance(previous_item, dict) else {}
    if not isinstance(prev_sig, dict):
        prev_sig = {}
    cur_players, cur_teams = _canonical_sets_from_signature(cur_sig)
    prev_players, prev_teams = _canonical_sets_from_signature(prev_sig)
    canonical_player_overlap = len(cur_players & prev_players)
    canonical_team_overlap = len(cur_teams & prev_teams)
    new_important_detail_tokens = (cur_tokens - prev_tokens) & IMPORTANT_DETAIL_WORDS
    general_has_new_material_detail = detail_delta >= 2 or number_detail_delta >= 1
    injury_has_new_material_detail = bool(new_important_detail_tokens & INJURY_ADVANCEMENT_DETAIL_WORDS) or number_detail_delta >= 1

    if (
        not same_author
        and family_overlap
        and (canonical_player_overlap >= 1 or canonical_team_overlap >= 2)
        and (current_rank >= previous_rank or "injury_squad" in family_overlap)
        and (
            ("injury_squad" in family_overlap and injury_has_new_material_detail)
            or ("injury_squad" not in family_overlap and general_has_new_material_detail)
        )
    ):
        return "ADVANCED_NEW"

    if (
        not same_author
        and canonical_player_overlap >= 1
        and canonical_team_overlap >= 2
        and family_overlap
        and current_rank < previous_rank + 10
        and detail_delta <= 1
    ):
        return "SAME_DUPLICATE"
    if (
        not same_author
        and canonical_player_overlap >= 1
        and canonical_team_overlap >= 1
        and family_overlap
        and score >= 0.62
        and current_rank < previous_rank + 10
        and detail_delta <= 1
    ):
        return "SAME_DUPLICATE"
    if (
        not same_author
        and canonical_team_overlap >= 2
        and family_overlap
        and score >= 0.72
        and current_rank < previous_rank + 10
        and detail_delta <= 1
    ):
        return "SAME_DUPLICATE"

    # Same journalist often posts several separate updates about the same club minutes apart.
    # For the same source, block only a near-repeat or a post sharing the same distinctive
    # player/manager/event tokens. Club/context overlap alone is not enough.
    if same_author:
        if text_ratio >= 0.94:
            return "SAME_DUPLICATE"
        if distinctive_overlap >= 2 and family_overlap and current_rank <= previous_rank + 10 and detail_delta <= 1:
            return "SAME_DUPLICATE"
        if cur_distinctive and prev_distinctive and distinctive_overlap == 0:
            return "DIFFERENT"
        if distinctive_overlap == 0 and score < 0.94:
            return "DIFFERENT"
        if score < 0.86 and text_ratio < 0.86:
            return "DIFFERENT"

    # Before dismissing low text similarity, catch same-event reports that use very
    # different wording but share the same named subject and event family.
    if (
        not same_author
        and distinctive_overlap >= 2
        and family_overlap
        and score >= 0.58
        and current_rank < previous_rank + 10
        and detail_delta <= 1
    ):
        return "SAME_DUPLICATE"

    # Cross-language channel memory: English source post vs Hebrew message already
    # published in the channel. Same player-name token (including transliteration),
    # same major club and same transfer/contract family is a duplicate even when
    # the text ratio is low.
    if (
        not same_author
        and shared_big_club_groups >= 1
        and distinctive_overlap >= 2
        and family_overlap
        and score >= 0.50
        and current_rank < previous_rank + 10
        and detail_delta <= 1
    ):
        return "SAME_DUPLICATE"

    # Clearly different: not enough shared entities and not enough text/action overlap.
    if score < AI_DUPLICATE_MIN_SIMILARITY and entity_overlap < 2:
        return "DIFFERENT"
    if entity_overlap == 0 and score < 0.72:
        return "DIFFERENT"

    if squad_absence_overlap and _is_squad_absence_context(cur_text) and _is_squad_absence_context(prev_text):
        return "SAME_DUPLICATE"

    # Strong anti-spam rule: the same named subject in the same news family is the
    # same story even when two writers phrase it very differently.
    if (
        not same_author
        and distinctive_overlap >= 2
        and family_overlap
        and score >= 0.58
        and current_rank < previous_rank + 10
        and detail_delta <= 1
    ):
        return "SAME_DUPLICATE"
    if (
        not same_author
        and distinctive_overlap >= 2
        and family_overlap
        and action_overlap >= 2
        and score >= 0.60
        and current_rank < previous_rank + 10
        and detail_delta <= 1
    ):
        return "SAME_DUPLICATE"

    if (
        not same_author
        and distinctive_overlap >= 2
        and current_stage == "medical_or_final_steps"
        and "medical" not in cur_text
        and previous_rank >= 50
        and score >= 0.58
        and detail_delta <= 1
    ):
        return "SAME_DUPLICATE"

    # Material advancement: official/completed/agreed after a lower stage, or important new detail.
    if entity_overlap >= 1 and current_rank >= previous_rank + 20 and current_rank >= 50:
        return "ADVANCED_NEW"
    if entity_overlap >= 2 and detail_delta >= 3 and current_rank >= previous_rank:
        return "ADVANCED_NEW"

    # Different journalists often phrase the same report very differently.
    # If the same distinctive person/event tokens and the same action context appear,
    # treat it as the same story unless this post is a clear advancement.
    if (
        not same_author
        and distinctive_overlap >= 2
        and (action_overlap >= 1 or family_overlap)
        and score >= 0.60
        and current_rank < previous_rank + 10
        and detail_delta <= 1
    ):
        return "SAME_DUPLICATE"
    if (
        not same_author
        and entity_overlap >= 2
        and distinctive_overlap >= 2
        and action_overlap >= 1
        and score >= 0.72
        and current_rank < previous_rank + 10
        and detail_delta <= 1
    ):
        return "SAME_DUPLICATE"

    # Very strong same-event match with no higher stage: skip locally, no Gemini needed.
    if score >= AI_DUPLICATE_AUTO_SKIP_SIMILARITY and entity_overlap >= 2 and action_overlap >= 1 and current_rank <= previous_rank and detail_delta == 0:
        return "SAME_DUPLICATE"
    if entity_overlap >= 3 and action_overlap >= 1 and distinctive_overlap >= 2 and score >= 0.86 and current_rank <= previous_rank and detail_delta <= 1:
        return "SAME_DUPLICATE"

    # Same entity but stronger trusted source: usually same duplicate unless it materially advances.
    if entity_overlap >= 2 and action_overlap >= 1 and distinctive_overlap >= 2 and score >= 0.90 and SOURCE_PRIORITY.get(current_post.username, 0) > int(previous_item.get("priority", 0) or 0) and current_rank <= previous_rank and detail_delta <= 1:
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
    global AI_DECISION_CACHE_DIRTY
    if not ENABLE_AI_REQUEST_SAVER or verdict not in {"SAME_DUPLICATE", "ADVANCED_NEW", "DIFFERENT", "UNKNOWN"}:
        return
    key = _ai_cache_key(previous_text, current_text)
    if key not in AI_DECISION_CACHE:
        AI_DECISION_CACHE_ORDER.append(key)
    if AI_DECISION_CACHE.get(key) != verdict:
        AI_DECISION_CACHE_DIRTY = True
    AI_DECISION_CACHE[key] = verdict
    while len(AI_DECISION_CACHE_ORDER) > AI_DECISION_CACHE_MAX_ITEMS:
        old = AI_DECISION_CACHE_ORDER.pop(0)
        if AI_DECISION_CACHE.pop(old, None) is not None:
            AI_DECISION_CACHE_DIRTY = True
    save_ai_decision_cache()


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
        logging.debug("חיסכון Gemini: החלטה מקומית בכפילות @%s מול @%s => %s | score=%.2f", current_post.username, previous_item.get("username", "unknown"), local, score)
        return local

    cached = _ai_cache_get(previous_text, current_text)
    if cached:
        logging.debug("חיסכון Gemini: תשובת כפילות מה-cache @%s מול @%s => %s", current_post.username, previous_item.get("username", "unknown"), cached)
        return cached

    if not ENABLE_AI_DUPLICATE_CHECK or not GEMINI_API_KEYS:
        return "UNKNOWN"
    if not has_gemini_key_available():
        logging.debug("חיסכון Gemini: אין מפתח זמין כרגע לפי cooldown מקומי; מדלג על AI כפילות למחזור הזה")
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
        logging.warning("⚠️ בדיקת כפילות חכמה לא זמינה כרגע: %s", gemini_error_summary(last_error) if 'gemini_error_summary' in globals() else last_error)
    _ai_cache_set(previous_text, current_text, "UNKNOWN")
    return "UNKNOWN"

def find_recent_duplicate_event_ai_aware(post: Post, state: dict[str, Any]) -> dict[str, Any] | None:
    """Final duplicate gate. Cheap local rules first, Gemini only for borderline near-matches."""
    recent = list(reversed(cleanup_recent_news_events(state)))
    fallback_duplicate: dict[str, Any] | None = None
    current_sig = news_event_signature(post)
    for item in recent:
        if not isinstance(item, dict):
            continue
        score = _event_similarity_score_for_post(post, item)
        local = local_duplicate_verdict(post, item, score)
        if local == "SAME_DUPLICATE":
            return item
        if local in {"ADVANCED_NEW", "DIFFERENT"}:
            continue
        if score < AI_DUPLICATE_MIN_SIMILARITY:
            continue

        # Gemini only for true borderline cases.
        verdict = gemini_duplicate_event_verdict(post, item)
        if verdict == "SAME_DUPLICATE":
            return item
        if verdict in {"ADVANCED_NEW", "DIFFERENT"}:
            continue
        previous_sig = item.get("signature", {}) if isinstance(item.get("signature", {}), dict) else {}
        if previous_sig and strict_duplicate_match(current_sig, previous_sig, score, local) and fallback_duplicate is None:
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
            -event_detail_richness(_candidate_post(item)),
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
        logging.debug("חיסכון Gemini: מיזוג מקביל מקומי בלי AI. מקורות: %s", also or _candidate_username(ordered[0]))
        return fallback + (f"\nAlso reported by: {also}" if also else "")
    if not has_gemini_key_available():
        also = ", ".join("@" + _candidate_username(item) for item in ordered[1:4])
        logging.debug("חיסכון Gemini: מיזוג AI נדחה כי אין מפתח זמין; משתמש במקור הטוב ביותר")
        return fallback + (f"\nAlso reported by: {also}" if also else "")
    logging.debug("Gemini merge: משתמש בבינה רק כי יש כמה מקורות/פרטים חדשים שצריך למזג חכם")
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
        "🧩 מיזוג חכם: %s דיווחים מקבילים אוחדו להודעה אחת. מקור מוביל: @%s | מקורות: %s",
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


def remove_dangling_source_attribution(text: str) -> str:
    """Remove source-credit fragments after handles/outlets were stripped."""
    text = text or ""
    source_names = (
        r"@?[A-Za-z0-9_]{3,40}|"
        r"Fabrizio\s+Romano|David\s+Ornstein|Gianluca\s+Di\s+Marzio|Di\s+Marzio|Nicol[oò]\s+Schira|"
        r"Matteo\s+Moretto|Ben\s+Jacobs|Florian\s+Plettenberg|Fernando\s+Polo|Gerard\s+Romero|"
        r"פבריציו\s+רומאנו|דיוויד\s+אורנשטיין|ג'אנלוקה\s+די\s+מרציו|ניקולו\s+שירה|מתאו\s+מורטו|בן\s+ג'ייקובס|פלוריאן\s+פלטנברג"
    )
    empty_tail = r"(?:\s*(?:[.,;:!?]|$))"
    patterns = (
        rf"(?iu)\s*,?\s*(?:as\s+(?:first\s+)?reported|as\s+revealed|as\s+told|reported)\s+by\s*(?:{source_names})?{empty_tail}",
        rf"(?iu)\s*,?\s*(?:via|h/t|credit(?:s)?\s+to)\s*(?:{source_names}){empty_tail}",
        rf"(?iu)\s*,?\s*(?:כפי\s+ש(?:דווח|מדווח|מדווחת|נחשף|פורסם)|כמו\s+ש(?:דווח|פורסם)|לפי\s+הדיווח)\s+(?:על\s+ידי|בידי|אצל|של)?\s*(?:{source_names})?{empty_tail}",
        rf"(?iu)\s*,?\s*(?:דווח|פורסם|נחשף)\s+(?:על\s+ידי|בידי|אצל)\s*(?:{source_names})?{empty_tail}",
    )
    for pattern in patterns:
        text = re.sub(pattern, ".", text)
    text = re.sub(
        r"(?iu)\s*,?\s*(?:כפי\s+ש(?:נחשף|דווח|פורסם|מדווח)|כמו\s+ש(?:נחשף|דווח|פורסם))\s+(?:אתמול|היום|מוקדם\s+יותר|לפני\s+[^.!?,;\n]{1,40})\s*[.!?]?",
        ".",
        text,
    )
    text = re.sub(r"(?iu)\s*,?\s*(?:as\s+(?:first\s+)?reported|reported\s+by|כפי\s+שדווח|דווח\s+על\s+ידי)\s*[.,;:!?]*\s*$", "", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"\.{2,}", ".", text)
    text = re.sub(r"\s*\.\s*\.", ".", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" *\n+ *", "\n", text)
    return text.strip(" \t,;:")


def remove_writer_brag_phrases(text: str) -> str:
    text = text or ""
    patterns = (
        r"(?iu)\s*(?:אין\s+הפתעות\s+כאן|אין\s+הפתעות|לא\s+היו\s+הפתעות)\s*(?:ו|,|\.)?\s*(?:זה\s+)?(?:אושר|מאושר|מאומת|ידוע|נחשף|דווח|פורסם)?\s*(?:מאז|כבר\s+מאז)?\s*(?:ה-?\d{1,2}\s+ב[א-ת]+|\d{1,2}/\d{1,2}(?:/\d{2,4})?|[A-Za-z]+\s+\d{1,2})?\s*[.!?]?",
        r"(?iu)\s*(?:וזה\s+)?(?:אושר|מאומת|ידוע|נחשף|דווח|פורסם)\s+(?:כבר\s+)?מאז\s+(?:ה-?\d{1,2}\s+ב[א-ת]+|\d{1,2}/\d{1,2}(?:/\d{2,4})?|[A-Za-z]+\s+\d{1,2})\s*[.!?]?",
        r"(?iu)\s*(?:confirmed|verified|reported|revealed)\s+since\s+(?:last\s+)?(?:\d{1,2}\s+[A-Za-z]+|[A-Za-z]+\s+\d{1,2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s*[.!?]?",
        r"(?iu)\s*(?:no\s+surprises?\s+here|no\s+surprise)\s*[.!?]?",
    )
    for pattern in patterns:
        text = re.sub(pattern, ".", text)
    text = re.sub(
        r"(?iu)\s*(?:אין\s+הפתעות(?:\s+כאן)?|לא\s+היו\s+הפתעות)(?:\s*(?:ו|,|\.))?\s*(?:זה\s+)?(?:אושר|מאושר|מאומת|ידוע|נחשף|דווח|פורסם)?\s*(?:כבר\s+)?מאז[^.!?\n]*(?:האחרון)?[.!?]?",
        ".",
        text,
    )
    text = re.sub(
        r"(?iu)\s*(?:וזה\s+)?(?:אושר|מאושר|מאומת|ידוע|נחשף|דווח|פורסם)\s+(?:כבר\s+)?מאז[^.!?\n]*(?:האחרון)?[.!?]?",
        ".",
        text,
    )
    text = re.sub(r"(?iu)\.?\s*האחרון[.!?]?", ".", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"\.{2,}", ".", text)
    return text.strip()


def _known_team_display_names() -> list[str]:
    names: set[str] = set()
    for item in all_team_catalog_items().values():
        name = str(item.get("name", "")).strip()
        if name:
            names.add(name)
        for alias in item.get("aliases", []) or []:
            alias_text = str(alias).strip()
            if re.search(r"[א-ת]", alias_text):
                names.add(alias_text)
    names.update({"מנצ'סטר סיטי", "מנצ'סטר יונייטד", "צ'לסי", "טוטנהאם", "ארסנל", "ליברפול", "באיירן", "ריאל מדריד", "ברצלונה"})
    return sorted(names, key=len, reverse=True)


def remove_trailing_duplicate_team_tags(text: str) -> str:
    value = text or ""
    team_names = _known_team_display_names()
    if not team_names:
        return value.strip()
    team_alt = "|".join(re.escape(name) for name in team_names if name)
    for _ in range(3):
        match = re.search(rf"(?s)(.*?)(?:[.!?]\s+)((?:(?:{team_alt})(?:\s+(?:{team_alt}))*))\s*[.!?]?\s*$", value)
        if not match:
            break
        before = match.group(1).strip()
        tail = match.group(2).strip()
        tail_names = [name for name in team_names if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", tail)]
        if not tail_names or not all(re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", before) for name in tail_names):
            break
        value = before.strip()
    return value.strip()


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
    return app_data_path(TRANSLATION_CACHE_FILE)


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
    global TRANSLATION_CACHE_DIRTY
    if not TRANSLATION_CACHE_DIRTY:
        return
    try:
        trimmed = dict(list(cache.items())[-10000:])
        path = cache_path()
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(trimmed, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(path)
        if len(trimmed) != len(cache):
            cache.clear()
            cache.update(trimmed)
        TRANSLATION_CACHE_DIRTY = False
    except Exception as exc:
        logging.warning("⚠️ לא הצליח לשמור cache תרגומים: %s", exc)


TRANSLATION_CACHE = load_translation_cache()
TRANSLATION_CACHE_DIRTY = False
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
    if is_gemini_output_validation_error(error):
        return "פלט Gemini נפסל בבדיקת איכות מקומית"
    if is_gemini_temporary_overload_error(error):
        return "עומס זמני ב-Gemini, ינסה שוב אחרי קירור קצר"
    if "404" in lowered or "not found" in lowered or "model" in lowered:
        return "בעיה בהגדרת מודל Gemini"
    if "400" in lowered or "invalid argument" in lowered:
        return "בקשת Gemini חזרה לא תקינה"
    return "שגיאת ג'מיני זמנית"


def is_gemini_quota_error(error: Exception | None) -> bool:
    lowered = str(error or "").lower()
    return "quota" in lowered or "429" in lowered or "resource_exhausted" in lowered


def is_gemini_temporary_overload_error(error: Exception | None) -> bool:
    lowered = str(error or "").lower()
    return any(
        marker in lowered
        for marker in (
            "http 503",
            "unavailable",
            "high demand",
            "try again later",
            "temporarily unavailable",
            "http 500",
            "http 502",
            "http 504",
        )
    )


def is_gemini_output_validation_error(error: Exception | None) -> bool:
    lowered = str(error or "").lower()
    return any(
        marker in lowered
        for marker in (
            "translation contradicted source names",
            "translation changed locked numbers",
            "returned empty translation",
            "returned no meaningful translation",
            "non json translation",
            "no meaningful translation",
        )
    )


def should_cool_down_gemini_key(error: Exception | None) -> bool:
    if error is None:
        return True
    if is_gemini_output_validation_error(error):
        return False
    lowered = str(error or "").lower()
    return any(
        marker in lowered
        for marker in (
            "quota", "429", "resource_exhausted", "403", "401", "api key", "permission",
            "timeout", "timed out", "urlopen", "connection", "ssl", "http 500", "http 502",
            "http 503", "http 504", "remote end", "temporarily unavailable",
        )
    )


def should_stop_gemini_key_sweep(error: Exception | None) -> bool:
    if error is None or is_gemini_output_validation_error(error) or is_gemini_quota_error(error) or is_gemini_temporary_overload_error(error):
        return False
    lowered = str(error or "").lower()
    if "api key" in lowered or "permission" in lowered or "403" in lowered or "401" in lowered:
        return False
    return any(marker in lowered for marker in ("http 400", "invalid argument", "http 404", "not found", "model"))


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
    # Free local check only: scans configured key cooldowns in memory, never calls Gemini.
    if gemini_requests_paused_until_refill():
        return False
    if GEMINI_DISABLED_UNTIL and GEMINI_DISABLED_UNTIL > time.time():
        return False
    return bool(GEMINI_API_KEYS and gemini_key_order_limited(GEMINI_LOCAL_KEY_SWEEP_SIZE))


def gemini_available_keys_for_operation() -> list[tuple[int, str]]:
    """Return every locally-available Gemini key for this operation.

    This performs only an in-memory cooldown sweep over up to
    GEMINI_LOCAL_KEY_SWEEP_SIZE keys. It does not contact Gemini and therefore
    does not spend requests/credit. Real requests are still capped separately by
    GEMINI_MAX_REAL_TRANSLATION_REQUESTS and the max_real_requests argument in
    gemini_translate().
    """
    if gemini_requests_paused_until_refill():
        return []
    if GEMINI_DISABLED_UNTIL and GEMINI_DISABLED_UNTIL > time.time():
        return []
    return gemini_key_order_limited(GEMINI_LOCAL_KEY_SWEEP_SIZE)


def gemini_translation_keys_for_operation() -> list[tuple[int, str]]:
    """Translation is the core path: do not let old server env cap it to one key."""
    if gemini_requests_paused_until_refill():
        return []
    if GEMINI_DISABLED_UNTIL and GEMINI_DISABLED_UNTIL > time.time():
        return []
    minimum_keys = max(3, min(len(GEMINI_API_KEYS), GEMINI_MAX_REAL_TRANSLATION_REQUESTS))
    return gemini_key_order_limited(max(GEMINI_LOCAL_KEY_SWEEP_SIZE, minimum_keys))


def cool_down_gemini_key(key: str, error: Exception | None) -> None:
    if should_cool_down_gemini_key(error):
        cooldown = (
            GEMINI_COOLDOWN_SECONDS
            if is_gemini_quota_error(error)
            else GEMINI_TEMPORARY_OVERLOAD_COOLDOWN_SECONDS
            if is_gemini_temporary_overload_error(error)
            else 90
        )
        GEMINI_KEY_COOLDOWNS[key] = time.time() + cooldown
    try:
        daily_stat_increment("gemini_failures", gemini_error_summary(error), 1)
    except Exception:
        pass


def log_gemini_unavailable(error: Exception | None) -> None:
    global GEMINI_FAILURE_LOGGED, GEMINI_DISABLED_UNTIL, GEMINI_COOLDOWN_IS_QUOTA
    if is_gemini_output_validation_error(error):
        if not GEMINI_FAILURE_LOGGED:
            logging.warning("⚠️ פלט Gemini נפסל בבדיקת איכות מקומית. לא מקרר את כל Gemini, והפוסט ידולג/יישמר לפי מנגנון הסינון.")
        GEMINI_FAILURE_LOGGED = True
        return
    GEMINI_COOLDOWN_IS_QUOTA = is_gemini_quota_error(error)
    if GEMINI_QUOTA_GUARD_ENABLED and GEMINI_COOLDOWN_IS_QUOTA:
        set_gemini_requests_pause(True, gemini_error_summary(error))
        GEMINI_DISABLED_UNTIL = 10 ** 12
    elif is_gemini_temporary_overload_error(error):
        GEMINI_DISABLED_UNTIL = time.time() + GEMINI_TEMPORARY_OVERLOAD_COOLDOWN_SECONDS
    else:
        GEMINI_DISABLED_UNTIL = time.time() + GEMINI_COOLDOWN_SECONDS
    if GEMINI_FAILURE_LOGGED:
        return
    GEMINI_FAILURE_LOGGED = True
    logging.warning("⚠️ ג'מיני לא זמין כרגע. הבוט לא ישלח פוסטים בלי תרגום Gemini תקין. סיבה: %s", gemini_error_summary(error))


def mark_gemini_available() -> None:
    global GEMINI_FAILURE_LOGGED, GEMINI_DISABLED_UNTIL, GEMINI_COOLDOWN_IS_QUOTA
    if GEMINI_FAILURE_LOGGED:
        logging.debug("ג'מיני חזר לעבוד")
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


def gemini_translate(text: str, respect_global_cooldown: bool = True, max_real_requests: int = GEMINI_MAX_REAL_TRANSLATION_REQUESTS) -> str:
    if gemini_requests_paused_until_refill():
        raise RuntimeError("Gemini requests are paused until quota refill/manual release")
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
        "- Do not publish ordinary player interviews or admiration quotes, even when they mention a major club, unless the quote itself contains a concrete transfer/contract/injury/official decision.\n"
        "- Keep an interview/quote only when it is genuinely newsworthy or highly relevant: club president/owner/coach/agent speaking about a star player, contract renewal, future at the club, transfer, injury, official decision, squad call-up, bid, club direction or a major sporting development.\n"
        "- Block youth/reserve/academy/B-team reports, including U15-U23, under-23, Primavera, Next Gen, Futuro, Castilla, Atletic/Atlètic, II/B teams, reserve teams, and reports focused on underage birth years/classes.\n"
        "- Remove ordinary statistics-only posts unless they contain a real record, official achievement or current news angle.\n"
        "- Block women's football, women's leagues/teams, WNBA/NBA/NFL/UFC/tennis/basketball and every sport that is not men's football.\n"
        "- Write 1-3 natural Hebrew news sentences unless the original genuinely needs more.\n"
        "- Keep only the actual news. Remove credits, source tags, TV/network tags, junk suffixes, tracking text and promo text.\n"
        "- Remove self/source attribution clauses such as 'as reported by...', 'as revealed by...', 'via...', and Hebrew equivalents like 'כפי שדווח על ידי'. Keep the news fact only, and never leave dangling fragments like 'כפי שדווח על ידי'.\n"
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
        "- Do not exaggerate labels. Translate 'breaking' as 'דיווח' or omit the label; avoid 'דיווח דרמטי' unless the original facts are truly exceptional.\n"
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
    available_keys = gemini_translation_keys_for_operation()
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
            data = http_post_json(url, payload, timeout=GEMINI_TRANSLATION_TIMEOUT_SECONDS, max_attempts=1, respect_retry_after=False)
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
            if should_stop_gemini_key_sweep(exc):
                break
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
        r"שובר|"
        r"חדשות\s+מרעישות|"
        r"חדשות\s+מתפרצות|"
        r"ידיעה\s+מתפרצת|"
        r"מבזק|"
        r"ברייקינג|"
        r"breaking"
    )
    text = re.sub(rf"(?im)^(\s*(?:[^A-Za-z0-9א-ת\n]*\s*)?)(?:{label})\s*[-:–—]?\s*", r"\1דיווח: ", text or "")
    text = re.sub(r"(?im)^(\s*(?:[^A-Za-z0-9א-ת\n]*\s*)?)דיווח\s+דרמטי\s*[-:–—]\s*", r"\1דיווח: ", text)
    text = re.sub(r"(?im)^(\s*(?:[^A-Za-z0-9א-ת\n]*\s*)?)דיווח\s*[-:–—]\s*", r"\1דיווח: ", text)
    return text


def final_hebrew_polish(text: str) -> str:
    text = remove_external_links(text)
    text = remove_weird_symbols(text)
    text = normalize_exclusive_label(text)
    text = normalize_breaking_label(text)
    text = re.sub(r"(?im)^\s*(?:אקסקלוסיב|אקסקלוסיבי|אקסלוסיב|אקסקלוסיב-י)\s*[-:–—]?\s*", "בלעדי: ", text)
    text = apply_handle_replacements(text)
    text = remove_credit_handles(text)
    text = remove_dangling_source_attribution(text)
    text = remove_writer_brag_phrases(text)
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
    text = remove_dangling_source_attribution(text)
    text = remove_writer_brag_phrases(text)
    text = remove_trailing_duplicate_team_tags(text)
    text = normalize_exclusive_label(text)
    text = normalize_breaking_label(text)
    text = re.sub(r"(?im)^\s*(?:אקסקלוסיב|אקסקלוסיבי|אקסלוסיב|אקסקלוסיב-י)\s*[-:–—]?\s*", "בלעדי: ", text)
    text = re.sub(r"(?im)^בלעדי\s*[-:–—]\s*", "בלעדי: ", text)
    text = final_visual_cleanup(text)
    return text.strip()


LIST_STAT_ITEM_MARKERS = ("🥇", "🥈", "🥉", "✅", "❌", "☑️", "✔️", "🔹", "🔸", "▪️", "▫️", "•")


def regional_flag_count(text: str) -> int:
    return len(re.findall(r"[\U0001F1E6-\U0001F1FF]{2}", text or ""))


def add_group_spacing_to_long_list(text: str) -> str:
    # Lists should be readable line-by-line, without blank lines inside the list.
    # Paragraph spacing is added only between the list and surrounding text.
    return text


def format_stat_list_lines(text: str) -> str:
    value = (text or "").strip()
    if not value:
        return value
    marker_count = sum(value.count(marker) for marker in LIST_STAT_ITEM_MARKERS)
    flag_count = regional_flag_count(value)
    has_many_numbered_stats = len(re.findall(r"\(\d+\)", value)) >= 4 and re.search(r"הכי הרבה|most\s+", value, re.IGNORECASE)
    has_dense_inline_list = marker_count >= 4 or flag_count >= 4 or bool(marker_count >= 3 and re.search(r"נבחרות|qualified|העפילו|עלו|מודחות|שלב", value, re.IGNORECASE))
    if not has_dense_inline_list and not has_many_numbered_stats:
        return value

    value = re.sub(r"(?iu)(היום)\.\s+(?=[💥🔥⚽🥇🥈🥉✅🔹🔸▪▫•])", r"\1:\n", value)
    value = re.sub(r"(?iu)\b(today)\.\s+(?=[💥🔥⚽🥇🥈🥉✅🔹🔸▪▫•])", r"\1:\n", value)
    value = re.sub(r"(?<!\n)\s+(?=(?:✅|❌|☑️|✔️)\s+)", "\n", value)
    value = re.sub(r"(?<!\n)\s+(?=[💥🔥⚽]\s+)", "\n", value)
    value = re.sub(r"(?<!\n)\s+(?=(?:🥇|🥈|🥉|✅|❌|☑️|✔️|🔹|🔸|▪️|▫️|•)\s+)", "\n", value)
    value = re.sub(r"(?<=[\U0001F1E6-\U0001F1FF])(?=(?:✅|❌|☑️|✔️))", "\n", value)
    value = re.sub(r"(?m)^((?:✅|❌|☑️|✔️)\s+.*?[\U0001F1E6-\U0001F1FF]{2})\s+(\d+\s+(?:נבחרות|קבוצות|שחקנים)\b.*)$", r"\1\n\n\2", value)
    value = re.sub(r"(\(\d+\))\s+(לא רע\.)", r"\1\n\2", value)
    value = re.sub(r"(?m)^((?:🥇|🥈|🥉)\s+.*?\(\d+\))\s+([^\n]{2,24}\.)$", r"\1\n\2", value)
    value = re.sub(r"(?<=\S)\s+(לא רע\.?)(?=\s*(?:\n|$))", r"\n\1", value)
    value = re.sub(r"(?<=\S)\s+(not bad\.?)(?=\s*(?:\n|$))", r"\n\1", value, flags=re.IGNORECASE)
    value = re.sub(r"(?<=\.)\s+(היום:)", r"\n\n\1", value, count=1)
    value = re.sub(r"(?<=\.)\s+(today:)", r"\n\n\1", value, count=1, flags=re.IGNORECASE)
    value = re.sub(r"(?<=\.)\n(היום:)", r"\n\n\1", value, count=1)
    value = re.sub(r"([.!?״”])\n(היום:)", r"\1\n\n\2", value, count=1)
    value = re.sub(r"(לא רע\.?)\s+([🫲🫱].*)", r"\1\n\n\2", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    value = re.sub(r"[ \t]*\n[ \t]*", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = add_group_spacing_to_long_list(value)
    return value.strip()


def format_news_paragraphs(text: str) -> str:
    value = (text or "").strip()
    value = format_stat_list_lines(value)
    if not value or "\n\n" in value or len(value) < 170:
        return value
    sentences = re.split(r"(?<=[.!?])\s+", value)
    if len(sentences) <= 2:
        return value
    paragraphs: list[str] = []
    current: list[str] = []
    current_len = 0
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        current.append(sentence)
        current_len += len(sentence)
        if len(current) >= 2 or current_len >= 230:
            paragraphs.append(" ".join(current).strip())
            current = []
            current_len = 0
    if current:
        paragraphs.append(" ".join(current).strip())
    if len(paragraphs) <= 1:
        return value
    return "\n\n".join(paragraphs)


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
    global TRANSLATION_CACHE_DIRTY
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
                    TRANSLATION_CACHE_DIRTY = True
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

    logging.error("⛔ אין תרגום תקין. הפוסט לא יישלח.")
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
        logging.debug("חיסכון Gemini: ציטוט לא תורגם כי TRANSLATE_QUOTED_POSTS כבוי")
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
    text = remove_writer_noise_for_event_matching(text)
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
    text = remove_writer_noise_for_event_matching(text)
    text = final_visual_cleanup(text)
    return text.strip()


def polish_team_names_with_original_context(post: Post, text: str) -> str:
    value = text or ""
    original = html.unescape("\n".join([post.text or "", post.quoted_text or ""]))
    original_has_tottenham = bool(re.search(r"\bTottenham(?:\s+Hotspur)?\b|טוטנהאם", original, re.IGNORECASE))
    original_has_spurs = bool(re.search(r"\bSpurs\b|ספרס", original, re.IGNORECASE))
    if original_has_tottenham or original_has_spurs:
        value = re.sub(r"(?iu)\bה?ספרס\b", "טוטנהאם", value)
    value = re.sub(r"(?iu)(?<![\wא-ת])ספרס(?![\wא-ת])", "טוטנהאם", value)
    value = re.sub(r"(?iu)וספרס\b", "וטוטנהאם", value)
    if re.search(r"(?iu)\bround\s+of\s+32\b|last\s+32|שלב\s+32", original):
        value = re.sub(r"(?iu)שמינית\s+גמר(?:\s+המונדיאל|\s+גביע\s+העולם)?", "שלב 32 הגדולות", value)
    return value


def should_hide_writer_header(post: Post, translated: str) -> bool:
    source = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or "", translated or ""])))
    if not source:
        return False
    if is_world_cup_bracket_or_qualification_noise(post):
        return True
    transfer_or_coach_news = _matches_any(TRANSFER_OR_FUTURE_PATTERNS, source) or _matches_any(COACH_IMPORTANT_PATTERNS, source)
    if not transfer_or_coach_news and re.search(r"(?iu)\bWorld Cup\b|מונדיאל|גביע העולם|נבחרות|העפילו|שלב\s+32", source):
        return True
    national_context = _matches_any(MAJOR_NATIONAL_TEAM_CONTEXT_PATTERNS, source) or matches_managed_team_tier("national", source)
    club_context = (
        _matches_any(ALLOWED_CLUB_PATTERNS, source)
        or _matches_any(FINAL_ONLY_ALLOWED_CLUB_PATTERNS, source)
        or matches_managed_team_tier("tier1", source)
        or matches_managed_team_tier("tier2", source)
        or matches_managed_team_tier("tier3", source)
        or _matches_any(ISRAELI_LEAGUE_PATTERNS, source)
    )
    soft_national_update = bool(
        national_context
        and not transfer_or_coach_news
        and (
            _matches_any(MATCH_RESULT_OR_ENGAGEMENT_PATTERNS, source)
            or _matches_any(INJURY_OR_FITNESS_UPDATE_PATTERNS, source)
            or is_stats_only_post(source)
            or re.search(r"(?iu)\b(?:player of the match|man of the match|motm|stats?)\b|שחקן מצטיין|איש המשחק|שער\s*\+\s*בישול|הכי הרבה|סטטיסט", source)
        )
    )
    return bool((national_context and not club_context and not transfer_or_coach_news) or soft_national_update)


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


def _telegram_message_id_from_response(response: dict[str, Any]) -> int | None:
    result = response.get("result")
    if isinstance(result, dict):
        message_id = result.get("message_id")
        return int(message_id) if message_id else None
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict) and first.get("message_id"):
            return int(first["message_id"])
    return None


def telegram_broadcast(method: str, payload: dict[str, Any], reply_message_ids: dict[str, int] | None = None) -> dict[str, int]:
    sent_count = 0
    errors: list[str] = []
    message_ids: dict[str, int] = {}
    for chat_id in TELEGRAM_CHAT_IDS:
        chat_payload = dict(payload)
        chat_payload["chat_id"] = chat_id
        reply_id = (reply_message_ids or {}).get(str(chat_id))
        if reply_id:
            chat_payload["reply_to_message_id"] = int(reply_id)
            chat_payload["allow_sending_without_reply"] = True
        try:
            response = telegram_api(method, chat_payload)
            sent_count += 1
            message_id = _telegram_message_id_from_response(response)
            if message_id:
                message_ids[str(chat_id)] = message_id
            logging.info("✅ טלגרם: %s נשלח בהצלחה לערוץ %s", method, chat_id)
        except Exception as exc:
            errors.append(f"{chat_id}: {exc}")
            logging.error("⛔ טלגרם: %s נכשל לערוץ %s, ממשיך לערוצים האחרים: %s", method, chat_id, exc)
    if sent_count == 0:
        raise RuntimeError("Telegram broadcast failed for all chats: " + " | ".join(errors))
    return message_ids


def telegram_broadcast_with_text_fallback(method: str, payload: dict[str, Any], fallback_text: str, reply_message_ids: dict[str, int] | None = None) -> dict[str, int]:
    sent_count = 0
    errors: list[str] = []
    message_ids: dict[str, int] = {}
    for chat_id in TELEGRAM_CHAT_IDS:
        chat_payload = dict(payload)
        chat_payload["chat_id"] = chat_id
        reply_id = (reply_message_ids or {}).get(str(chat_id))
        if reply_id:
            chat_payload["reply_to_message_id"] = int(reply_id)
            chat_payload["allow_sending_without_reply"] = True
        try:
            response = telegram_api(method, chat_payload)
            sent_count += 1
            message_id = _telegram_message_id_from_response(response)
            if message_id:
                message_ids[str(chat_id)] = message_id
            logging.info("✅ טלגרם: %s נשלח בהצלחה לערוץ %s", method, chat_id)
            continue
        except Exception as exc:
            errors.append(f"{chat_id} {method}: {exc}")
            logging.error("⛔ טלגרם: %s נכשל לערוץ %s. מנסה לשלוח טקסט רגיל לאותו ערוץ: %s", method, chat_id, exc)

        try:
            fallback_payload = {
                "chat_id": chat_id,
                "text": trim(fallback_text, 4096),
                "disable_web_page_preview": True,
                "parse_mode": "HTML",
            }
            if reply_id:
                fallback_payload["reply_to_message_id"] = int(reply_id)
                fallback_payload["allow_sending_without_reply"] = True
            response = telegram_api("sendMessage", fallback_payload)
            sent_count += 1
            message_id = _telegram_message_id_from_response(response)
            if message_id:
                message_ids[str(chat_id)] = message_id
            logging.info("✅ טלגרם: טקסט גיבוי נשלח בהצלחה לערוץ %s", chat_id)
        except Exception as fallback_exc:
            errors.append(f"{chat_id} fallback: {fallback_exc}")
            logging.error(
                "⛔ טלגרם: גם טקסט גיבוי נכשל לערוץ %s. אם זה הערוץ %s, צריך לבדוק שהבוט אדמין עם הרשאה לפרסם הודעות: %s",
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
    return message_ids


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
    translated = format_news_paragraphs(translated)
    display_name = ACCOUNT_DISPLAY_NAMES.get(post.username, post.username)

    safe_account = html.escape(rtl(f"{display_name}:"))
    safe_body = html.escape(rtl(translated or "עדכון חדש"))
    safe_quoted_author = html.escape(rtl(quoted_author_translated))
    safe_quoted_body = html.escape(rtl(f'"{quoted_translated}"')) if quoted_translated else ""
    quote_label = f"<b>{html.escape(rtl('פוסט מצוטט:'))}</b>"
    signature = f'<a href="{html.escape(SIGNATURE_LINK)}">{html.escape(rtl(SIGNATURE_TEXT))}</a>'

    if should_hide_writer_header(post, translated):
        parts = [safe_body]
    else:
        parts = [f"<b>{safe_account}</b>", "", safe_body]

    if safe_quoted_body:
        parts.append("")
        if safe_quoted_author:
            parts.append(quote_label)
            parts.append(safe_quoted_author)
        parts.append(safe_quoted_body)
    parts.extend(["", signature])

    return "\n".join(parts)


def selected_post_images(post: Post) -> list[str]:
    if post.has_video:
        return []
    images = list(dict.fromkeys(post.image_urls))[:MAX_IMAGES_PER_POST]
    if len(images) <= 1:
        return images
    text = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    if _matches_any(FINAL_ONLY_STRICT_PATTERNS, text) or _matches_any(FINAL_OR_NEAR_FINAL_PATTERNS, text):
        return images[:1]
    return images





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
    r"רשמי|אושר|אישר|אישרה|הודיע|הודיעה|הודעה רשמית|חתם|חתמה|יחתום|תחתום|צפוי לחתום|צפויה לחתום|צפוי להצטרף|צפויה להצטרף|הנה זה קורה|הנה זה בא|עסקה סגורה|העסקה סגורה|העסקה הושלמה|העסקה סוכמה|סוכמה העסקה|סיכום מלא|הושג סיכום|סיכום בעל פה|סיכום עם|סיכום על|סוכמו התנאים|בדיקות רפואיות|נקבעו בדיקות|מסמכים נחתמו|חוזים נחתמו|הושלם|הושלמה|נסגר|נסגרה|פרטים אחרונים|בשלבים האחרונים|צעד אחד מסגירה|קרוב לסגירה|קרובה לסגירה|מיידי|צפוי להיסגר|אור ירוק|הצעה התקבלה|ההצעה התקבלה",
)

FINAL_ONLY_STRICT_PATTERNS = (
    r"\b(?:official|confirmed|announced|announcement|club statement|signed|has signed|done deal|deal done|deal agreed|agreement reached|full agreement|documents signed|contracts signed|completed|sealed|approved|accepted bid|bid accepted)\b",
    r"רשמי|אושר|אישר|אישרה|הודיע|הודיעה|הודעה רשמית|חתם|חתמה|חתמו|חתימה רשמית|הנה זה בא|הנה זה קורה|העסקה סגורה|עסקה סגורה|העסקה הושלמה|העסקה סוכמה|סוכמה העסקה|סיכום מלא|הושג סיכום|סיכום עם|סיכום על|מסמכים נחתמו|חוזים נחתמו|הושלם|הושלמה|נסגר|נסגרה|הצעה התקבלה|ההצעה התקבלה",
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
    r"\b(?:Milan Futuro|AC Milan Futuro|Juventus Next Gen|Juve Next Gen|Atalanta U-?23|Real Madrid Castilla|Barca Atletic|Barça Atlètic|Barcelona Atletic|Barcelona Atlètic|Bayern II|Borussia Dortmund II|Dortmund II|Ajax Jong|Jong Ajax|Jong PSV|Jong AZ|Jong Utrecht|Benfica B|Porto B|Sporting CP B|Real Sociedad B|Villarreal B|Sevilla Atletico|Sevilla Atlético|Athletic Bilbao B|Valencia Mestalla|Freiburg II|Stuttgart II|Hoffenheim II|Mainz II|Wolfsburg II|Leipzig U-?19|Chelsea U-?21|Liverpool U-?21|Arsenal U-?21|Man City U-?21|Manchester City U-?21|Man United U-?21|Manchester United U-?21|Tottenham U-?21|Spurs U-?21)\b",
    r"\b(?:[A-Z][A-Za-zÀ-ÿ'’.-]+(?:\s+[A-Z][A-Za-zÀ-ÿ'’.-]+){0,3})\s+(?:II|B|U-?23|U-?21|U-?19|Futuro|Next\s+Gen|Castilla|Atletic|Atlètic|Primavera|Mestalla)\b",
    r"מחלקת נוער|קבוצת נוער|נוער|נערים|נערים א|נערים ב|ילדים|אקדמיה|קבוצת מילואים|מילואים|קבוצת עתודה|עתודה|קבוצת בת|קבוצת ב׳|קבוצת ב'|עד גיל\s*(?:15|16|17|18|19|20|21|23)|U ?(?:15|16|17|18|19|20|21|23)",
    r"מילאן\s+פוטורו|יובנטוס\s+נקסט\s+ג'?ן|ריאל\s+מדריד\s+קסטיליה|ברצלונה\s+אתלטיק|בארסה\s+אתלטיק|באיירן\s+2|באיירן\s+II|דורטמונד\s+2|דורטמונד\s+II|אייאקס\s+יונג|יונג\s+אייאקס|בנפיקה\s+B|פורטו\s+B|ספורטינג\s+B|ויאריאל\s+B|ריאל\s+סוסיאדד\s+B|ולנסיה\s+מסטאייה",
)


def has_underage_birth_year_signal(text: str) -> bool:
    if not text:
        return False
    current_year = time.localtime().tm_year
    patterns = (
        r"\b(?:born|born in|born on|class of|generation|year group)\s+(20\d{2})\b",
        r"\b(20\d{2})\s*(?:born|birth year|class|generation)\b",
        r"(?:יליד|נולד\s+ב|נולד\s+בשנת|שנתון|מחזור)\s*(20\d{2})",
        r"(20\d{2})\s*(?:יליד|שנתון|מחזור)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            try:
                birth_year = int(match.group(1))
            except Exception:
                continue
            if 8 <= current_year - birth_year <= 18:
                return True
    return False


def is_youth_or_academy_post(post: Post) -> bool:
    cleaned = post_filter_text(post)
    return _matches_any(YOUTH_ACADEMY_BLOCK_PATTERNS, cleaned) or has_underage_birth_year_signal(cleaned)


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
    return (
        (_matches_any(ALLOWED_NATIONAL_TEAM_PATTERNS, cleaned) or matches_managed_team_tier("national", cleaned))
        and _matches_any(NATIONAL_TEAM_CONTEXT_PATTERNS, cleaned)
    )


def contains_allowed_club_or_israeli_league(post: Post) -> bool:
    cleaned = post_filter_text(post)
    return (
        _matches_any(ALLOWED_CLUB_PATTERNS, cleaned)
        or matches_managed_team_tier("tier1", cleaned)
        or has_central_player_affiliation(cleaned, {"tier1"})
        or _matches_any(ISRAELI_LEAGUE_PATTERNS, cleaned)
        or contains_allowed_national_team(post)
    )


def contains_tracked_club_or_israeli_league(post: Post) -> bool:
    """User club gate: tier 1, tier 2/final-only, Israeli league or allowed national teams."""
    cleaned = post_filter_text(post)
    return (
        _matches_any(ALLOWED_CLUB_PATTERNS, cleaned)
        or _matches_any(FINAL_ONLY_ALLOWED_CLUB_PATTERNS, cleaned)
        or matches_managed_team_tier("tier1", cleaned)
        or matches_managed_team_tier("tier2", cleaned)
        or matches_managed_team_tier("tier3", cleaned)
        or has_central_player_affiliation(cleaned, {"tier1", "tier2", "tier3", "national"})
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
    r"\b(?:Brighton|Bournemouth|Brentford|Fulham|Wolves|Everton|West Ham|Crystal Palace|Nottingham Forest|Leeds|Sunderland|Leicester|Southampton|Burnley|Aston Villa|Newcastle)\b",
    r"\b(?:Genoa|Cagliari|Como|Lecce|Udinese|Sassuolo|Bologna|Torino|Monza|Verona|Parma|Sampdoria|Pisa|Cremonese|Salernitana)\b",
    r"\b(?:Getafe|Osasuna|Mallorca|Rayo Vallecano|Alaves|Alavés|Celta Vigo|Espanyol|Levante|Malaga|Málaga|Racing Santander|Leganes|Leganés|Granada|Las Palmas|Valladolid|Girona)\b",
    r"\b(?:Toulouse|Metz|Nice|Strasbourg|Lens|Auxerre|Angers|Lorient|Paris FC|Saint-Étienne|Saint Etienne)\b",
    r"\b(?:Bochum|Mainz|Freiburg|Heidenheim|St Pauli|Werder Bremen|Wolfsburg|Union Berlin|Hoffenheim|Hamburg|Koln|Köln|Darmstadt|Holstein Kiel)\b",
    r"ברייטון|בורנמות|ברנטפורד|פולהאם|וולבס|אברטון|ווסטהאם|קריסטל פאלאס|נוטינגהאם|לידס|סנדרלנד|לסטר|סאות'המפטון|ברנלי|אסטון וילה|ניוקאסל",
    r"גנואה|קליארי|קומו|לצ'ה|אודינזה|ססואולו|בולוניה|טורינו|מונצה|ורונה|פארמה|סמפדוריה|פיזה|קרמונזה",
    r"חטאפה|אוססונה|מיורקה|ראיו|אלאבס|סלטה|אספניול|לבאנטה|מלאגה|ראסינג|ראסינג סנטנדר|לגאנס|גרנאדה|לאס פאלמאס|ויאדוליד|ג'ירונה",
    r"טולוז|מץ|ניס|שטרסבורג|לאנס|אוקזר|אנז'ה|לוריין|פאריס FC|סנט אטיין",
    r"בוכום|מיינץ|פרייבורג|היידנהיים|סט פאולי|ורדר ברמן|וולפסבורג|אוניון ברלין|הופנהיים|המבורג|קלן|דרמשטאדט|הולשטיין קיל",
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
    r"\b(?:interest|interested|monitoring|tracking|keeping tabs|admire|considering|could|might|eyeing|linked with|on the list|shortlist|inquired|enquired|exploring|watching|following|asked for|requested|no agreement|no deal|talks stalled)\b",
    r"מתעניין|מתעניינת|מעוניין|מעוניינת|מגלה עניין|מגלים עניין|גילה עניין|גילו עניין|הביע(?:ו)? עניין|עוקב(?:ת|ים)?|שוקל(?:ת|ים)?|עשוי|יכולה|מקושר|ברשימה|ברשימת המועמדים|בירר(?:ה|ו)?|בודק(?:ת|ים)?|נמצא במעקב|פתח(?:ה|ו)? שיחות|נפתחו שיחות|שיחות ראשוניות|מגעים ראשוניים|ביקשו|מבקשת|אין הסכמה|אין עסקה|השיחות נתקעו",
)

NON_ELITE_LOOSE_TRANSFER_PATTERNS = (
    r"\b(?:interest|interested|monitoring|tracking|keeping tabs|considering|could|might|eyeing|linked with|on the list|shortlist|inquired|enquired|exploring|watching|following|asked for|requested|opened talks|open talks|talks opened|initial talks|preliminary talks|contacts?|no agreement|no deal|talks stalled)\b",
    r"גיל(?:ה|ו)\s+עניין|מגל(?:ה|ים)\s+עניין|הביע(?:ה|ו)?\s+עניין|מתעניינ(?:ת|ים)|מעוניינ(?:ת|ים)|פתח(?:ה|ו)?\s+שיחות|נפתחו\s+שיחות|שיחות\s+(?:ראשוניות|פתוחות|נמשכות)|מגעים\s+(?:ראשוניים|נמשכים)|בירר(?:ה|ו)?|בודק(?:ת|ים)?|בדק(?:ה|ו)?|פנ(?:ה|תה|ו)|עוקב(?:ת|ים)?|במעקב|נמצא\s+במעקב|ברשימה|ברשימת\s+המועמדים|מועמד(?:ת|ים)?|מקושר(?:ת|ים)?|אין\s+סיכום|אין\s+הסכמה|אין\s+עסקה|השיחות\s+נתקעו",
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
    r"רשמי|אושר|הנה זה קורה|הנה זה בא|העסקה סוכמה|הושג סיכום|סיכום מלא|סיכום בעל פה|סיכום עם|סיכום על|צפוי לחתום|צפוי להצטרף|קרוב לחתימה|קרוב להצטרף|בדיקות רפואיות|החוזה נחתם|חתם|יחתום|מצטרף|עסקה סגורה|ההצעה התקבלה|סעיף שחרור|שחקן חופשי|העברה קבועה|השאלה סוכמה",
)

CLEAR_PLAYER_DEPARTURE_PATTERNS = (
    r"\b(?:leaves?|leaving|left|departs?|departing|released|out of contract|contract expires?|free agent|free transfer)\b",
    r"עוזב|עוזבת|עזב|עזבה|יעזוב|תעזוב|שוחרר|שוחררה|משוחרר|מסיים חוזה|סיים חוזה|תום חוזה|שחקן חופשי|העברה חופשית",
)

COACH_IMPORTANT_PATTERNS = (
    r"\b(?:head coach|manager|coach|appointed|set to be appointed|sacked|fired|dismissed|resigned|leaves role|new manager|new head coach)\b",
    r"מאמן|מאמן ראשי|על הקווים|לקווים|ספסל|מונה|ימונה|צפוי להתמנות|פוטר|התפטר|עזב את תפקידו|מאמן חדש",
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

BIG_CLUB_AS_MAIN_BUYER_PATTERNS = (
    r"\b(?:Real Madrid|Barcelona|Barca|Barça|Atletico Madrid|Atlético Madrid|Manchester United|Man United|Man Utd|Manchester City|Man City|Liverpool|Arsenal|Chelsea|Tottenham|Spurs|Bayern Munich|Bayern|Borussia Dortmund|Dortmund|Bayer Leverkusen|Leverkusen|PSG|Paris Saint-Germain|Juventus|Inter Milan|Inter|AC Milan|Milan|Napoli|Roma)\b.{0,120}\b(?:interest|interested|monitoring|tracking|eyeing|shortlist|considering|bid|offer|proposal|submit|prepare|ready|expected|set|trying|push(?:ing)?|working|talks|negotiations|advance|close|closing|complete|seal|buy|bring)\b",
    r"\b(?:interest|interested|monitoring|tracking|eyeing|shortlist|considering|bid|offer|proposal|submit|prepare|ready|expected|set|trying|push(?:ing)?|working|talks|negotiations|advance|close|closing|complete|seal|buy|bring)\b.{0,120}\b(?:Real Madrid|Barcelona|Barca|Barça|Atletico Madrid|Atlético Madrid|Manchester United|Man United|Man Utd|Manchester City|Man City|Liverpool|Arsenal|Chelsea|Tottenham|Spurs|Bayern Munich|Bayern|Borussia Dortmund|Dortmund|Bayer Leverkusen|Leverkusen|PSG|Paris Saint-Germain|Juventus|Inter Milan|Inter|AC Milan|Milan|Napoli|Roma)\b",
    r"(?:ריאל מדריד|ברצלונה|בארסה|אתלטיקו מדריד|מנצ'סטר יונייטד|מנצ'סטר סיטי|ליברפול|ארסנל|צ'לסי|טוטנהאם|באיירן(?: מינכן)?|דורטמונד|לברקוזן|פ\.ס\.ז|פריז סן ז'רמן|יובנטוס|אינטר|מילאן|נאפולי|רומא).{0,120}(?:גילתה עניין|גילו עניין|מגלה עניין|מגלים עניין|מעוניינת|מעוניינים|עוקבת|עוקבים|ברשימה|ברשימת המועמדים|הצעה|תציע|צפויה להגיש|צפוי להגיש|מכינה|מכין|מנסה|דוחפת|דוחף|בשיחות|מגעים|מו\"מ|מתקדמת|מתקדם|קרובה|קרוב|לסגור|להשלים|להחתים|לרכוש)",
    r"(?:גילתה עניין|גילו עניין|מגלה עניין|מגלים עניין|מעוניינת|מעוניינים|עוקבת|עוקבים|ברשימה|ברשימת המועמדים|הצעה|תציע|צפויה להגיש|צפוי להגיש|מכינה|מכין|מנסה|דוחפת|דוחף|בשיחות|מגעים|מו\"מ|מתקדמת|מתקדם|קרובה|קרוב|לסגור|להשלים|להחתים|לרכוש).{0,120}(?:ריאל מדריד|ברצלונה|בארסה|אתלטיקו מדריד|מנצ'סטר יונייטד|מנצ'סטר סיטי|ליברפול|ארסנל|צ'לסי|טוטנהאם|באיירן(?: מינכן)?|דורטמונד|לברקוזן|פ\.ס\.ז|פריז סן ז'רמן|יובנטוס|אינטר|מילאן|נאפולי|רומא)",
)


def has_big_club_as_main_buyer(cleaned: str) -> bool:
    return _matches_any(BIG_CLUB_AS_MAIN_BUYER_PATTERNS, cleaned)

# Transfer/future language broad enough to catch quotes like "his son wants Napoli",
# but still specific enough to block ordinary post-match interviews.
TRANSFER_OR_FUTURE_PATTERNS = (
    r"\b(?:transfer|move|join|joining|sign|signing|leave|leaving|return|back to|future|loan|buy option|option to buy|purchase option|clause|release clause|bid|offer|proposal|talks|negotiations|agreement|medical|deal|contract|free agent|wants? to|would like to|keen to|open to|dreams? of)\b",
    r"העברה|מעבר|לעבור|להצטרף|חתימה|יחתום|יחתמו|יחתמו על החוזים|יעזוב|לעזוב|לחזור|חזרה ל|עתידו|עתיד ב|השאלה|אופציית רכישה|אופציית הקנייה|סעיף שחרור|הצעה|שיחות|מו\"מ|משא ומתן|סיכום|הסכמה|תנאים אישיים|בדיקות רפואיות|עסקה|חוזה|חוזים|שחקן חופשי|רוצה|מעוניין|מעוניינת|חולם|פתוח להצטרף",
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


def is_extra_strict_source(post: Post) -> bool:
    return (getattr(post, "username", "") or "") in EXTRA_STRICT_SOURCE_ACCOUNTS


def is_non_elite_loose_transfer_report(cleaned: str) -> bool:
    """Block low-certainty transfer chatter unless the main club is truly elite."""
    if not cleaned or not _matches_any(NON_ELITE_LOOSE_TRANSFER_PATTERNS, cleaned):
        return False
    if (
        _matches_any(FINAL_ONLY_STRICT_PATTERNS, cleaned)
        or _matches_any(STRONG_PLAYER_MOVE_PATTERNS, cleaned)
        or has_big_club_as_main_buyer(cleaned)
        or _matches_any(BIG_CLUB_CONTEXT_PATTERNS, cleaned)
        or matches_managed_team_tier("tier1", cleaned)
        or has_central_player_affiliation(cleaned, {"tier1"})
        or _matches_any(MAJOR_NATIONAL_TEAM_CONTEXT_PATTERNS, cleaned)
    ):
        return False
    tracked_lower_tier = (
        _matches_any(FINAL_ONLY_ALLOWED_CLUB_PATTERNS, cleaned)
        or matches_managed_team_tier("tier2", cleaned)
        or matches_managed_team_tier("tier3", cleaned)
        or has_central_player_affiliation(cleaned, {"tier2", "tier3"})
    )
    known_non_elite_top_league = _matches_any(POPULAR_OR_RECENT_UCL_CLUB_PATTERNS, cleaned) and not _matches_any(BIG_CLUB_RUMOR_PATTERNS, cleaned)
    return bool(tracked_lower_tier or known_non_elite_top_league)


def is_untracked_transfer_or_staff_news(post: Post) -> bool:
    """Transfer/contract/coach reports must name a team the user actually tracks."""
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    if not cleaned:
        return False
    has_market_or_staff_news = (
        _matches_any(TRANSFER_OR_FUTURE_PATTERNS, cleaned)
        or _matches_any(STRONG_PLAYER_MOVE_PATTERNS, cleaned)
        or _matches_any(COACH_IMPORTANT_PATTERNS, cleaned)
        or _matches_any(ADMIN_OR_BACKROOM_ROLE_PATTERNS, cleaned)
        or _matches_any(FINAL_OR_NEAR_FINAL_PATTERNS, cleaned)
        or _matches_any(FINAL_ONLY_STRICT_PATTERNS, cleaned)
    )
    if not has_market_or_staff_news:
        return False
    if contains_tracked_club_or_israeli_league(post):
        return False
    if (
        has_big_club_as_main_buyer(cleaned)
        or _matches_any(BIG_CLUB_CONTEXT_PATTERNS, cleaned)
        or matches_managed_team_tier("tier1", cleaned)
        or _matches_any(MAJOR_NATIONAL_TEAM_CONTEXT_PATTERNS, cleaned)
    ):
        return False
    return True


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
    cleaned = clean_for_ai_translation(text)
    return _matches_any(FINAL_ONLY_ALLOWED_CLUB_PATTERNS, cleaned) or matches_managed_team_tier("tier2", cleaned)


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
    if is_contextless_teaser_post(post):
        return False, "contextless_teaser", 0, ["contextless_teaser"]
    if is_unclear_subject_news_post(post):
        return False, "unclear_subject_news", 0, ["unclear_subject_news"]
    if is_vague_status_without_primary_context(post):
        return False, "vague_status_without_primary_context", 0, ["vague_status_without_primary_context"]
    if is_untracked_transfer_or_staff_news(post):
        return False, "untracked_transfer_or_staff_news", 0, ["untracked_transfer_or_staff_news"]
    if not contains_tracked_club_or_israeli_league(post):
        logging.debug("פוסט של %s נפסל בסינון האיכות: לא קשור לקבוצה ברשימות הדרגים.", post.username)
        return False, "not_connected_to_tracked_club", 0, ["no_tracked_club"]
    if is_other_sport_post(post):
        return False, "other_sport", 0, ["other_sport"]
    if is_youth_or_academy_post(post):
        return False, "youth_or_academy", 0, ["youth_or_academy"]
    if is_interview_post(post):
        return False, "interview_blocked", 0, ["interview"]
    if is_lineup_or_teamsheet_post(post):
        return False, "lineup_or_teamsheet", 0, ["lineup"]
    if is_poll_or_audience_post(post):
        return False, "poll_or_audience", 0, ["poll_or_audience"]
    if is_live_goal_or_match_moment_post(post):
        return False, "live_goal_or_match_moment", 0, ["live_goal_or_match_moment"]
    if is_match_context_noise_post(post):
        return False, "match_context_noise", 0, ["match_context_noise"]
    if is_media_without_report_post(post):
        return False, "media_without_report", 0, ["media_without_report"]
    if is_too_short_without_strong_news_post(post):
        return False, "too_short_without_strong_news", 0, ["too_short_without_strong_news"]
    if is_name_without_news_action_post(post):
        return False, "name_without_news_action", 0, ["name_without_news_action"]
    if is_unclear_main_club_context_post(post):
        return False, "unclear_main_club_context", 0, ["unclear_main_club_context"]
    if is_weak_copy_without_primary_value_post(post):
        return False, "weak_copy_without_primary_value", 0, ["weak_copy_without_primary_value"]
    if is_writer_profile_noise_post(post):
        return False, "writer_profile_noise", 0, ["writer_profile_noise"]
    central_player_tiers = central_player_affiliation_tiers(cleaned)
    has_central_tier1_player = "tier1" in central_player_tiers
    has_central_tier2_player = "tier2" in central_player_tiers
    has_central_tier3_player = "tier3" in central_player_tiers
    has_allowed_interest_club = contains_allowed_club_or_israeli_league(post)
    has_final_only_club = _matches_any(FINAL_ONLY_ALLOWED_CLUB_PATTERNS, cleaned) or matches_managed_team_tier("tier2", cleaned) or has_central_tier2_player
    has_tier3_club = matches_managed_team_tier("tier3", cleaned) or has_central_tier3_player
    has_big_club_main_buyer = has_big_club_as_main_buyer(cleaned)
    has_big_rumor_club = (_matches_any(BIG_CLUB_RUMOR_PATTERNS, cleaned) or matches_managed_team_tier("tier1", cleaned) or has_central_tier1_player) and (not has_final_only_club or has_big_club_main_buyer)
    has_top5_or_promoted_club = _matches_any(POPULAR_OR_RECENT_UCL_CLUB_PATTERNS, cleaned) or matches_managed_team_tier("tier2", cleaned) or matches_managed_team_tier("tier3", cleaned) or has_central_tier2_player or has_central_tier3_player
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
    has_big_club_context = _matches_any(BIG_CLUB_CONTEXT_PATTERNS, cleaned) or matches_managed_team_tier("tier1", cleaned) or has_central_tier1_player
    has_pure_admin_appointment = _matches_any(PURE_ADMIN_APPOINTMENT_PATTERNS, cleaned)
    has_injury = _matches_any(INJURY_PATTERNS, cleaned)
    has_serious_injury = _matches_any(SERIOUS_INJURY_PATTERNS, cleaned)
    has_injury_or_fitness_update = _matches_any(INJURY_OR_FITNESS_UPDATE_PATTERNS, cleaned)
    has_major_national_context = _matches_any(MAJOR_NATIONAL_TEAM_CONTEXT_PATTERNS, cleaned) or matches_managed_team_tier("national", cleaned)
    has_final_or_near_final = _matches_any(FINAL_OR_NEAR_FINAL_PATTERNS, cleaned)
    has_final_only_strict = _matches_any(FINAL_ONLY_STRICT_PATTERNS, cleaned)
    has_non_elite_loose_transfer = is_non_elite_loose_transfer_report(cleaned)
    has_lower_tier_context = has_final_only_club or has_tier3_club
    has_staff_or_coach_context = has_coach_news or has_admin_role or has_known_admin_person_status or has_pure_admin_appointment
    has_elite_or_national_context = has_big_rumor_club or has_big_club_context or has_big_club_main_buyer or has_major_national_context
    has_clear_final_step = has_final_only_strict or has_strong_move or has_clear_departure
    is_strict_writer = is_extra_strict_source(post)

    if has_small_total_transfer_fee(post):
        return False, "small_transfer_fee", 0, ["small_transfer_fee"]

    if is_minor_destination_from_big_club_source(post):
        return False, "minor_destination_from_big_club", 0, ["minor_destination_from_big_club"]

    untracked_destination = explicit_untracked_destination_club(post)
    if untracked_destination:
        return False, "untracked_destination_club", 0, ["untracked_destination", untracked_destination]

    if has_staff_or_coach_context and has_lower_tier_context and not (has_elite_admin_club and has_final_only_strict) and not has_elite_or_national_context:
        return False, "lower_tier_staff_or_coach_noise", 0, ["lower_tier", "staff_or_coach"]

    if has_tier3_club and not (has_clear_final_step or has_elite_or_national_context):
        return False, "tier3_not_final_enough", 0, ["tier3", "not_final_enough"]

    if is_strict_writer:
        strict_has_strength = (
            has_final_only_strict
            or (has_strong_move and (has_allowed_interest_club or has_elite_or_national_context))
            or (has_clear_departure and (has_allowed_interest_club or has_elite_or_national_context))
            or (has_serious_injury and (has_big_club_context or has_major_national_context))
            or (has_big_club_main_buyer and has_transfer_or_future and has_final_or_near_final)
        )
        if has_staff_or_coach_context and not (has_elite_admin_club and has_final_only_strict):
            return False, "strict_writer_staff_or_coach_noise", 0, ["strict_writer", "staff_or_coach"]
        if (has_weak_interest or has_vague_player_idea or has_non_elite_loose_transfer) and not strict_has_strength:
            return False, "strict_writer_not_strong_enough", 0, ["strict_writer", "weak_or_vague"]
        if has_lower_tier_context and not (has_final_only_strict or has_big_club_main_buyer or has_big_club_context):
            return False, "strict_writer_not_strong_enough", 0, ["strict_writer", "lower_tier_not_final"]
        if not strict_has_strength:
            return False, "strict_writer_not_strong_enough", 0, ["strict_writer", "not_strong"]

    if has_non_elite_loose_transfer:
        return False, "non_elite_loose_transfer_talk", 0, ["non_elite", "loose_transfer_talk"]

    # For the user's lower-priority club group, block pure rumours/loose interest.
    # Keep normal rules if a major club is also part of the same report, or when the
    # post is really about a national team / country squad.
    if has_final_only_club and not has_final_only_strict and not has_big_club_main_buyer:
        return False, "final_only_club_not_strict_final", 0, ["final_only_club", "not_strict_final"]

    if has_tier3_club and has_weak_interest and not (has_big_club_main_buyer or has_big_club_context or has_final_only_strict):
        return False, "tier3_weak_interest", 0, ["tier3", "weak_interest"]

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
    if has_big_club_main_buyer:
        add(35, "big_club_main_buyer")
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


def temporary_control_filter_block_reason(post: Post) -> str:
    state = load_control_state()
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    low = cleaned.lower()
    if bool(state.get("block_social", False)) and is_non_news_social_post(post):
        return "control_block_social"
    if bool(state.get("block_injuries", False)) and _matches_any(INJURY_OR_FITNESS_UPDATE_PATTERNS, cleaned):
        return "control_block_injuries"
    if bool(state.get("block_national", False)) and _matches_any(MAJOR_NATIONAL_TEAM_CONTEXT_PATTERNS, cleaned):
        return "control_block_national"
    if bool(state.get("block_rumors", False)) and _matches_any(TRANSFER_OR_FUTURE_PATTERNS, cleaned) and not _matches_any(FINAL_OR_NEAR_FINAL_PATTERNS, cleaned):
        return "control_block_rumors"
    if bool(state.get("only_herewego", False)) and "here we go" not in low and "הנה זה קורה" not in cleaned:
        return "control_only_herewego"
    if bool(state.get("only_top5", False)) and not _matches_any(BIG_CLUB_RUMOR_PATTERNS, cleaned) and not _matches_any(POPULAR_OR_RECENT_UCL_CLUB_PATTERNS, cleaned) and not matches_managed_team_tier("tier3", cleaned):
        return "control_only_top5"
    if bool(state.get("only_real_barca", False)) and not re.search(r"ברצלונה|בארסה|barcelona|barca|fc barcelona|ריאל מדריד|real madrid|rma", cleaned, re.IGNORECASE):
        return "control_only_real_barca"
    if not (elite_only_mode_active(state) or strict_filter_active(state) or night_mode_control_active(state)):
        return ""
    has_big_club = (
        _matches_any(BIG_CLUB_RUMOR_PATTERNS, cleaned)
        or _matches_any(ELITE_ADMIN_CLUB_PATTERNS, cleaned)
        or has_big_club_as_main_buyer(cleaned)
    )
    has_high_value_news = (
        _matches_any(FINAL_OR_NEAR_FINAL_PATTERNS, cleaned)
        or _matches_any(STRONG_PLAYER_MOVE_PATTERNS, cleaned)
        or _matches_any(COACH_IMPORTANT_PATTERNS, cleaned)
        or _matches_any(SERIOUS_INJURY_PATTERNS, cleaned)
    )
    if elite_only_mode_active(state) and not has_big_club:
        return "temporary_elite_only_mode"
    if strict_filter_active(state) and not (has_big_club and has_high_value_news):
        return "temporary_strict_filter_mode"
    if night_mode_control_active(state) and not (has_big_club and has_high_value_news):
        return "temporary_night_mode"
    return ""


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
    if is_lineup_or_teamsheet_post(post):
        return "lineup_or_teamsheet"
    if is_poll_or_audience_post(post):
        return "poll_or_audience"
    if is_world_cup_bracket_or_qualification_noise(post):
        return "world_cup_bracket_noise"
    if has_small_total_transfer_fee(post):
        return "small_transfer_fee"
    if is_minor_destination_from_big_club_source(post):
        return "minor_destination_from_big_club"
    if is_explicit_untracked_destination_club(post):
        return "untracked_destination_club"
    if is_contextless_teaser_post(post):
        return "contextless_teaser"
    if is_unclear_subject_news_post(post):
        return "unclear_subject_news"
    if is_vague_status_without_primary_context(post):
        return "vague_status_without_primary_context"
    if is_live_goal_or_match_moment_post(post):
        return "live_goal_or_match_moment"
    if is_match_result_or_engagement_post(post):
        return "match_result_or_engagement"
    if is_match_context_noise_post(post):
        return "match_context_noise"
    if is_media_without_report_post(post):
        return "media_without_report"
    if is_too_short_without_strong_news_post(post):
        return "too_short_without_strong_news"
    if is_name_without_news_action_post(post):
        return "name_without_news_action"
    if is_unclear_main_club_context_post(post):
        return "unclear_main_club_context"
    if is_weak_copy_without_primary_value_post(post):
        return "weak_copy_without_primary_value"
    if is_writer_profile_noise_post(post):
        return "writer_profile_noise"
    temporary_block_reason = temporary_control_filter_block_reason(post)
    if temporary_block_reason:
        return temporary_block_reason
    cleaned = clean_for_ai_translation(html.unescape("\n".join([post.text or "", post.quoted_text or ""])))
    if is_untracked_transfer_or_staff_news(post):
        return "untracked_transfer_or_staff_news"
    if is_non_elite_loose_transfer_report(cleaned):
        return "non_elite_loose_transfer_talk"
    if (
        (_matches_any(FINAL_ONLY_ALLOWED_CLUB_PATTERNS, cleaned) or matches_managed_team_tier("tier2", cleaned))
        and not _matches_any(FINAL_ONLY_STRICT_PATTERNS, cleaned)
        and not has_big_club_as_main_buyer(cleaned)
    ):
        return "final_only_club_not_strict_final"
    if (
        matches_managed_team_tier("tier3", cleaned)
        and _matches_any(WEAK_INTEREST_PATTERNS, cleaned)
        and not (
            has_big_club_as_main_buyer(cleaned)
            or _matches_any(BIG_CLUB_CONTEXT_PATTERNS, cleaned)
            or matches_managed_team_tier("tier1", cleaned)
            or _matches_any(FINAL_ONLY_STRICT_PATTERNS, cleaned)
        )
    ):
        return "tier3_weak_interest"
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
            or matches_managed_team_tier("tier3", cleaned)
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
    global TRANSLATION_CACHE_DIRTY
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
        "- If the source contains an inline list of stats, countries, teams, players, checkmarks, crosses, medals, bullets, or many flag emojis, format it as a readable Telegram list.\n"
        "- For lists: use one line per list item and do NOT add blank lines inside the list. Add a blank line only after the list ends if a summary/next paragraph follows.\n"
        "- For long non-list messages only: use natural short paragraphs every 2-3 sentences when it improves readability.\n"
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
    for index, key in gemini_translation_keys_for_operation():
        if real_requests_used >= max(1, GEMINI_MAX_REAL_TRANSLATION_REQUESTS):
            break
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{urllib.parse.quote(GEMINI_FAST_MODEL)}:generateContent?key={urllib.parse.quote(key)}"
        )
        try:
            with GEMINI_TRANSLATION_SEMAPHORE:
                real_requests_used += 1
                data = http_post_json(url, payload, timeout=GEMINI_TRANSLATION_TIMEOUT_SECONDS, max_attempts=1, respect_retry_after=False)
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
                TRANSLATION_CACHE_DIRTY = True
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
            if should_stop_gemini_key_sweep(exc):
                break
            continue
    log_gemini_unavailable(last_error)
    raise TranslationUnavailable(f"Gemini single translation failed after {real_requests_used} real request(s): {last_error}")


def translate_post_for_send(post: Post) -> tuple[str, str, str]:
    """Return publishable translation. If Gemini is unavailable, do not send."""
    include_quote = bool(
        not is_self_quote(post)
        and post.quoted_text
        and TRANSLATE_QUOTED_POSTS
    )
    main, quote, quote_author = gemini_translate_post_once(post, include_quote)
    if not (has_meaningful_text(main) or has_meaningful_text(quote)):
        raise TranslationUnavailable("Gemini returned no meaningful translation")
    return main, quote, quote_author


def send_post(post: Post, reply_message_ids: dict[str, int] | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    timings: dict[str, Any] = {"sent": False, "mode": "skipped"}

    # Final network-free approval gate. No Gemini request, video HEAD/GET,
    # external video API, or Telegram upload is allowed before this passes.
    block_reason = pre_send_final_local_block_reason(post)
    if getattr(post, "force_startup_send", False) and block_reason == "old_post":
        logging.info("בדיקת הפעלה: מדלג רק על חסימת גיל לפוסט האחרון של @%s. מסנני תוכן עדיין פועלים כרגיל.", post.username)
        block_reason = ""
    if block_reason:
        timings["total_seconds"] = time.perf_counter() - started
        timings["mode"] = f"pre_send_blocked:{block_reason}"
        block_reason_he = hebrew_block_reason(block_reason)
        log_skip_once(
            "pre_send:" + block_reason,
            post,
            "דילוג לפני תרגום/וידיאו: %s מ-@%s לא נשלח ולא בוצעה בדיקת וידיאו/תרגום: %s | %s",
            block_reason_he,
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
    images = selected_post_images(post)
    timings["prepare_seconds"] = time.perf_counter() - prepare_started

    if video_url:
        try:
            send_started = time.perf_counter()
            message_ids = telegram_broadcast_with_text_fallback(
                "sendVideo",
                {
                    "video": video_url,
                    "caption": trim_keep_ending(message, 1024),
                    "parse_mode": "HTML",
                    "supports_streaming": True,
                },
                message,
                reply_message_ids=reply_message_ids,
            )
            timings["send_seconds"] = time.perf_counter() - send_started
            timings["total_seconds"] = time.perf_counter() - started
            timings["sent"] = True
            timings["mode"] = "וידיאו"
            timings["telegram_message_ids"] = message_ids
            return timings
        except Exception as exc:
            logging.warning("⚠️ שליחת וידיאו נכשלה, שולח טקסט נקי בלבד: %s", exc)
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
            message_ids = telegram_broadcast_with_text_fallback("sendMediaGroup", {"media": media}, message, reply_message_ids=reply_message_ids)
        except Exception as exc:
            logging.warning("⚠️ שליחת תמונות נכשלה, שולח טקסט בלבד: %s", exc)
        else:
            timings["send_seconds"] = time.perf_counter() - send_started
            timings["total_seconds"] = time.perf_counter() - started
            timings["sent"] = True
            timings["mode"] = f"{len(images)} תמונה/ות"
            timings["telegram_message_ids"] = message_ids
            return timings

    send_started = time.perf_counter()
    message_ids = telegram_broadcast(
        "sendMessage",
        {
            "text": trim(message, 4096),
            "disable_web_page_preview": True,
            "parse_mode": "HTML",
        },
        reply_message_ids=reply_message_ids,
    )
    timings["send_seconds"] = time.perf_counter() - send_started
    timings["total_seconds"] = time.perf_counter() - started
    timings["sent"] = True
    timings["mode"] = "טקסט"
    timings["telegram_message_ids"] = message_ids
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
        logging.warning("⚠️ הטקסט נשלח, אבל טלגרם לא הצליח לצרף וידיאו: %s", exc)


STATE_LAST_SAVED_JSON: str | None = None


def state_path() -> Path:
    return app_data_path(STATE_FILE)


def load_state() -> dict[str, Any]:
    global STATE_LAST_SAVED_JSON
    path = state_path()
    if not path.exists():
        STATE_LAST_SAVED_JSON = None
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        STATE_LAST_SAVED_JSON = raw
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        logging.warning("⚠️ לא הצליח לקרוא קובץ מצב. מתחיל עם מצב נקי.")
        STATE_LAST_SAVED_JSON = None
        return {}


def save_state(state: dict[str, Any]) -> None:
    global STATE_LAST_SAVED_JSON
    path = state_path()
    serialized = json.dumps(state, ensure_ascii=False, indent=2)
    if serialized == STATE_LAST_SAVED_JSON:
        return
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(serialized, encoding="utf-8")
    temp_path.replace(path)
    STATE_LAST_SAVED_JSON = serialized


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
    control_state_for_cycle = load_control_state()
    fetch_workers = min(current_max_parallel_account_checks(), max(1, len(accounts)))
    send_executor = ThreadPoolExecutor(max_workers=current_max_parallel_post_sends())
    send_futures = []
    queued_ids: set[str] = set()
    global_candidate_posts: list[tuple[str, Post, float]] = []
    scanned_accounts = 0
    accounts_with_posts = 0
    fetched_posts_total = 0
    new_posts_total = 0
    recent_24h_snapshot: dict[str, int] = {}

    def send_task(item: tuple[str, Post, float], reply_message_ids: dict[str, int] | None = None) -> tuple[str, Post, list[str], str, bool, dict[str, Any]]:
        username, post, found_seconds = item
        try:
            result = send_post(post, reply_message_ids=reply_message_ids)
            result["found_seconds"] = found_seconds
            result["post_age_seconds"] = max(0.0, time.time() - post.published_ts) if post.published_ts else 0.0
            result["source_name"] = post.source_name
            result["force_startup_send"] = bool(getattr(post, "force_startup_send", False))
            return username, post, post.dedupe_ids, post.link, True, result
        except Exception as exc:
            logging.error("⛔ שליחת הפוסט נכשלה %s: %s", post.link, exc)
            return username, post, post.dedupe_ids, post.link, False, {}

    try:
        with ThreadPoolExecutor(max_workers=fetch_workers) as fetch_executor:
            future_map = {fetch_executor.submit(fetch_posts_safely, username): username for username in ordered_accounts()}
            for future in as_completed(future_map):
                username, posts = future.result()
                scanned_accounts += 1
                daily_stat_increment("scanned", username, 1)
                seen = set(state.get(username, []))
                if not posts:
                    recent_24h_snapshot[username] = 0
                    record_account_scan_summary(username, [], 0)
                    continue
                accounts_with_posts += 1
                fetched_posts_total += len(posts)
                daily_stat_increment("fetched", username, len(posts))
                recent_count = recent_24h_count(posts)
                recent_24h_snapshot[username] = recent_count
                daily_stat_set("fetched_recent_24h", username, recent_count)
                enabled_since_ts = account_enabled_since(username, control_state_for_cycle)

                if not first_run and username not in state and not SEND_BACKLOG_FOR_NEW_ACCOUNTS:
                    if enabled_since_ts > 0:
                        new_posts = []
                        skipped_before_enable = 0
                        for post in posts:
                            if post.published_ts and post.published_ts >= enabled_since_ts:
                                new_posts.append(post)
                            else:
                                skipped_before_enable += 1
                                seen.update(post.dedupe_ids)
                        state[username] = list(seen)[-500:]
                        if not new_posts:
                            logging.info(
                                "🔎 @%s הופעל בכפתור, אבל אין פוסטים חדשים אחרי זמן ההפעלה. סומנו %s פוסטים ישנים כנצפו.",
                                username,
                                skipped_before_enable,
                            )
                            continue
                        logging.info(
                            "▶️ @%s הופעל בכפתור: %s פוסטים אחרי זמן ההפעלה ייבדקו, %s פוסטים ישנים סומנו כנצפו.",
                            username,
                            len(new_posts),
                            skipped_before_enable,
                        )
                    else:
                        for post in posts:
                            seen.update(post.dedupe_ids)
                        state[username] = list(seen)[-500:]
                        continue
                else:
                    new_posts = [post for post in posts if not any(post_id in seen for post_id in post.dedupe_ids)]

                if enabled_since_ts > 0 and not SEND_BACKLOG_FOR_NEW_ACCOUNTS:
                    filtered_new_posts = []
                    skipped_before_enable = 0
                    for post in new_posts:
                        if post.published_ts and post.published_ts >= enabled_since_ts:
                            filtered_new_posts.append(post)
                        else:
                            skipped_before_enable += 1
                            seen.update(post.dedupe_ids)
                    if skipped_before_enable:
                        state[username] = list(seen)[-500:]
                        logging.info(
                            "↩️ @%s: דולגו %s פוסטים מלפני זמן ההפעלה בכפתור; פוסטים חדשים אחרי ההפעלה נשארו לבדיקה.",
                            username,
                            skipped_before_enable,
                        )
                    new_posts = filtered_new_posts
                new_posts_total += len(new_posts)
                if new_posts:
                    daily_stat_increment("new", username, len(new_posts))
                record_account_scan_summary(username, posts, len(new_posts))
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
                            "↩️ בדיקת הפעלה: הפוסט האחרון של @FabrizioRomano כבר נשלח בעבר בבדיקת הפעלה, מדלג עליו עכשיו. קישור: %s",
                            latest_post.link,
                        )
                    else:
                        setattr(latest_post, "force_startup_send", True)
                        new_posts = [latest_post]
                        logging.info(
                            "🚀 בדיקת הפעלה: שולח את הפוסט האחרון של @FabrizioRomano דרך RSS, תרגום ושליחה לטלגרם. מקור: %s | קישור: %s",
                            posts[0].source_name,
                            posts[0].link,
                        )
                elif startup_cycle and SEND_LAST_POST_ON_EVERY_START and username == "FabrizioRomano":
                    new_posts = posts[:1]
                elif first_run and SEND_LAST_POST_ON_FIRST_RUN and username == "FabrizioRomano":
                    new_posts = posts[:1]
                elif first_run:
                    for post in posts:
                        seen.update(post.dedupe_ids)
                    state[username] = list(seen)[-500:]
                    logging.info("🔎 אתחול ראשון: @%s נמצאו %s פוסטים קיימים וסומנו כנקראו בלי שליחה.", username, len(posts))
                    continue

                candidate_posts: list[tuple[str, Post, float]] = []
                posts_to_consider = new_posts[: min(MAX_NEW_POSTS_PER_ACCOUNT_PER_CHECK, MAX_POSTS_SENT_PER_CYCLE)]
                for post in reversed(posts_to_consider):
                    if min_published_ts and post.published_ts and post.published_ts < min_published_ts:
                        seen.update(post.dedupe_ids)
                        log_skip_once(
                            "old_post",
                            post,
                            "דילוג: פוסט ישן מטווח ההפעלה מחדש מ-@%s לא נשלח: %s | גיל: %s",
                            username,
                            post.link,
                            post_age_text(post),
                        )
                        continue
                    if is_interview_post(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("interview_blocked", post, "דילוג מסנן: ראיון/ציטוט בלי חדשות מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_lineup_or_teamsheet_post(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("lineup_or_teamsheet", post, "דילוג מסנן: הרכב/הרכבים מ-@%s לא נשלחו: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_poll_or_audience_post(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("poll_or_audience", post, "דילוג מסנן: סקר/הצבעת קהל מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if has_small_total_transfer_fee(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("small_transfer_fee", post, "דילוג מסנן: עסקה קטנה מתחת לרף מ-@%s לא נשלחה: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_minor_destination_from_big_club_source(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("minor_destination_from_big_club", post, "דילוג מסנן: יעד קטן דרך קבוצה גדולה מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if getattr(post, "force_startup_send", False):
                        forced_block_reason = pre_send_final_local_block_reason(post)
                        if forced_block_reason and forced_block_reason != "old_post":
                            seen.update(post.dedupe_ids)
                            log_skip_once(
                                "force_startup_final:" + forced_block_reason,
                                post,
                                "דילוג בדיקת הפעלה: %s מ-@%s לא נשלח: %s | טקסט: %s",
                                hebrew_block_reason(forced_block_reason),
                                username,
                                post.link,
                                filtered_post_text_preview(post),
                            )
                            continue
                        candidate_posts.append((username, post, time.perf_counter() - cycle_started))
                        continue
                    if is_too_old_post(post) and not (username == "FabrizioRomano" and startup_cycle and SEND_LAST_POST_ON_EVERY_START):
                        seen.update(post.dedupe_ids)
                        log_skip_once(
                            "old_post",
                            post,
                            "דילוג: פוסט ישן מדי מ-@%s לא נשלח: %s | גיל: %s | חלון מותר: %s",
                            username,
                            post.link,
                            post_age_text(post),
                            max_post_age_text(),
                        )
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
                    if is_contextless_teaser_post(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("contextless_teaser", post, "דילוג מסנן: הודעת רמז בלי מידע מ-@%s לא נשלחה: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_unclear_subject_news_post(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("unclear_subject_news", post, "דילוג מסנן: דיווח בלי שם/קבוצה ברורים מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_vague_status_without_primary_context(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("vague_status_without_primary_context", post, "דילוג מסנן: עדכון סטטוס בלי נושא ברור מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_live_goal_or_match_moment_post(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("live_goal_or_match_moment", post, "דילוג מסנן: עדכון שער או מהלך משחק מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_match_result_or_engagement_post(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("match_result_or_engagement", post, "דילוג מסנן: תוצאה/שאלת קהל/עדכון משחק מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_match_context_noise_post(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("match_context_noise", post, "דילוג מסנן: סביבת משחק/נבחרת בלי חדשות מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_media_without_report_post(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("media_without_report", post, "דילוג מסנן: תמונה/וידאו בלי דיווח מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_too_short_without_strong_news_post(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("too_short_without_strong_news", post, "דילוג מסנן: הודעה קצרה מדי בלי דיווח חזק מ-@%s לא נשלחה: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_name_without_news_action_post(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("name_without_news_action", post, "דילוג מסנן: שם בלי פעולה חדשותית ברורה מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_unclear_main_club_context_post(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("unclear_main_club_context", post, "דילוג מסנן: לא ברור מי עיקר הדיווח מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_weak_copy_without_primary_value_post(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("weak_copy_without_primary_value", post, "דילוג מסנן: דיווח ממוחזר בלי ערך חדש מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
                        continue
                    if is_writer_profile_noise_post(post):
                        seen.update(post.dedupe_ids)
                        log_skip_once("writer_profile_noise", post, "דילוג מסנן: רעש אופייני לכתב מ-@%s לא נשלח: %s | טקסט: %s", username, post.link, filtered_post_text_preview(post))
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
                        log_skip_once("importance:" + importance_reason, post, "דילוג מסנן חשיבות: %s מ-@%s לא נשלח: %s | טקסט: %s", hebrew_block_reason(importance_reason), username, post.link, filtered_post_text_preview(post))
                        continue
                    burst_event = find_recent_burst_spam_event(post, state)
                    if burst_event:
                        seen.update(post.dedupe_ids)
                        burst_detail = duplicate_event_debug_he(post, burst_event)
                        log_skip_once("burst_spam", post, "דילוג עומס: יש כבר גל דיווחים על אותו נושא, והנוכחי לא מוסיף התקדמות חזקה. @%s לא נשלח: %s | %s", username, post.link, burst_detail)
                        continue
                    duplicate_event = find_channel_duplicate_event(post, state) or find_recent_duplicate_event(post, state)
                    if duplicate_event:
                        if try_keep_non_duplicate_report_lines(post, state):
                            duplicate_event = None
                        else:
                            seen.update(post.dedupe_ids)
                            duplicate_source = duplicate_event_source_he(duplicate_event)
                            duplicate_detail = duplicate_event_debug_he(post, duplicate_event)
                            log_skip_once("recent_duplicate", post, "דילוג כפילות חכמה: אותו אירוע כבר נמצא בזיכרון 12 שעות מול %s. @%s לא נשלח: %s | %s", duplicate_source, username, post.link, duplicate_detail)
                            continue
                    if duplicate_event:
                        seen.update(post.dedupe_ids)
                        duplicate_source = duplicate_event_source_he(duplicate_event)
                        duplicate_detail = duplicate_event_debug_he(post, duplicate_event)
                        log_skip_once("recent_duplicate", post, "דילוג כפילות חכמה: אותו אירוע כבר נשלח/נשמר ב-12 השעות האחרונות מול %s. הנוכחי מ-@%s לא נשלח: %s | %s", duplicate_source, username, post.link, duplicate_detail)
                        continue
                    candidate_posts.append((username, post, time.perf_counter() - cycle_started))

                global_candidate_posts.extend(candidate_posts)

                state[username] = list(seen)[-500:]

        global_candidate_posts = cluster_parallel_candidates(global_candidate_posts)
        if recent_24h_snapshot:
            daily_stat_replace_table("fetched_recent_24h_snapshot", recent_24h_snapshot)
        record_scan_cycle_summary(
            scanned_accounts,
            accounts_with_posts,
            fetched_posts_total,
            new_posts_total,
            len(global_candidate_posts),
        )
        flush_scan_cycle_summary()
        flush_skip_summary()
        flush_account_scan_summary(force=bool(startup_cycle and ACCOUNT_SCAN_SUMMARY_ON_STARTUP))

        for candidate in sort_candidate_posts_for_priority(global_candidate_posts):
            if len(send_futures) >= MAX_POSTS_SENT_PER_CYCLE:
                break
            username, post, _ = candidate
            seen = set(state.get(username, []))
            final_block_reason = "interview_blocked" if is_interview_post(post) else pre_send_final_local_block_reason(post)
            if getattr(post, "force_startup_send", False) and final_block_reason == "old_post":
                final_block_reason = ""
            if final_block_reason:
                mark_candidate_seen(state, candidate)
                final_block_reason_he = hebrew_block_reason(final_block_reason)
                log_skip_once(
                    "final:" + final_block_reason,
                    post,
                    "דילוג סופי לפני שליחה: %s מ-@%s לא נשלח, לפני תרגום/וידיאו: %s | %s",
                    final_block_reason_he,
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
                    if not bool(duplicate_event.get("pending", False)):
                        mark_candidate_seen(state, candidate)
                    duplicate_source = duplicate_event_source_he(duplicate_event)
                    duplicate_detail = duplicate_event_debug_he(post, duplicate_event)
                    log_skip_once("same_cycle_duplicate", post, "דילוג כפילות חכמה: אותו אירוע כבר נמצא בזיכרון מול %s. @%s לא נשלח: %s | %s", duplicate_source, username, post.link, duplicate_detail)
                    continue
            if duplicate_event:
                if not bool(duplicate_event.get("pending", False)):
                    mark_candidate_seen(state, candidate)
                duplicate_source = duplicate_event_source_he(duplicate_event)
                duplicate_detail = duplicate_event_debug_he(post, duplicate_event)
                log_skip_once("same_cycle_duplicate", post, "דילוג כפילות חכמה באותו סבב: אותו אירוע כבר נבחר ממקור עדיף/קודם מול %s. @%s לא נשלח: %s | %s", duplicate_source, username, post.link, duplicate_detail)
                continue
            reply_message_ids = find_bot_reply_target_for_post(post, state)
            remember_recent_news_event(post, state, pending=True)
            if reply_message_ids:
                logging.info("↩️ תגובה חכמה: הפוסט מ-@%s יישלח כתגובה להודעה קודמת של הבוט באותו אירוע.", username)
            send_futures.append(send_executor.submit(send_task, candidate, reply_message_ids))
            queued_ids.update(post.dedupe_ids)

        for future in as_completed(send_futures):
            username, sent_post, post_ids, link, ok, result = future.result()
            if not ok:
                forget_pending_recent_news_event(sent_post, state)
                continue
            if result.get("sent"):
                confirm_recent_news_event(sent_post, state)
                seen = set(state.get(username, []))
                seen.update(post_ids)
                state[username] = list(seen)[-500:]
                if result.get("force_startup_send"):
                    forced_seen = set(state.get(FORCED_FABRIZIO_STARTUP_STATE_KEY, []))
                    forced_seen.update(post_ids)
                    state[FORCED_FABRIZIO_STARTUP_STATE_KEY] = list(forced_seen)[-100:]
                if result.get("channel_memory_text"):
                    remember_channel_news_text(str(result.get("channel_memory_text", "")), state, message_id=link, source="bot_sent")
                if result.get("telegram_message_ids"):
                    remember_bot_sent_reply_target(sent_post, state, dict(result.get("telegram_message_ids", {})))
                sent += 1
                daily_stat_increment("sent", username, 1)
                if float(result.get("translation_seconds", 0.0) or 0.0) > 0:
                    daily_stat_add_timing("translation_seconds", float(result.get("translation_seconds", 0.0) or 0.0))
                daily_stat_record_post_length(username, link, str(result.get("channel_memory_text", "") or ""))
                save_control_state(last_sent_post={"ts": time.time(), "username": username, "link": link})
                logging.info(
                    "✅ נשלח פוסט מ-@%s | מקור: %s | גיל: %.0fs | תרגום: %.2fs | שליחה: %.2fs | סה״כ: %.2fs",
                    username,
                    result.get("source_name", "unknown"),
                    result.get("post_age_seconds", 0.0),
                    result.get("translation_seconds", 0.0),
                    result.get("send_seconds", 0.0),
                    result.get("total_seconds", 0.0),
                )
            elif result.get("mode") == "no_news":
                forget_pending_recent_news_event(sent_post, state)
                seen = set(state.get(username, []))
                seen.update(post_ids)
                state[username] = list(seen)[-500:]
                logging.info(
                    "דילוג: אין עדכון חדשותי, הפוסט סומן כנראה: %s | מקור: %s",
                    link,
                    result.get("source_name", "unknown"),
                )
            elif str(result.get("mode", "")).startswith("translation_unavailable"):
                forget_pending_recent_news_event(sent_post, state)
                logging.info(
                    "דילוג זמני: הפוסט לא סומן כנראה כי הכשל הוא בתרגום Gemini בלבד. ינסה שוב אחרי הקירור המקומי. מצב: %s | מקור: %s | %s",
                    result.get("mode", "skipped"),
                    result.get("source_name", "unknown"),
                    link,
                )
            elif str(result.get("mode", "")).startswith("pre_send_blocked:"):
                forget_pending_recent_news_event(sent_post, state)
                seen = set(state.get(username, []))
                seen.update(post_ids)
                state[username] = list(seen)[-500:]
                logging.info(
                    "דילוג חסכוני: הפוסט סומן כנראה כדי לא לנסות שוב באותו כשל. מצב: %s | מקור: %s | %s",
                    result.get("mode", "skipped"),
                    result.get("source_name", "unknown"),
                    link,
                )
            else:
                forget_pending_recent_news_event(sent_post, state)
                logging.warning(
                    "⏳ פוסט מ-@%s לא נשלח ולכן לא סומן כנראה, יישאר לניסיון הבא: %s | מקור RSS: %s | מצב: %s",
                    username,
                    link,
                    result.get("source_name", "unknown"),
                    result.get("mode", "unknown"),
                )
        drop_unconfirmed_recent_news_events(state)
    finally:
        send_executor.shutdown(wait=True, cancel_futures=False)

    return sent


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    refresh_gemini_api_keys_from_env()
    validate_settings()
    env_parts_count = gemini_env_parts_count()
    logging.info("🚀 בוט הכדורגל עלה. כתבים פעילים: %s | בדיקה כל %ss", len(active_x_accounts()), current_check_every_seconds())
    if env_parts_count and not GEMINI_API_KEYS:
        logging.error(
            "Gemini אבחון חמור: Railway מכיל %s חלקי מפתחות אבל הקוד טען 0. אם הלוג הזה מופיע עם BOT_BUILD_ID=%s, שלח את שורת הדיבאג; אם BOT_BUILD_ID אחר/חסר, Railway מריץ קוד ישן.",
            env_parts_count,
            BOT_BUILD_ID,
        )
    if not env_parts_count:
        logging.error("לא נמצאו מפתחות Gemini במשתני הסביבה. פוסטים לא יישלחו בלי תרגום תקין.")
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
            logging.error("⛔ הודעת בדיקת הפעלה לטלגרם נכשלה: %s", exc)

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
                    logging.info("⏸️ בוט הכדורגל כבוי מלוח השליטה. לא סורק ולא שולח.")
                    paused_logged = True
                time.sleep(current_check_every_seconds())
                continue
            paused_logged = False

            if is_shabbat_now():
                if not skipped_for_shabbat:
                    logging.info("🕯️ מצב שבת פעיל: הבוט לא סורק, לא שולח ולא שומר מצב")
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
                logging.info("✅ מצב שבת הסתיים: פוסטים משבת סומנו כנצפו בלי שליחה")
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
            send_daily_quality_report_if_due()
            now = time.time()
            if now - last_heartbeat_log >= HEARTBEAT_LOG_SECONDS:
                logging.info("💓 בוט הכדורגל עדיין עובד. כתבים פעילים: %s | בדיקה כל %ss | נשלחו בסבב: %s", len(active_x_accounts()), current_check_every_seconds(), sent)
                last_heartbeat_log = now
        except Exception as exc:
            logging.error("⛔ שגיאה לא צפויה. הבוט ימשיך לעבוד: %s", exc)
        elapsed = time.time() - cycle_started
        time.sleep(max(0, current_check_every_seconds() - elapsed))


if __name__ == "__main__":
    main()

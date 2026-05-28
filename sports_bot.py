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
]

TARGET_LANGUAGE = "he"
CHECK_EVERY_SECONDS = 60
HTTP_RETRIES = 3
RETRY_SLEEP_SECONDS = 4
MAX_NEW_POSTS_PER_ACCOUNT_PER_CHECK = 3
SEND_LAST_POST_ON_FIRST_RUN = True
MAX_IMAGES_PER_POST = 4
STATE_FILE = "x_to_telegram_state.json"
SEND_IMAGES_AFTER_TEXT = False

ACCOUNT_DISPLAY_NAMES = {
    "NBA": "NBA",
    "ShamsCharania": "שאמס צ׳רניה",
}

RTL_MARK = "\u200f"

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

        if text or link:
            posts.append(
                Post(
                    post_id=post_id,
                    username=username,
                    text=text,
                    link=link,
                    image_urls=images,
                    video_urls=videos,
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


def translate_text(text: str) -> str:
    if not text:
        return ""
    logging.info("Translating post text")
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
    try:
        data = json.loads(http_get(url, timeout=20).decode("utf-8"))
        translated = "".join(part[0] for part in data[0] if part and part[0]).strip()
        logging.info("Translation finished")
        return translated
    except Exception as exc:
        logging.warning("Translation failed, sending original text: %s", exc)
        return text


def remove_inline_links(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text or "")
    text = re.sub(r"(?<!\w)[@#][A-Za-z0-9_]+", "", text)
    text = re.sub(r"(?m)^\s*[-–—]\s*$", "", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def tidy_translated_text(text: str) -> str:
    text = html.unescape(text or "").strip()
    text = remove_inline_links(text)
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)

    text = re.sub(r"(?<=[.!?])\s+(?=[א-תA-Z0-9])", "\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def rtl(text: str) -> str:
    return "\n".join(f"{RTL_MARK}{line}" if line.strip() else line for line in text.splitlines())


def has_video_hint(post: Post, translated: str) -> bool:
    combined = f"{post.text}\n{translated}".lower()
    return bool(post.video_urls or "video" in combined or "וידאו" in combined or "סרטון" in combined)


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


def build_message(post: Post, translated: str, quoted_translated: str = "") -> str:
    translated = tidy_translated_text(translated)
    quoted_translated = tidy_translated_text(quoted_translated)
    display_name = ACCOUNT_DISPLAY_NAMES.get(post.username, post.username)
    safe_account = html.escape(rtl(f"{display_name}:"))
    safe_body = html.escape(rtl(translated or "עדכון חדש"))
    safe_quoted_author = html.escape(rtl(post.quoted_author or "פוסט מצוטט"))
    safe_quoted_body = html.escape(rtl(quoted_translated))
    safe_link = html.escape(post.link)

    parts = [
        f"<b>{safe_account}</b>",
        "",
        safe_body,
    ]
    if safe_quoted_body:
        parts.extend(
            [
                "",
                f"<b>{html.escape(rtl('פוסט מצוטט:'))}</b>",
                safe_quoted_author,
                safe_quoted_body,
            ]
        )
    if post.link:
        link_label = "קישור לווידיאו:" if has_video_hint(post, translated) else "לצפייה בפוסט המלא:"
        parts.extend(["", f"<b>{html.escape(rtl(link_label))}</b>", safe_link])
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
        media = []
        for index, image_url in enumerate(images):
            item: dict[str, Any] = {"type": "photo", "media": image_url}
            if index == 0:
                item["caption"] = trim(message, 1024)
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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    validate_settings()
    logging.info("Bot started. Accounts: %s", ", ".join(f"@{account}" for account in X_ACCOUNTS))
    logging.info("Checking every %s seconds", CHECK_EVERY_SECONDS)

    while True:
        try:
            logging.info("Starting new check cycle")
            state = load_state()
            sent = run_once(state)
            save_state(state)
            logging.info("Finished check. Sent %s new posts.", sent)
        except Exception as exc:
            logging.exception("Unexpected cycle error; bot will keep running: %s", exc)
        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()

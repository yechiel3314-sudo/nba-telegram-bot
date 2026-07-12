import json
import os
import re
import sys
import time
import urllib.error
import urllib.request


TOKEN_ENV_NAMES = [
    "TELEGRAM_TOKEN",
    "NBA_BOT_TOKEN",
    "NBA_LIVE_TELEGRAM_BOT_TOKEN_PRIVATE",
    "NETO_SPORT_SHARED_MAIN_TELEGRAM_BOT_TOKEN_PRIVATE",
    "NETO_SPORT_SHARED_MAIN_TELEGRAM_BOT_TOKEN",
    "NETO_SPORT_SHARED_MAIN_TELEGRAM_BOT",
    "NETO_SPORT_SHARED_MAIN_TELEGRAM_BOT_PRIVATE",
]

CHAT_ID_ENV_NAMES = [
    "NBA_CHANNEL_ID",
    "NBA_LIVE_TELEGRAM_CHAT_ID_PRIVATE",
    "TELEGRAM_NBA_CHANNEL_ID",
    "TELEGRAM_CHAT_ID",
    "CHAT_ID",
]


def looks_like_telegram_token(value):
    return bool(re.match(r"^\d{6,}:[A-Za-z0-9_-]{20,}$", (value or "").strip()))


def normalize_chat_id(raw):
    value = (raw or "").strip()
    if value.startswith("@"):
        return value
    if value.endswith("-") and value[:-1].isdigit():
        value = "-" + value[:-1]
    if value.startswith("100") and value.isdigit():
        value = "-" + value
    return value


def find_token():
    for name in TOKEN_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if value:
            return name, value

    for name, value in os.environ.items():
        upper_name = name.upper()
        if looks_like_telegram_token(value) and "TELEGRAM" in upper_name and ("BOT" in upper_name or "TOKEN" in upper_name):
            return name, value.strip()

    for value in os.environ.values():
        if looks_like_telegram_token(value):
            return "AUTO_DISCOVERED_TOKEN", value.strip()

    return "", ""


def find_chat_id():
    for name in CHAT_ID_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if value:
            return name, normalize_chat_id(value)
    return "", ""


def telegram_api(token, method, payload=None, timeout=20):
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            return response.status, json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"ok": False, "description": body}
        return e.code, parsed
    except Exception as e:
        return 0, {"ok": False, "description": str(e)}


def description(result):
    return (result or {}).get("description") or str(result)


def main():
    token_env, token = find_token()
    chat_env, chat_id = find_chat_id()

    print("=== Telegram channel connection test ===")
    print(f"Token env: {token_env or 'NOT FOUND'}")
    print(f"Chat env: {chat_env or 'NOT FOUND'}")
    print(f"Chat id: {chat_id or 'NOT FOUND'}")

    if not token:
        print("ERROR: No Telegram bot token was found in environment variables.")
        return 2

    if not chat_id:
        print("ERROR: NBA_CHANNEL_ID was not found.")
        return 2

    status, get_me = telegram_api(token, "getMe")
    if status != 200 or not get_me.get("ok"):
        print(f"ERROR: getMe failed ({status}): {description(get_me)}")
        return 3

    bot = get_me.get("result") or {}
    bot_username = bot.get("username") or "unknown"
    print(f"Bot detected: @{bot_username} (id={bot.get('id', 'unknown')})")

    status, get_chat = telegram_api(token, "getChat", {"chat_id": chat_id})
    if status != 200 or not get_chat.get("ok"):
        reason = description(get_chat)
        print(f"ERROR: getChat failed ({status}): {reason}")
        if "chat not found" in reason.lower():
            print(f"FIX: Add @{bot_username} as an ADMIN in the NBA Telegram channel, or fix NBA_CHANNEL_ID.")
        return 4

    chat = get_chat.get("result") or {}
    print(f"Chat accessible: {chat.get('title') or chat.get('username') or chat_id} | type={chat.get('type', 'unknown')}")

    message = os.getenv(
        "TEST_MESSAGE",
        f"✅ בדיקת חיבור בוט NBA הצליחה\n\nהבוט @{bot_username} מחובר לערוץ ויכול לשלוח הודעות.\nזמן בדיקה: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
    )
    status, sent = telegram_api(
        token,
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": True,
        },
    )
    if status != 200 or not sent.get("ok"):
        print(f"ERROR: sendMessage failed ({status}): {description(sent)}")
        return 5

    print("OK: Test message was sent to the NBA channel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

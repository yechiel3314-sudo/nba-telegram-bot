import time
import logging
import requests
from datetime import datetime, timedelta, time as dt_time
import pytz

# =========================
# הגדרות
# =========================

BOT_TOKEN = "PUT_YOUR_BOT_TOKEN_HERE"
CHAT_ID = "PUT_YOUR_CHAT_ID_HERE"

SCHEDULE_TIME_STR = "20:04"  # שעת שליחה לפי שעון ישראל

ESPN_API_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

RTL_MARK = "\u200f"

# =========================
# לוגים
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


# =========================
# עיצוב שמות קבוצות
# =========================

def format_team(name):
    return name


# =========================
# שליחה לטלגרם
# =========================

def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    r = requests.post(url, json=payload, timeout=20)
    r.raise_for_status()

    logger.info("Message sent to Telegram successfully.")


# =========================
# משיכת ESPN לפי תאריך
# =========================

def fetch_scoreboard_for_date(date_str):
    try:
        url = f"{ESPN_API_URL}?dates={date_str}&limit=1000"
        logger.info(f"Fetching ESPN scoreboard: {url}")

        r = requests.get(url, timeout=20)
        r.raise_for_status()

        return r.json().get("events", [])

    except Exception as e:
        logger.error(f"Fetch error for {date_str}: {e}")
        return []


# =========================
# בניית רשימת משחקים
# =========================

def get_nba_schedule():
    isr_tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(isr_tz)

    today_str = now.strftime("%Y%m%d")
    tomorrow_str = (now + timedelta(days=1)).strftime("%Y%m%d")

    events = fetch_scoreboard_for_date(today_str) + fetch_scoreboard_for_date(tomorrow_str)

    schedule = []
    seen = set()

    for ev in events:
        try:
            event_id = ev.get("id")

            if event_id in seen:
                continue

            seen.add(event_id)

            comp = ev["competitions"][0]

            home = next(
                t for t in comp["competitors"]
                if t.get("homeAway") == "home"
            )

            away = next(
                t for t in comp["competitors"]
                if t.get("homeAway") == "away"
            )

            schedule.append({
                "id": event_id,
                "time": ev["date"],
                "home": home["team"]["displayName"],
                "away": away["team"]["displayName"],
            })

            logger.info(
                f"Loaded game id={event_id} time={ev['date']} "
                f"away={away['team']['displayName']} home={home['team']['displayName']}"
            )

        except Exception as e:
            logger.error(f"Parse event error: {e}")

    return schedule


# =========================
# בניית הודעת משחקי הלילה
# =========================

def build_schedule_msg(data):
    isr_tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(isr_tz)

    # חלון קבוע של "הלילה הקרוב":
    # מהיום ב־18:00 עד מחר ב־12:00
    window_start = isr_tz.localize(
        datetime.combine(now.date(), dt_time(18, 0))
    )

    window_end = isr_tz.localize(
        datetime.combine(now.date() + timedelta(days=1), dt_time(12, 0))
    )

    date_title = f"{window_start.strftime('%d/%m')} → {window_end.strftime('%d/%m')}"

    header = (
        f"{RTL_MARK}🏀 ══ <b>לוח משחקי הלילה ב NBA</b> ══ 🏀\n"
        f"{RTL_MARK}<b>{date_title}</b>\n\n"
    )

    games = []

    for g in data:
        try:
            raw = g["time"].replace("Z", "")

            try:
                utc_dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=pytz.utc)
            except ValueError:
                utc_dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M").replace(tzinfo=pytz.utc)

            local_dt = utc_dt.astimezone(isr_tz)

            logger.info(
                f"CHECK game_id={g['id']} local={local_dt} "
                f"window=({window_start} -> {window_end}) "
                f"away={g['away']} home={g['home']}"
            )

            if window_start <= local_dt <= window_end:
                games.append({
                    "local_dt": local_dt,
                    "away": g["away"],
                    "home": g["home"],
                })

        except Exception as e:
            logger.error(f"build_schedule_msg error: {e} raw={g}")

    games.sort(key=lambda x: x["local_dt"])

    if not games:
        logger.info("No upcoming games found for the schedule.")
        return None

    body = ""

    for game in games:
        time_str = game["local_dt"].strftime("%d/%m %H:%M")

        body += (
            f"{RTL_MARK}⏰ <b>{time_str}</b>\n"
            f"{RTL_MARK}🏀 {format_team(game['away'])} 🆚 {format_team(game['home'])}\n\n"
        )

    return header + body


# =========================
# לולאת הרצה יומית
# =========================

def main():
    isr_tz = pytz.timezone("Asia/Jerusalem")
    last_s = None

    logger.info("NBA Telegram bot started.")

    while True:
        try:
            now = datetime.now(isr_tz)
            curr = now.strftime("%H:%M")
            today = now.strftime("%Y-%m-%d")

            logger.info(f"Current time: {curr}, scheduled time: {SCHEDULE_TIME_STR}, last_s={last_s}")

            if curr == SCHEDULE_TIME_STR and last_s != today:
                logger.info("Scheduled time reached. Fetching NBA schedule...")

                data = get_nba_schedule()
                msg = build_schedule_msg(data)

                if msg:
                    send_to_telegram(msg)
                    last_s = today

                    # דילוג על הדקה כדי לא לשלוח פעמיים
                    time.sleep(65)
                else:
                    # חשוב: לא נועלים את היום אם אין הודעה
                    logger.info("No message was sent, so today was not locked.")
                    time.sleep(30)

            else:
                time.sleep(30)

        except Exception as e:
            logger.error(f"Main loop error: {e}")
            time.sleep(30)


if __name__ == "__main__":
    main()

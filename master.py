import os
import sys
import time
import signal
import subprocess
from datetime import datetime, timedelta

import requests
import pytz
from astral import LocationInfo
from astral.sun import sun
from hdate import HDateInfo


# =========================================================
# הגדרות
# =========================================================
TZ = pytz.timezone("Asia/Jerusalem")
CITY = LocationInfo("Jerusalem", "Israel", "Asia/Jerusalem", 31.7683, 35.2137)

TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

# רשימת הסקריפטים שירוצו במקביל
SCRIPTS = [
    "bot.py",
    "nba.py",
    "clutch.py",
    "ligyonerim.py",
    "nba_schedule.py",
]

# כמה דקות אחרי השקיעה נחשב מוצ"ש
MOTZEI_SHABBAT_OFFSET_MINUTES = 40

# כל כמה שניות המנהל בודק מצב
LOOP_SLEEP_SECONDS = 30

# כל כמה שניות לבדוק מחדש כשיש שבת/חג
REST_SLEEP_SECONDS = 60


# =========================================================
# טלגרם
# =========================================================
def send_telegram(message: str) -> None:
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
    except Exception as e:
        print(f"⚠️ Telegram send failed: {e}")


# =========================================================
# זמן ויום
# =========================================================
def now_local() -> datetime:
    return datetime.now(TZ)


def today_date():
    return now_local().date()


def sunset_for(date_obj):
    return sun(CITY.observer, date=date_obj, tzinfo=TZ)["sunset"]


# =========================================================
# שבת
# =========================================================
def is_shabbat() -> bool:
    now = now_local()
    weekday = now.weekday()  # Monday=0 ... Sunday=6

    today = now.date()
    yesterday = today - timedelta(days=1)

    sunset_today = sunset_for(today)
    sunset_yesterday = sunset_for(yesterday)

    # שישי אחרי שקיעה
    if weekday == 4 and now >= sunset_today:
        return True

    # שבת עד צאת שבת (40 דקות אחרי שקיעת שישי)
    if weekday == 5:
        motzei = sunset_yesterday + timedelta(minutes=MOTZEI_SHABBAT_OFFSET_MINUTES)
        if now <= motzei:
            return True

    return False


# =========================================================
# חגים בישראל בלבד
# =========================================================
def is_holiday() -> bool:
    # diaspora=False => ישראל בלבד, בלי חו"ל
    info = HDateInfo(today_date(), diaspora=False)
    return bool(info.is_holiday)


def is_work_time() -> bool:
    return not (is_shabbat() or is_holiday())


# =========================================================
# ניהול תהליכים
# =========================================================
processes = {}  # script_name -> subprocess.Popen


def start_script(script: str) -> None:
    if script in processes and processes[script].poll() is None:
        return

    if not os.path.exists(script):
        print(f"❌ {script} לא קיים - מדלג")
        return

    print(f"🚀 מפעיל {script}")
    p = subprocess.Popen(
        [sys.executable, "-u", script],
        stdout=None,
        stderr=None,
    )
    processes[script] = p


def stop_script(script: str) -> None:
    p = processes.get(script)
    if not p:
        return

    if p.poll() is not None:
        processes.pop(script, None)
        return

    try:
        p.terminate()
        p.wait(timeout=5)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass
    finally:
        processes.pop(script, None)


def start_all() -> None:
    for script in SCRIPTS:
        start_script(script)
        time.sleep(2)


def stop_all() -> None:
    print("⛔ שבת/חג - עוצר את כל הבוטים...")
    for script in list(processes.keys()):
        stop_script(script)


def check_processes() -> None:
    for script in SCRIPTS:
        p = processes.get(script)
        if not p:
            continue

        if p.poll() is not None:
            exit_code = p.returncode
            print(f"⚠️ {script} נפל (קוד יציאה: {exit_code}) - מפעיל מחדש")
            start_script(script)


# =========================================================
# לוגיקת מצב
# =========================================================
def mode_name(work_time: bool) -> str:
    return "work" if work_time else "rest"


def main() -> None:
    print("🔥 Master Bot Manager הופעל בהצלחה")

    running = False
    last_mode = None

    while True:
        try:
            work_time = is_work_time()
            current_mode = mode_name(work_time)

            # שינוי מצב: נכנסנו לשבת/חג
            if last_mode is not None and current_mode != last_mode:
                if current_mode == "rest":
                    send_telegram("שבת שלום חברים! נתראה במוצ\"ש עם כוחות מחודשים. 💪")
                else:
                    send_telegram("שבוע טוב! 🌙 הבוט זמין ושב לעדכן כרגיל.")

            last_mode = current_mode

            if not work_time:
                if running:
                    stop_all()
                    running = False

                print(f"😴 [{now_local().strftime('%H:%M:%S')}] שבת/חג - בהמתנה...")
                time.sleep(REST_SLEEP_SECONDS)
                continue

            # זמן חול
            if not running:
                print(f"🌅 [{now_local().strftime('%H:%M:%S')}] זמן חול - מפעיל בוטים")
                start_all()
                running = True

            check_processes()

        except KeyboardInterrupt:
            print("🛑 הופסק ידנית")
            stop_all()
            break
        except Exception as e:
            print(f"❌ שגיאה קריטית במנהל: {e}")

        time.sleep(LOOP_SLEEP_SECONDS)


if __name__ == "__main__":
    main()

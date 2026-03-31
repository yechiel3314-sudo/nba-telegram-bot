import os
import sys
import time
import subprocess
from datetime import datetime, timedelta

import psutil
import pytz
import requests
from astral import LocationInfo
from astral.sun import sun
from pyluach import dates

# =====================
# הגדרות
# =====================
TELEGRAM_TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"

FILES = [
    "bot.py",
    "nba.py",
    "clutch.py",
    "ligyonerim.py",
    "winner.py",
    "nba_schedule.py",
]

# כמה דקות לפני שקיעה בשישי להתחיל לעצור
PRE_SHABBAT_MINUTES = 60

# כמה דקות אחרי יציאת שבת לחזור לפעילות
POST_SHABBAT_MINUTES = 15

# כמה זמן להמתין בפתיחה כדי לא לשכפל תהליכים שכבר הופעלו ע"י ה-start command
BOOT_GRACE_SECONDS = 45

# כל כמה זמן לבדוק
CHECK_EVERY_SECONDS = 30

tz = pytz.timezone("Asia/Jerusalem")
city = LocationInfo("Tel Aviv", "Israel", "Asia/Jerusalem", 32.0853, 34.7818)

last_mode = None
started_at = datetime.now(tz)


# =====================
# טלגרם
# =====================
def send(msg: str) -> None:
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg},
            timeout=10,
        )
    except Exception:
        pass


# =====================
# חישובי שמש
# =====================
def sun_times(now: datetime):
    s = sun(city.observer, date=now.date(), tzinfo=tz)
    return s["sunset"], s["dusk"]


# =====================
# חגים יהודיים לפי ישראל, בלי חול המועד
# =====================
def holiday_name_for_date(py_date):
    heb_date = dates.HebrewDate.from_pydate(py_date)
    return heb_date.holiday(israel=True, include_working_days=False)


def is_shabbat_locked(now: datetime) -> bool:
    sunset, dusk = sun_times(now)

    # שישי: דקות לפני השקיעה
    if now.weekday() == 4 and now >= sunset - timedelta(minutes=PRE_SHABBAT_MINUTES):
        return True

    # שבת: עד 10 דקות אחרי יציאת שבת
    if now.weekday() == 5 and now <= dusk + timedelta(minutes=POST_SHABBAT_MINUTES):
        return True

    return False


def is_holiday_locked(now: datetime) -> bool:
    sunset, dusk = sun_times(now)
    today_holiday = holiday_name_for_date(now.date())
    tomorrow_holiday = holiday_name_for_date(now.date() + timedelta(days=1))

    # ביום חג עצמו: עד 10 דקות אחרי יציאה
    if today_holiday:
        return now <= dusk + timedelta(minutes=POST_SHABBAT_MINUTES)

    # בערב חג: מהשקיעה שלפניו
    if tomorrow_holiday and now >= sunset:
        return True

    return False


def get_mode(now: datetime) -> str:
    if is_shabbat_locked(now):
        return "shabbat"
    if is_holiday_locked(now):
        return "holiday"
    return "regular"


# =====================
# זיהוי תהליכים קיימים לפי שם קובץ
# =====================
def script_from_cmdline(cmdline):
    if not cmdline:
        return None

    for part in cmdline:
        base = os.path.basename(str(part).strip('"').strip("'"))
        if base in FILES:
            return base
    return None


def scan_managed_processes():
    found = {f: [] for f in FILES}

    for proc in psutil.process_iter(attrs=["pid", "cmdline", "name"]):
        try:
            if proc.info["pid"] == os.getpid():
                continue

            script = script_from_cmdline(proc.info.get("cmdline") or [])
            if script:
                found[script].append(proc)

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return found


# =====================
# עצירה/הפעלה
# =====================
def stop_processes(process_list):
    for p in process_list:
        try:
            p.terminate()
        except Exception:
            pass

    deadline = time.time() + 10
    while time.time() < deadline:
        still_alive = []
        for p in process_list:
            try:
                if p.is_running():
                    still_alive.append(p)
            except Exception:
                pass
        if not still_alive:
            return
        time.sleep(0.5)

    for p in process_list:
        try:
            if p.is_running():
                p.kill()
        except Exception:
            pass


def stop_all_running():
    managed = scan_managed_processes()
    unique = {}
    for script, plist in managed.items():
        for p in plist:
            unique[p.pid] = p

    if unique:
        stop_processes(list(unique.values()))


def start_missing():
    managed = scan_managed_processes()

    for script in FILES:
        running = managed.get(script, [])

        alive = []
        for p in running:
            try:
                if p.is_running() and p.status() != psutil.STATUS_ZOMBIE:
                    alive.append(p)
            except Exception:
                pass

        # רק אם אין בכלל תהליך פעיל
        if len(alive) == 0:
            subprocess.Popen([sys.executable, script])

# =====================
# לולאה ראשית
# =====================
def run():
    global last_mode

    # זמן קצר בפתיחה כדי לא ליצור כפילויות עם ה-start command
    while (datetime.now(tz) - started_at).total_seconds() < BOOT_GRACE_SECONDS:
        time.sleep(1)

    while True:
        now = datetime.now(tz)
        mode = get_mode(now)

        if mode != last_mode:
            if mode == "shabbat":
                stop_all_running()
                send("🕯️ הבוט במנוחה בשבת ויחזור לפעילות במוצ\"ש.\nשבת שלום!")

            elif mode == "holiday":
                stop_all_running()
                send("🎉 הבוט לא פעיל בחג.\nחג שמח!")

            elif mode == "regular":
                start_missing()
                send("🚀 הבוט חזר לפעילות!")

            last_mode = mode

        if mode == "regular":
            start_missing()

        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    run()

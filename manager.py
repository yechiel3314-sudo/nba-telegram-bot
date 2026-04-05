import os
import sys
import time
import logging
import subprocess
from datetime import datetime, timedelta

import psutil
import pytz
from astral import LocationInfo
from astral.sun import sun
from pyluach import dates

# =========================================================
# הגדרות
# =========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

FILES = [
    "bot.py",
    "nba.py",
    "clutch.py",
    "ligyonerim.py",
    "winner.py",
    "nba_schedule.py",
]

# כמה דקות לפני שקיעה בשישי לעצור
PRE_SHABBAT_MINUTES = 60

# כמה דקות אחרי צאת שבת/חג לחזור
POST_SHABBAT_MINUTES = 15

# כמה זמן לחכות בתחילת ריצה כדי למנוע כפילויות
BOOT_GRACE_SECONDS = 45

# כל כמה זמן לבדוק
CHECK_EVERY_SECONDS = 60

# אזור זמן ומיקום
tz = pytz.timezone("Asia/Jerusalem")
city = LocationInfo("Tel Aviv", "Israel", "Asia/Jerusalem", 32.0853, 34.7818)

last_mode = None
started_at = datetime.now(tz)

# =========================================================
# לוגים
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOGS_DIR, "manager.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger("manager")


# =========================================================
# בדיקות מערכת
# =========================================================
def check_files_exist():
    logger.info("בודק שכל קבצי הבוטים קיימים...")

    all_ok = True

    for script in FILES:
        path = os.path.join(BASE_DIR, script)
        if os.path.exists(path):
            logger.info(f"קובץ קיים: {script}")
        else:
            logger.error(f"קובץ חסר: {script}")
            all_ok = False

    return all_ok


# =========================================================
# חישובי שקיעה / צאת
# =========================================================
def sun_times(now: datetime):
    """
    מחזיר (שקיעה, צאת) לפי היום הנוכחי.
    מובטח שהזמנים יהיו עם timezone תואם ל-Asia/Jerusalem.
    """
    s = sun(city.observer, date=now.date(), tzinfo=tz)

    sunset = s["sunset"]
    dusk = s["dusk"]

    if sunset.tzinfo is None:
        sunset = tz.localize(sunset)
    else:
        sunset = sunset.astimezone(tz)

    if dusk.tzinfo is None:
        dusk = tz.localize(dusk)
    else:
        dusk = dusk.astimezone(tz)

    return sunset, dusk


# =========================================================
# חגים יהודיים
# =========================================================
def holiday_name_for_date(py_date):
    """
    מחזיר שם חג אם התאריך הוא חג, אחרת None.
    מנסה להיות תואם לגרסאות שונות של pyluach.
    """
    try:
        heb_date = dates.GregorianDate(py_date.year, py_date.month, py_date.day).to_heb()
    except Exception as e:
        logger.exception(f"שגיאה בהמרת תאריך ל-heb: {e}")
        return None

    try:
        holiday = heb_date.holiday(israel=True, include_working_days=False)
    except TypeError:
        try:
            holiday = heb_date.holiday(israel=True)
        except Exception as e:
            logger.exception(f"שגיאה בזיהוי חג: {e}")
            return None
    except Exception as e:
        logger.exception(f"שגיאה בזיהוי חג: {e}")
        return None

    return holiday if holiday else None


def is_shabbat_locked(now: datetime) -> bool:
    sunset, dusk = sun_times(now)

    # שישי - PRE_SHABBAT_MINUTES לפני שקיעה
    if now.weekday() == 4 and now >= sunset - timedelta(minutes=PRE_SHABBAT_MINUTES):
        return True

    # שבת - עד POST_SHABBAT_MINUTES אחרי צאת שבת
    if now.weekday() == 5 and now <= dusk + timedelta(minutes=POST_SHABBAT_MINUTES):
        return True

    return False


def is_holiday_locked(now: datetime) -> bool:
    sunset, dusk = sun_times(now)
    today_holiday = holiday_name_for_date(now.date())
    tomorrow_holiday = holiday_name_for_date(now.date() + timedelta(days=1))

    # ביום חג עצמו: עד X דקות אחרי צאת החג
    if today_holiday:
        return now <= dusk + timedelta(minutes=POST_SHABBAT_MINUTES)

    # ערב חג: מהשקיעה
    if tomorrow_holiday and now >= sunset:
        return True

    return False


def get_mode(now: datetime) -> str:
    if is_shabbat_locked(now):
        return "shabbat"
    if is_holiday_locked(now):
        return "holiday"
    return "regular"


# =========================================================
# זיהוי תהליכים
# =========================================================
def script_from_cmdline(cmdline):
    if not cmdline:
        return None

    for part in cmdline:
        try:
            base = os.path.basename(str(part).strip('"').strip("'"))
            if base in FILES:
                return base
        except Exception:
            continue

    return None


def scan_managed_processes():
    found = {f: [] for f in FILES}

    for proc in psutil.process_iter(attrs=["pid", "cmdline", "status"]):
        try:
            if proc.info["pid"] == os.getpid():
                continue

            cmdline = proc.info.get("cmdline") or []
            script = script_from_cmdline(cmdline)

            if script:
                found[script].append(proc)

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception as e:
            logger.exception(f"שגיאה בסריקת תהליך: {e}")

    return found


def is_process_alive(proc):
    try:
        return proc.is_running() and proc.status() not in [psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD]
    except Exception:
        return False


# =========================================================
# עצירה
# =========================================================
def stop_processes(process_list):
    if not process_list:
        return

    pids = [p.pid for p in process_list]
    logger.info(f"עוצר תהליכים: {pids}")

    for p in process_list:
        try:
            p.terminate()
            logger.info(f"נשלח terminate ל-PID {p.pid}")
        except Exception as e:
            logger.warning(f"terminate נכשל עבור PID {p.pid}: {e}")

    try:
        gone, alive = psutil.wait_procs(process_list, timeout=10)
    except Exception as e:
        logger.warning(f"wait_procs נכשל: {e}")
        alive = process_list

    if not alive:
        logger.info("כל התהליכים נעצרו בהצלחה")
        return

    logger.warning("יש תהליכים שעדיין חיים - מבצע kill")

    for p in alive:
        try:
            if is_process_alive(p):
                p.kill()
                logger.info(f"בוצע KILL ל-PID {p.pid}")
        except Exception as e:
            logger.warning(f"kill נכשל עבור PID {p.pid}: {e}")

    try:
        psutil.wait_procs(alive, timeout=5)
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
    else:
        logger.info("לא נמצאו תהליכים לעצירה")


# =========================================================
# הפעלה
# =========================================================
def start_script(script):
    script_path = os.path.join(BASE_DIR, script)

    if not os.path.exists(script_path):
        logger.error(f"לא ניתן להפעיל - קובץ חסר: {script_path}")
        return False

    log_file_path = os.path.join(LOGS_DIR, f"{os.path.splitext(script)[0]}.log")

    try:
        logger.info(f"מריץ פקודה: {sys.executable} {script_path}")

        with open(log_file_path, "a", encoding="utf-8") as log_file:
            popen_kwargs = dict(
                cwd=BASE_DIR,
                stdout=log_file,
                stderr=log_file,
                stdin=subprocess.DEVNULL,
            )

            # start_new_session מתאים ללינוקס/ריילווי.
            # אם תריץ מקומית ב-Windows, נשתמש בלי זה.
            if os.name != "nt":
                popen_kwargs["start_new_session"] = True

            process = subprocess.Popen(
                [sys.executable, script_path],
                **popen_kwargs,
            )

        logger.info(f"הופעל {script} | PID={process.pid}")
        return True

    except Exception as e:
        logger.exception(f"שגיאה בהפעלת {script}: {e}")
        return False


def start_missing():
    managed = scan_managed_processes()

    for script in FILES:
        running = managed.get(script, [])
        alive = [p for p in running if is_process_alive(p)]

        if len(alive) == 0:
            logger.info(f"{script} לא רץ - מפעיל")
            start_script(script)
        else:
            logger.info(f"{script} כבר רץ | PIDs={[p.pid for p in alive]}")


# =========================================================
# מצב מערכת
# =========================================================
def log_status(mode):
    managed = scan_managed_processes()
    summary = {}

    for script, plist in managed.items():
        alive = []
        for p in plist:
            if is_process_alive(p):
                alive.append(p.pid)
        summary[script] = alive

    logger.info(f"מצב מערכת: {mode} | תהליכים פעילים: {summary}")


# =========================================================
# בדיקות פתיחה
# =========================================================
def startup_checks():
    logger.info("=" * 80)
    logger.info("MANAGER STARTED")
    logger.info("=" * 80)

    if not check_files_exist():
        logger.critical("עצירה: חסרים קבצים.")
        return False

    try:
        now = datetime.now(tz)
        sunset, dusk = sun_times(now)
        logger.info(f"זמן נוכחי: {now}")
        logger.info(f"שקיעה היום: {sunset}")
        logger.info(f"צאת היום: {dusk}")
        logger.info(f"חג היום: {holiday_name_for_date(now.date())}")
        logger.info(f"חג מחר: {holiday_name_for_date(now.date() + timedelta(days=1))}")
        logger.info(f"מצב מחושב כרגע: {get_mode(now)}")
    except Exception as e:
        logger.exception(f"שגיאה בבדיקות פתיחה: {e}")
        return False

    return True


# =========================================================
# לולאה ראשית
# =========================================================
def run():
    global last_mode

    if not startup_checks():
        return

    logger.info(f"ממתין {BOOT_GRACE_SECONDS} שניות כדי למנוע כפילויות...")
    while (datetime.now(tz) - started_at).total_seconds() < BOOT_GRACE_SECONDS:
        time.sleep(1)

    logger.info("מתחיל לולאת ניהול ראשית")

    while True:
        try:
            now = datetime.now(tz)
            mode = get_mode(now)

            logger.info(f"בדיקת מחזור | זמן: {now.strftime('%Y-%m-%d %H:%M:%S')} | mode={mode}")

            if mode != last_mode:
                logger.info(f"שינוי מצב: {last_mode} -> {mode}")

                if mode in ["shabbat", "holiday"]:
                    logger.info("נכנס למצב נעילה - עוצר את כל הבוטים")
                    stop_all_running()

                elif mode == "regular":
                    logger.info("חזר למצב רגיל - מפעיל בוטים חסרים")
                    start_missing()

                last_mode = mode

            if mode == "regular":
                start_missing()

            log_status(mode)

        except Exception as e:
            logger.exception(f"שגיאה בלולאה הראשית: {e}")

        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    run()

import datetime as dt
import html
import json
import logging
import os
import time
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None


# ==========================================
# הגדרות
# ==========================================

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_TOKEN")
    or os.getenv("NBA_BOT_TOKEN")
    or os.getenv("NBA_LIVE_TELEGRAM_BOT_TOKEN_PRIVATE")
    or os.getenv("NETO_SPORT_SHARED_MAIN_TELEGRAM_BOT_TOKEN_PRIVATE")
    or ""
).strip()

# זה המשתנה הפשוט והאחיד לערוץ ה-NBA בכל הקודים.
CHAT_ID = (
    os.getenv("NBA_CHANNEL_ID")
    or os.getenv("NBA_LIVE_TELEGRAM_CHAT_ID_PRIVATE")
    or os.getenv("TELEGRAM_CHAT_ID")
    or os.getenv("CHAT_ID")
    or ""
).strip()

STATE_FILE = os.getenv("STATE_FILE", "nba_summer_results_state.json")
RESULTS_TIME = os.getenv("NBA_SUMMER_RESULTS_TIME", "09:00").strip()
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))
SEND_EMPTY_SUMMER_REPORT = os.getenv("SEND_EMPTY_SUMMER_REPORT", "false").strip().lower() == "true"

ISRAEL_TZID = "Asia/Jerusalem"
NEW_YORK_TZID = "America/New_York"
NBA_LEAGUE_ID = "00"

LIVE_TODAY_SCOREBOARD_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
LIVE_DATE_SCOREBOARD_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/scoreboard_{date}.json"
STATS_SCOREBOARD_URL = "https://stats.nba.com/stats/scoreboardv2"

SUMMER_LEAGUE_GAME_ID_PREFIXES = ("15",)
SUMMER_LEAGUE_KEYWORDS = (
    "summer league",
    "summer",
    "las vegas",
    "california classic",
    "salt lake city",
)

ISRAEL_LAT = 31.778
ISRAEL_LON = 35.235

RLM = "\u200f"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


TEAM_BY_TRICODE = {
    "ATL": "אטלנטה הוקס",
    "BOS": "בוסטון סלטיקס",
    "BKN": "ברוקלין נטס",
    "CHA": "שארלוט הורנטס",
    "CHI": "שיקגו בולס",
    "CLE": "קליבלנד קאבלירס",
    "DAL": "דאלאס מאבריקס",
    "DEN": "דנבר נאגטס",
    "DET": "דטרויט פיסטונס",
    "GSW": "גולדן סטייט ווריורס",
    "HOU": "יוסטון רוקטס",
    "IND": "אינדיאנה פייסרס",
    "LAC": "לוס אנג'לס קליפרס",
    "LAL": "לוס אנג'לס לייקרס",
    "MEM": "ממפיס גריזליס",
    "MIA": "מיאמי היט",
    "MIL": "מילווקי באקס",
    "MIN": "מינסוטה טימברוולבס",
    "NOP": "ניו אורלינס פליקנס",
    "NYK": "ניו יורק ניקס",
    "OKC": "אוקלהומה סיטי ת'אנדר",
    "ORL": "אורלנדו מג'יק",
    "PHI": "פילדלפיה סיקסרס",
    "PHX": "פיניקס סאנס",
    "POR": "פורטלנד טרייל בלייזרס",
    "SAC": "סקרמנטו קינגס",
    "SAS": "סן אנטוניו ספרס",
    "TOR": "טורונטו ראפטורס",
    "UTA": "יוטה ג'אז",
    "WAS": "וושינגטון וויזארדס",
}

TEAM_BY_FULL_NAME = {
    "Atlanta Hawks": "אטלנטה הוקס",
    "Boston Celtics": "בוסטון סלטיקס",
    "Brooklyn Nets": "ברוקלין נטס",
    "Charlotte Hornets": "שארלוט הורנטס",
    "Chicago Bulls": "שיקגו בולס",
    "Cleveland Cavaliers": "קליבלנד קאבלירס",
    "Dallas Mavericks": "דאלאס מאבריקס",
    "Denver Nuggets": "דנבר נאגטס",
    "Detroit Pistons": "דטרויט פיסטונס",
    "Golden State Warriors": "גולדן סטייט ווריורס",
    "Houston Rockets": "יוסטון רוקטס",
    "Indiana Pacers": "אינדיאנה פייסרס",
    "LA Clippers": "לוס אנג'לס קליפרס",
    "Los Angeles Clippers": "לוס אנג'לס קליפרס",
    "Los Angeles Lakers": "לוס אנג'לס לייקרס",
    "Memphis Grizzlies": "ממפיס גריזליס",
    "Miami Heat": "מיאמי היט",
    "Milwaukee Bucks": "מילווקי באקס",
    "Minnesota Timberwolves": "מינסוטה טימברוולבס",
    "New Orleans Pelicans": "ניו אורלינס פליקנס",
    "New York Knicks": "ניו יורק ניקס",
    "Oklahoma City Thunder": "אוקלהומה סיטי ת'אנדר",
    "Orlando Magic": "אורלנדו מג'יק",
    "Philadelphia 76ers": "פילדלפיה סיקסרס",
    "Phoenix Suns": "פיניקס סאנס",
    "Portland Trail Blazers": "פורטלנד טרייל בלייזרס",
    "Sacramento Kings": "סקרמנטו קינגס",
    "San Antonio Spurs": "סן אנטוניו ספרס",
    "Toronto Raptors": "טורונטו ראפטורס",
    "Utah Jazz": "יוטה ג'אז",
    "Washington Wizards": "וושינגטון וויזארדס",
}


# ==========================================
# זמן / לוג
# ==========================================

def tz(name):
    if ZoneInfo:
        return ZoneInfo(name)
    return dt.timezone(dt.timedelta(hours=3)) if name == ISRAEL_TZID else dt.timezone(dt.timedelta(hours=-4))


def now_israel():
    return dt.datetime.now(tz(ISRAEL_TZID))


def log(msg):
    logging.info(msg)


def rtl(text):
    return f"{RLM}{text}{RLM}"


def esc(value):
    return html.escape("" if value is None else str(value))


def parse_hhmm(value):
    hour, minute = value.split(":", 1)
    return int(hour), int(minute)


def should_send_now(now):
    hour, minute = parse_hhmm(RESULTS_TIME)
    send_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return now >= send_at


def report_key_for_today(now):
    return now.date().isoformat()


def candidate_nba_dates(now):
    ny_now = now.astimezone(tz(NEW_YORK_TZID))
    dates = [
        ny_now.date() - dt.timedelta(days=1),
        ny_now.date(),
        ny_now.date() + dt.timedelta(days=1),
    ]
    seen = set()
    out = []
    for d in dates:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


# ==========================================
# HTTP
# ==========================================

def build_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.nba.com/",
        "Origin": "https://www.nba.com",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "x-nba-stats-origin": "stats",
        "x-nba-stats-token": "true",
        "Connection": "keep-alive",
    })

    retry_args = {
        "total": 4,
        "backoff_factor": 1,
        "status_forcelist": [429, 500, 502, 503, 504],
    }
    try:
        retry = Retry(allowed_methods=["GET", "POST"], **retry_args)
    except TypeError:
        retry = Retry(method_whitelist=["GET", "POST"], **retry_args)

    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


SESSION = build_session()


def get_json(url, params=None, use_cdn_proxy=True):
    try:
        response = SESSION.get(url, params=params, timeout=20)
        if response.status_code == 200:
            return response.json()
        log(f"HTTP {response.status_code} for {response.url}")
    except Exception as e:
        log(f"Direct fetch failed for {url}: {e}")

    if not use_cdn_proxy or "cdn.nba.com" not in url:
        return None

    encoded = quote(url, safe="")
    proxy_urls = [
        f"https://api.allorigins.win/raw?url={encoded}",
        f"https://api.allorigins.win/get?url={encoded}",
    ]

    for proxy_url in proxy_urls:
        try:
            log(f"Trying CDN proxy for {url}")
            response = SESSION.get(proxy_url, timeout=25)
            if response.status_code != 200:
                log(f"Proxy HTTP {response.status_code} for {url}")
                continue

            if "/get?" in proxy_url:
                contents = response.json().get("contents")
                return json.loads(contents) if contents else None
            return response.json()
        except Exception as e:
            log(f"Proxy fetch failed for {url}: {e}")

    return None


# ==========================================
# מצב
# ==========================================

def normalize_state(data):
    if not isinstance(data, dict):
        return {"last_results_date": None, "pending_results": None}
    data.setdefault("last_results_date", None)
    data.setdefault("pending_results", None)
    return data


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return normalize_state(json.load(f))
        except Exception as e:
            log(f"שגיאה בטעינת state: {e}")
    return {"last_results_date": None, "pending_results": None}


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"שגיאה בשמירת state: {e}")


# ==========================================
# שבת / חג
# ==========================================

def is_shabbat_or_yom_tov():
    try:
        url = (
            "https://www.hebcal.com/zmanim"
            f"?cfg=json&im=1&latitude={ISRAEL_LAT}&longitude={ISRAEL_LON}&tzid={ISRAEL_TZID}"
        )
        data = get_json(url, use_cdn_proxy=False)
        if not data:
            return False
        return bool((data.get("status") or {}).get("isAssurBemlacha"))
    except Exception as e:
        log(f"שגיאה בבדיקת שבת/חג: {e}")
        return False


# ==========================================
# NBA data
# ==========================================

def safe_int(value, default=0):
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def result_set_rows(data, name):
    for result_set in data.get("resultSets") or []:
        if result_set.get("name") != name:
            continue
        headers = result_set.get("headers") or []
        rows = result_set.get("rowSet") or []
        return [dict(zip(headers, row)) for row in rows]
    return []


def full_team_name(team):
    city = team.get("teamCity") or team.get("city") or ""
    name = team.get("teamName") or team.get("name") or ""
    return f"{city} {name}".strip()


def team_display(team):
    tri = (team.get("teamTricode") or team.get("tricode") or team.get("TEAM_ABBREVIATION") or "").strip()
    full = full_team_name(team)

    if tri in TEAM_BY_TRICODE:
        return TEAM_BY_TRICODE[tri]
    if full in TEAM_BY_FULL_NAME:
        return TEAM_BY_FULL_NAME[full]
    return full or tri or "קבוצה לא ידועה"


def is_summer_league_game(game):
    gid = str(game.get("gameId") or game.get("GAME_ID") or "")
    if gid.startswith(SUMMER_LEAGUE_GAME_ID_PREFIXES):
        return True

    text_fields = [
        game.get("gameLabel"),
        game.get("gameSubLabel"),
        game.get("gameSubtype"),
        game.get("seriesText"),
        game.get("gameCode"),
        game.get("GAMECODE"),
        game.get("_seasonType"),
    ]
    text = " ".join(str(x or "") for x in text_fields).lower()
    return any(keyword in text for keyword in SUMMER_LEAGUE_KEYWORDS)


def normalize_live_game(game):
    home = game.get("homeTeam") or {}
    away = game.get("awayTeam") or {}
    return {
        "gameId": str(game.get("gameId") or ""),
        "gameStatus": safe_int(game.get("gameStatus")),
        "gameStatusText": game.get("gameStatusText") or "",
        "gameTimeUTC": game.get("gameTimeUTC") or "",
        "gameCode": game.get("gameCode") or "",
        "homeTeam": {
            "teamTricode": home.get("teamTricode") or "",
            "teamCity": home.get("teamCity") or "",
            "teamName": home.get("teamName") or "",
            "score": safe_int(home.get("score")),
        },
        "awayTeam": {
            "teamTricode": away.get("teamTricode") or "",
            "teamCity": away.get("teamCity") or "",
            "teamName": away.get("teamName") or "",
            "score": safe_int(away.get("score")),
        },
        "_source": "liveData",
        "_seasonType": "Summer League" if is_summer_league_game(game) else "",
    }


def parse_stats_scoreboard(data):
    game_rows = result_set_rows(data, "GameHeader")
    score_rows = result_set_rows(data, "LineScore")

    teams_by_game = {}
    for row in score_rows:
        gid = str(row.get("GAME_ID") or "")
        team_id = str(row.get("TEAM_ID") or "")
        if not gid or not team_id:
            continue
        teams_by_game.setdefault(gid, {})[team_id] = row

    games = []
    for row in game_rows:
        gid = str(row.get("GAME_ID") or "")
        if not gid:
            continue

        home_id = str(row.get("HOME_TEAM_ID") or "")
        away_id = str(row.get("VISITOR_TEAM_ID") or "")
        home_row = teams_by_game.get(gid, {}).get(home_id, {})
        away_row = teams_by_game.get(gid, {}).get(away_id, {})

        game = {
            "gameId": gid,
            "gameStatus": safe_int(row.get("GAME_STATUS_ID")),
            "gameStatusText": row.get("GAME_STATUS_TEXT") or "",
            "gameTimeUTC": "",
            "gameCode": row.get("GAMECODE") or "",
            "homeTeam": {
                "teamTricode": home_row.get("TEAM_ABBREVIATION") or "",
                "teamCity": home_row.get("TEAM_CITY_NAME") or "",
                "teamName": home_row.get("TEAM_NAME") or "",
                "score": safe_int(home_row.get("PTS")),
            },
            "awayTeam": {
                "teamTricode": away_row.get("TEAM_ABBREVIATION") or "",
                "teamCity": away_row.get("TEAM_CITY_NAME") or "",
                "teamName": away_row.get("TEAM_NAME") or "",
                "score": safe_int(away_row.get("PTS")),
            },
            "_source": "statsScoreboardV2",
            "_seasonType": "Summer League" if gid.startswith(SUMMER_LEAGUE_GAME_ID_PREFIXES) else "",
        }
        games.append(game)

    return games


def fetch_live_games_for_date(nba_date):
    date_key = nba_date.strftime("%Y%m%d")
    urls = [
        LIVE_DATE_SCOREBOARD_URL.format(date=date_key),
    ]

    # היום הנוכחי נשמר אצל NBA גם בקובץ todaysScoreboard.
    if nba_date == dt.datetime.now(tz(NEW_YORK_TZID)).date():
        urls.append(LIVE_TODAY_SCOREBOARD_URL)

    games = []
    for url in urls:
        data = get_json(url)
        raw_games = (((data or {}).get("scoreboard") or {}).get("games") or [])
        games.extend(normalize_live_game(g) for g in raw_games)
    return games


def fetch_stats_games_for_date(nba_date):
    data = get_json(
        STATS_SCOREBOARD_URL,
        params={
            "GameDate": nba_date.strftime("%m/%d/%Y"),
            "LeagueID": NBA_LEAGUE_ID,
            "DayOffset": "0",
        },
        use_cdn_proxy=False,
    )
    if not data:
        return []
    return parse_stats_scoreboard(data)


def fetch_summer_league_games(now):
    games_by_id = {}

    for nba_date in candidate_nba_dates(now):
        for game in fetch_live_games_for_date(nba_date):
            gid = game.get("gameId")
            if gid:
                games_by_id[gid] = game

        for game in fetch_stats_games_for_date(nba_date):
            gid = game.get("gameId")
            if gid and gid not in games_by_id:
                games_by_id[gid] = game

    games = [
        game for game in games_by_id.values()
        if is_summer_league_game(game) and safe_int(game.get("gameStatus")) == 3
    ]

    return sorted(games, key=lambda g: g.get("gameId") or "")


# ==========================================
# בניית הודעה
# ==========================================

def winner_loser(game):
    home = game.get("homeTeam") or {}
    away = game.get("awayTeam") or {}
    home_score = safe_int(home.get("score"))
    away_score = safe_int(away.get("score"))

    if home_score >= away_score:
        return home, home_score, away, away_score
    return away, away_score, home, home_score


def game_line(game):
    winner, winner_score, loser, loser_score = winner_loser(game)
    winner_name = team_display(winner)
    loser_name = team_display(loser)

    return "\n".join([
        rtl(f"🏆 <b>{esc(winner_name)} {winner_score}</b>"),
        rtl(f"🔹 {esc(loser_name)} {loser_score}"),
    ])


def get_results_msg(games, report_date):
    if not games:
        if not SEND_EMPTY_SUMMER_REPORT:
            return None
        return "\n".join([
            rtl("☀️🏀 <b>תוצאות משחקי הלילה בליגת הקיץ ב-NBA</b> 🏀☀️"),
            "",
            rtl("לא נמצאו משחקי ליגת קיץ שהסתיימו הלילה."),
        ])

    lines = [
        rtl("☀️🏀 <b>תוצאות משחקי הלילה בליגת הקיץ ב-NBA</b> 🏀☀️"),
        rtl(f"📅 {esc(report_date)}"),
        "",
    ]

    for game in games:
        lines.append(game_line(game))
        lines.append("")

    return "\n".join(lines).strip()


# ==========================================
# טלגרם
# ==========================================

def send_to_telegram(text):
    if not text:
        return False

    if not TELEGRAM_TOKEN:
        log("חסר TELEGRAM_TOKEN / NBA_BOT_TOKEN / NBA_LIVE_TELEGRAM_BOT_TOKEN_PRIVATE")
        return False

    if not CHAT_ID:
        log("חסר NBA_CHANNEL_ID")
        return False

    try:
        response = SESSION.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text[:4096],
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        if response.status_code == 200:
            log("הודעת תוצאות נשלחה בהצלחה")
            return True

        log(f"שגיאת טלגרם {response.status_code}: {response.text}")
        return False
    except Exception as e:
        log(f"שגיאה בשליחה לטלגרם: {e}")
        return False


def try_send_pending(state):
    pending = state.get("pending_results")
    if not pending:
        return

    message = pending.get("message")
    pending_date = pending.get("date")
    if not message:
        state["pending_results"] = None
        save_state(state)
        return

    ok = send_to_telegram(message)
    if ok:
        state["last_results_date"] = pending_date
        state["pending_results"] = None
        save_state(state)
        log(f"הודעת תוצאות מושהית נשלחה עבור {pending_date}")


# ==========================================
# לולאה ראשית
# ==========================================

def build_and_store_or_send_report(state, now, blocked_now):
    today_key = report_key_for_today(now)
    games = fetch_summer_league_games(now)
    message = get_results_msg(games, today_key)

    if not message:
        state["last_results_date"] = today_key
        save_state(state)
        log("לא נמצאו משחקי ליגת קיץ לשליחה")
        return

    if blocked_now:
        state["pending_results"] = {
            "date": today_key,
            "message": message,
        }
        state["last_results_date"] = today_key
        save_state(state)
        log("שבת/חג פעיל - הודעת התוצאות נשמרה לשליחה מאוחרת")
        return

    ok = send_to_telegram(message)
    if ok:
        state["last_results_date"] = today_key
        save_state(state)
        log(f"הודעת תוצאות יומית הושלמה עבור {today_key}")


def run():
    log("NBA SUMMER LEAGUE MORNING RESULTS BOT STARTED")
    state = load_state()

    while True:
        try:
            now = now_israel()
            today_key = report_key_for_today(now)
            blocked_now = is_shabbat_or_yom_tov()

            if not blocked_now and state.get("pending_results"):
                try_send_pending(state)
                state = load_state()

            if should_send_now(now) and state.get("last_results_date") != today_key:
                build_and_store_or_send_report(state, now, blocked_now)
                state = load_state()

        except Exception as e:
            log(f"שגיאה בלולאה הראשית: {e}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()

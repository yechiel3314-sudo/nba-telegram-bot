import datetime
import html
import json
import logging
import os
import re
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
# Settings
# ==========================================
TOKEN = (
    os.getenv("TELEGRAM_TOKEN")
    or os.getenv("NBA_BOT_TOKEN")
    or os.getenv("NBA_LIVE_TELEGRAM_BOT_TOKEN_PRIVATE")
    or os.getenv("NETO_SPORT_SHARED_MAIN_TELEGRAM_BOT_TOKEN_PRIVATE")
    or ""
).strip()
CHAT_ID = (
    os.getenv("NBA_CHANNEL_ID")
    or os.getenv("NBA_LIVE_TELEGRAM_CHAT_ID_PRIVATE")
    or os.getenv("TELEGRAM_NBA_CHANNEL_ID")
    or os.getenv("TELEGRAM_CHAT_ID")
    or os.getenv("CHAT_ID")
    or "-1003808107418"
).strip()
STATE_FILE = os.getenv("STATE_FILE", "nba_israeli_state.json")

MESSAGE_DELAY_SECONDS = int(os.getenv("MESSAGE_DELAY_SECONDS", "20"))
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "20"))

ISRAEL_LAT = 31.778
ISRAEL_LON = 35.235
ISRAEL_TZID = "Asia/Jerusalem"

NBA_LEAGUE_ID = "00"
LIVE_SCOREBOARD_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
LIVE_BOX_URL = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
STATS_SCOREBOARD_URL = "https://stats.nba.com/stats/scoreboardv2"
STATS_BOX_URL = "https://stats.nba.com/stats/boxscoretraditionalv2"

# NBA Summer League game ids commonly start with 15, for example 15224xxxxx.
SUMMER_LEAGUE_GAME_ID_PREFIXES = ("15",)
SUMMER_LEAGUE_KEYWORDS = (
    "summer league",
    "summer",
    "las vegas",
    "california classic",
    "salt lake city",
)

PLAYER_HEBREW_NAMES = {
    "Deni Avdija": "דני אבדיה",
    "Ben Saraf": "בן שרף",
    "Danny Wolf": "דני וולף",
    "Emanuel Sharp": "עמנואל שארפ",
}

PLAYER_ALIASES = {
    "Emanuel Christopher Sharp": "Emanuel Sharp",
    "E. Sharp": "Emanuel Sharp",
}

PLAYER_IMAGES = {
    "Danny Wolf": "https://pbs.twimg.com/media/HCXLU3mbAAAd_Ma?format=jpg&name=small",
    "Ben Saraf": "https://pbs.twimg.com/media/HET8BYNXMAAI9zl?format=jpg&name=small",
    "Deni Avdija": "https://pbs.twimg.com/media/HE9V4E8bQAA_Kqo?format=jpg&name=large",
    "Emanuel Sharp": os.getenv(
        "EMANUEL_SHARP_IMAGE_URL",
        "https://i.ibb.co/hRZvDBHc/Gemini-Generated-Image-8cndu08cndu08cnd.png",
    ).strip(),
}

ISRAELI_PLAYERS = set(PLAYER_HEBREW_NAMES.keys())

TEAM_HEBREW = {
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
RLM = "\u200F"


# ==========================================
# Session / HTTP
# ==========================================
def build_session():
    s = requests.Session()
    s.headers.update({
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

    retry_kwargs = {
        "total": 4,
        "backoff_factor": 1,
        "status_forcelist": [429, 500, 502, 503, 504],
    }
    try:
        retry = Retry(allowed_methods=["GET", "POST"], **retry_kwargs)
    except TypeError:
        retry = Retry(method_whitelist=["GET", "POST"], **retry_kwargs)

    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


SESSION = build_session()


def _parse_json_response(response):
    text = response.text.strip()
    if not text:
        return None
    return response.json()


def get_json(url, params=None, use_cdn_proxy=True):
    try:
        r = SESSION.get(url, params=params, timeout=18)
        if r.status_code == 200:
            return _parse_json_response(r)
        logging.warning("HTTP %s for %s", r.status_code, r.url)
    except Exception as e:
        if "hebcal" in url:
            logging.error("Direct Hebcal fetch failed: %s", e)
            return None
        logging.warning("Direct fetch failed for %s: %s", url, e)

    if not use_cdn_proxy or "cdn.nba.com" not in url:
        return None

    encoded_url = quote(url, safe="")
    proxy_urls = [
        f"https://api.allorigins.win/raw?url={encoded_url}",
        f"https://api.allorigins.win/get?url={encoded_url}",
    ]

    for proxy_url in proxy_urls:
        try:
            logging.info("Trying NBA CDN proxy for %s", url)
            r = SESSION.get(proxy_url, timeout=25)
            if r.status_code != 200:
                logging.warning("Proxy HTTP %s for %s", r.status_code, url)
                continue

            if "/get?" in proxy_url:
                contents = r.json().get("contents")
                return json.loads(contents) if contents else None
            return r.json()
        except Exception as e:
            logging.error("Proxy fetch failed for %s: %s", url, e)

    return None


# ==========================================
# Shabbat / Yom Tov
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

        status = data.get("status") or {}
        return bool(status.get("isAssurBemlacha"))
    except Exception as e:
        logging.error("Shabbat/Yom Tov check failed: %s", e)
        return False


# ==========================================
# State
# ==========================================
def normalize_state(data):
    if not isinstance(data, dict):
        return {"games": {}, "pending": {}}

    if not isinstance(data.get("games"), dict):
        data["games"] = {}

    if not isinstance(data.get("pending"), dict):
        data["pending"] = {}

    for game_state in data["games"].values():
        if not isinstance(game_state, dict):
            continue
        if not isinstance(game_state.get("events"), list):
            game_state["events"] = []

    return data


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return normalize_state(json.load(f))
        except Exception as e:
            logging.error("Failed loading state: %s", e)
    return {"games": {}, "pending": {}}


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error("Failed saving state: %s", e)


def event_key(stage_key, player_name_en):
    return f"{stage_key}:{player_name_en}"


def was_event_sent(state, gid, event):
    gs = state["games"].setdefault(gid, {"events": []})
    return event in gs["events"]


def mark_event_sent(state, gid, event):
    gs = state["games"].setdefault(gid, {"events": []})
    if event not in gs["events"]:
        gs["events"].append(event)


def queue_pending_message(state, gid, player_name_en, event, message):
    if gid not in state["pending"]:
        state["pending"][gid] = {}
    state["pending"][gid][player_name_en] = {
        "event": event,
        "message": message,
    }


def flush_pending_messages(state):
    pending = state.get("pending") or {}
    if not pending:
        return

    remaining = {}

    for gid, players_payload in pending.items():
        if not isinstance(players_payload, dict):
            continue

        for player_name_en, payload in players_payload.items():
            try:
                message = payload.get("message")
                event = payload.get("event") or payload.get("stage")

                if not message or not event:
                    continue

                ok = send_player_message(player_name_en, message)
                if ok:
                    mark_event_sent(state, gid, event)
                    time.sleep(MESSAGE_DELAY_SECONDS)
                else:
                    remaining.setdefault(gid, {})[player_name_en] = payload
            except Exception as e:
                logging.error("Failed flushing pending message for %s: %s", player_name_en, e)
                remaining.setdefault(gid, {})[player_name_en] = payload

    state["pending"] = remaining
    save_state(state)


# ==========================================
# Helpers / Formatters
# ==========================================
def safe_int(raw, default=0):
    try:
        if raw is None or raw == "":
            return default
        return int(float(raw))
    except (TypeError, ValueError):
        return default


def stat_value(raw, default=0):
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
        if value.is_integer():
            return int(value)
        return value
    except (TypeError, ValueError):
        return raw


def stats_minutes_to_duration(raw):
    if not raw:
        return "PT0M0S"

    s = str(raw).strip()
    if s.startswith("PT"):
        return s

    m = re.match(r"^(\d+):(\d{1,2})(?:\.\d+)?$", s)
    if m:
        return f"PT{int(m.group(1))}M{int(m.group(2))}.00S"

    try:
        total_minutes = float(s)
    except ValueError:
        return "PT0M0S"

    mins = int(total_minutes)
    secs = int(round((total_minutes - mins) * 60))
    if secs >= 60:
        mins += secs // 60
        secs %= 60
    return f"PT{mins}M{secs}.00S"


def format_minutes_seconds(raw):
    if not raw:
        return "00:00"

    s = str(raw).strip()

    direct = re.match(r"^(\d+):(\d{1,2})(?:\.\d+)?$", s)
    if direct:
        return f"{int(direct.group(1)):02}:{int(direct.group(2)):02}"

    m = re.match(r"^PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$", s)
    if not m:
        return "00:00"

    mins = int(m.group(1) or 0)
    secs = float(m.group(2) or 0)
    secs_int = int(round(secs))

    if secs_int >= 60:
        mins += secs_int // 60
        secs_int %= 60

    return f"{mins:02}:{secs_int:02}"


def format_plus_minus(raw):
    try:
        v = float(raw or 0)
    except (TypeError, ValueError):
        return "0"

    if v == 0:
        return "0"
    if v.is_integer():
        return f"{int(v):+}"
    return f"{v:+.1f}".rstrip("0").rstrip(".")


def is_played(mins_raw):
    return format_minutes_seconds(mins_raw) != "00:00"


def rtl(text):
    return f"{RLM}{text}{RLM}"


def esc(text):
    return html.escape("" if text is None else str(text))


def player_full_name(player):
    full = f"{player.get('firstName', '')} {player.get('familyName', '')}".strip()
    return full or player.get("name") or player.get("playerName") or ""


def normalize_name(name):
    return re.sub(r"[^a-z]", "", str(name).lower())


def tracked_player_name(raw_name):
    if not raw_name:
        return None

    if raw_name in PLAYER_ALIASES:
        return PLAYER_ALIASES[raw_name]

    if raw_name in ISRAELI_PLAYERS:
        return raw_name

    normalized = normalize_name(raw_name)
    for known in ISRAELI_PLAYERS:
        if normalize_name(known) == normalized:
            return known

    return None


def split_player_name(full_name):
    parts = str(full_name or "").strip().split(" ", 1)
    if not parts or not parts[0]:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def result_set_rows(data, set_name):
    for result_set in data.get("resultSets") or []:
        if result_set.get("name") != set_name:
            continue
        headers = result_set.get("headers") or []
        rows = result_set.get("rowSet") or []
        return [dict(zip(headers, row)) for row in rows]
    return []


# ==========================================
# NBA data
# ==========================================
def is_summer_league_game(game):
    gid = str(game.get("gameId") or game.get("GAME_ID") or "")
    if gid.startswith(SUMMER_LEAGUE_GAME_ID_PREFIXES):
        return True

    text_fields = [
        game.get("gameLabel"),
        game.get("gameSubLabel"),
        game.get("gameSubtype"),
        game.get("seriesText"),
        game.get("ifNecessary"),
        game.get("gameCode"),
        game.get("_seasonType"),
    ]
    text = " ".join(str(x or "") for x in text_fields).lower()
    return any(keyword in text for keyword in SUMMER_LEAGUE_KEYWORDS)


def stats_game_dates_to_check():
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    if ZoneInfo:
        base_date = now_utc.astimezone(ZoneInfo("America/New_York")).date()
    else:
        base_date = (now_utc + datetime.timedelta(hours=-4)).date()

    return [
        (base_date + datetime.timedelta(days=offset)).strftime("%m/%d/%Y")
        for offset in (-1, 0, 1)
    ]


def fetch_live_scoreboard_games():
    sb = get_json(LIVE_SCOREBOARD_URL)
    if not sb:
        return []

    games = (((sb or {}).get("scoreboard") or {}).get("games") or [])
    for game in games:
        game["_source"] = "liveData"
    return games


def parse_stats_scoreboard(data):
    game_headers = result_set_rows(data, "GameHeader")
    line_scores = result_set_rows(data, "LineScore")

    teams_by_game = {}
    for row in line_scores:
        gid = str(row.get("GAME_ID") or "")
        team_id = str(row.get("TEAM_ID") or "")
        if not gid or not team_id:
            continue
        teams_by_game.setdefault(gid, {})[team_id] = row

    games = []
    for row in game_headers:
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
            "period": safe_int(row.get("LIVE_PERIOD")),
            "gameCode": row.get("GAMECODE") or "",
            "awayTeam": {
                "teamId": away_id,
                "teamTricode": away_row.get("TEAM_ABBREVIATION") or "",
            },
            "homeTeam": {
                "teamId": home_id,
                "teamTricode": home_row.get("TEAM_ABBREVIATION") or "",
            },
            "_source": "statsScoreboardV2",
            "_seasonType": "Summer League" if gid.startswith(SUMMER_LEAGUE_GAME_ID_PREFIXES) else "",
        }
        games.append(game)

    return games


def fetch_stats_summer_games():
    games = []
    for game_date in stats_game_dates_to_check():
        data = get_json(
            STATS_SCOREBOARD_URL,
            params={
                "GameDate": game_date,
                "LeagueID": NBA_LEAGUE_ID,
                "DayOffset": "0",
            },
            use_cdn_proxy=False,
        )
        if not data:
            continue

        for game in parse_stats_scoreboard(data):
            if is_summer_league_game(game):
                games.append(game)

    return games


def fetch_scoreboard_games():
    games_by_id = {}

    for game in fetch_live_scoreboard_games():
        gid = str(game.get("gameId") or "")
        if gid:
            games_by_id[gid] = game

    for game in fetch_stats_summer_games():
        gid = str(game.get("gameId") or "")
        if gid and gid not in games_by_id:
            games_by_id[gid] = game

    return list(games_by_id.values())


def stats_player_to_live_player(row):
    full_name = row.get("PLAYER_NAME") or ""
    first, family = split_player_name(full_name)
    comment = row.get("COMMENT") or ""

    return {
        "firstName": first,
        "familyName": family,
        "name": full_name,
        "status": "INACTIVE" if "inactive" in comment.lower() else "ACTIVE",
        "statistics": {
            "minutesCalculated": stats_minutes_to_duration(row.get("MIN")),
            "points": stat_value(row.get("PTS")),
            "fieldGoalsMade": stat_value(row.get("FGM")),
            "fieldGoalsAttempted": stat_value(row.get("FGA")),
            "threePointersMade": stat_value(row.get("FG3M")),
            "threePointersAttempted": stat_value(row.get("FG3A")),
            "freeThrowsMade": stat_value(row.get("FTM")),
            "freeThrowsAttempted": stat_value(row.get("FTA")),
            "reboundsTotal": stat_value(row.get("REB")),
            "assists": stat_value(row.get("AST")),
            "steals": stat_value(row.get("STL")),
            "blocks": stat_value(row.get("BLK")),
            "turnovers": stat_value(row.get("TO")),
            "plusMinusPoints": stat_value(row.get("PLUS_MINUS")),
        },
    }


def fetch_stats_boxscore_game(gid, game_info):
    data = get_json(
        STATS_BOX_URL,
        params={
            "GameID": gid,
            "StartPeriod": "0",
            "EndPeriod": "0",
            "StartRange": "0",
            "EndRange": "0",
            "RangeType": "0",
        },
        use_cdn_proxy=False,
    )
    if not data:
        return None

    rows = result_set_rows(data, "PlayerStats")
    if not rows:
        return None

    away = game_info.get("away") or ""
    home = game_info.get("home") or ""
    away_players = []
    home_players = []

    for row in rows:
        team_abbr = row.get("TEAM_ABBREVIATION") or ""
        player = stats_player_to_live_player(row)
        if team_abbr == home:
            home_players.append(player)
        else:
            away_players.append(player)

    return {
        "gameId": gid,
        "awayTeam": {"teamTricode": away, "players": away_players},
        "homeTeam": {"teamTricode": home, "players": home_players},
    }


def fetch_boxscore_game(gid, game_info):
    box = get_json(LIVE_BOX_URL.format(gid=gid))
    game = (box or {}).get("game") if isinstance(box, dict) else None
    if isinstance(game, dict):
        return game

    if is_summer_league_game({"gameId": gid, "_seasonType": game_info.get("season_type", "")}):
        return fetch_stats_boxscore_game(gid, game_info)

    return None


def scoreboard_game_info(game):
    away = (game.get("awayTeam") or {}).get("teamTricode") or ""
    home = (game.get("homeTeam") or {}).get("teamTricode") or ""

    return {
        "away": away,
        "home": home,
        "is_summer_league": is_summer_league_game(game),
        "season_type": game.get("_seasonType") or "",
    }


# ==========================================
# Message builder
# ==========================================
def build_msg(player, stage_text, game_info, player_name_en=None):
    full = player_name_en or tracked_player_name(player_full_name(player)) or player_full_name(player)

    if player.get("status") == "INACTIVE":
        return None

    stats = player.get("statistics") or {}
    mins_raw = stats.get("minutesCalculated")
    played = is_played(mins_raw)

    name_he = PLAYER_HEBREW_NAMES.get(full, full)
    away_he = TEAM_HEBREW.get(game_info["away"], game_info["away"])
    home_he = TEAM_HEBREW.get(game_info["home"], game_info["home"])

    lines = [
        rtl(f"🇮🇱 <b>לגיונרים: {esc(name_he)}</b> 🇮🇱"),
        "",
        rtl(f"🏀 <b>{esc(away_he)} 🆚 {esc(home_he)}</b> 🏀"),
    ]

    if game_info.get("is_summer_league"):
        lines.extend(["", rtl("☀️ <b>ליגת הקיץ</b>")])

    lines.extend([
        "",
        rtl("📊 <b>סטטיסטיקה מלאה:</b>"),
        rtl(f"<b>{esc(stage_text)}</b>"),
        "",
    ])

    if not played:
        if "סיום המשחק" in stage_text:
            lines.append(rtl("⏳ <b>לא שותף במשחק</b>"))
        else:
            lines.append(rtl("⏳ <b>טרם עלה לפרקט</b>"))
    else:
        def g(key):
            return stats.get(key) or 0

        lines.extend([
            rtl(f"🎯 <b>נקודות:</b> {g('points')}"),
            rtl(
                f"🏀 <b>מהשדה:</b> {g('fieldGoalsMade')}/{g('fieldGoalsAttempted')} | "
                f"<b>לשלוש:</b> {g('threePointersMade')}/{g('threePointersAttempted')} | "
                f"<b>מהעונשין:</b> {g('freeThrowsMade')}/{g('freeThrowsAttempted')}"
            ),
            rtl(f"💪 <b>ריבאונדים:</b> {g('reboundsTotal')}"),
            rtl(f"🤝 <b>אסיסטים:</b> {g('assists')}"),
            rtl(f"🧤 <b>חטיפות:</b> {g('steals')}"),
            rtl(f"🚫 <b>חסימות:</b> {g('blocks')}"),
            rtl(f"⚠️ <b>איבודים:</b> {g('turnovers')}"),
            rtl(f"📊 <b>פלוס מינוס:</b> {format_plus_minus(g('plusMinusPoints'))}"),
            rtl(f"🕒 <b>דקות:</b> {format_minutes_seconds(mins_raw)}"),
        ])

    return "\n".join(lines)


def stage_from_game(game):
    status = safe_int(game.get("gameStatus"))
    period = safe_int(game.get("period"))
    txt = str(game.get("gameStatusText") or "").lower()

    if status == 3:
        ot = max(0, period - 4)
        if ot == 0:
            return "FINAL", "🏁 סיום המשחק 🏁"
        return f"FINAL_OT_{ot}", f"🏁 סיום המשחק לאחר הארכה {ot} 🏁"

    if is_summer_league_game(game):
        return None, None

    if "end" in txt or "half" in txt or "final" in txt:
        if period == 1:
            return "Q1_END", "⏱️ סוף רבע 1 ⏱️"
        if period == 2:
            return "HALFTIME", "⏱️ מחצית ⏱️"
        if period == 3:
            return "Q3_END", "⏱️ סוף רבע 3 ⏱️"
        if period == 4:
            return "Q4_END", "⏱️ סוף רבע 4 ⏱️"

    return None, None


def is_final_stage_key(stage_key):
    return bool(stage_key) and stage_key.startswith("FINAL")


# ==========================================
# Telegram
# ==========================================
def telegram_send_message(text):
    if not TOKEN:
        logging.error("TELEGRAM_TOKEN is missing; message was not sent.")
        return False

    try:
        r = SESSION.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logging.error("sendMessage failed: %s", e)
        return False


def telegram_send_photo(photo_url, caption):
    if not TOKEN:
        logging.error("TELEGRAM_TOKEN is missing; photo was not sent.")
        return False

    try:
        r = SESSION.post(
            f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
            json={
                "chat_id": CHAT_ID,
                "photo": photo_url,
                "caption": caption,
                "parse_mode": "HTML",
            },
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logging.error("sendPhoto failed: %s", e)
        return False


def send_player_message(player_name_en, message):
    photo = PLAYER_IMAGES.get(player_name_en)

    if photo and photo.startswith(("http://", "https://")) and len(message) <= 1024:
        ok = telegram_send_photo(photo, message)
        if ok:
            return True

    return telegram_send_message(message)


# ==========================================
# Main loop
# ==========================================
def handle_game(state, game, shabbat_or_yom_tov):
    gid = str(game.get("gameId") or "")
    if not gid:
        return False

    state["games"].setdefault(gid, {"events": []})

    stage_key, stage_text = stage_from_game(game)
    if not stage_key or not stage_text:
        return False

    game_info = scoreboard_game_info(game)
    box_game = fetch_boxscore_game(gid, game_info)
    if not box_game or not isinstance(box_game, dict):
        logging.warning("Boxscore data unavailable or unexpected for game %s", gid)
        return False

    away = (box_game.get("awayTeam") or {}).get("teamTricode") or game_info["away"]
    home = (box_game.get("homeTeam") or {}).get("teamTricode") or game_info["home"]
    game_info.update({"away": away, "home": home})

    state_dirty = False

    for team_key in ("awayTeam", "homeTeam"):
        team_data = box_game.get(team_key) or {}
        players = team_data.get("players") or []
        if not isinstance(players, list):
            continue

        for player in players:
            canonical_name = tracked_player_name(player_full_name(player))
            if not canonical_name:
                continue

            event = event_key(stage_key, canonical_name)
            if was_event_sent(state, gid, event):
                continue

            msg = build_msg(player, stage_text, game_info, canonical_name)
            if not msg:
                mark_event_sent(state, gid, event)
                state_dirty = True
                continue

            if shabbat_or_yom_tov:
                if is_final_stage_key(stage_key):
                    queue_pending_message(state, gid, canonical_name, event, msg)
                    state_dirty = True
                continue

            ok = send_player_message(canonical_name, msg)
            if ok:
                mark_event_sent(state, gid, event)
                state_dirty = True
            time.sleep(MESSAGE_DELAY_SECONDS)

    return state_dirty


def run():
    state = load_state()
    logging.info("Bot started...")

    while True:
        state_dirty = False

        try:
            shabbat_or_yom_tov = is_shabbat_or_yom_tov()

            if not shabbat_or_yom_tov and state.get("pending"):
                flush_pending_messages(state)
                state = load_state()

            games = fetch_scoreboard_games()
            if not games:
                time.sleep(POLL_SECONDS)
                continue

            for game in games:
                if handle_game(state, game, shabbat_or_yom_tov):
                    state_dirty = True

            if state_dirty:
                save_state(state)
        except Exception as e:
            logging.error("Main loop error: %s", e)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()

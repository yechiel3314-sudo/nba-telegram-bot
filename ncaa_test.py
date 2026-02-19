import requests
import time
from datetime import datetime
import pytz
from deep_translator import GoogleTranslator

# --- הגדרות טכניות ---
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"
CHAT_ID = "-1003808107418"
NCAA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
NBA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

translator = GoogleTranslator(source='en', target='iw')
RTL_MARK = "\u200f" 

# --- מילון שחקני NBA ---
NBA_DATABASE = {
    "Deni Avdija": ["דני אבדיה", "פורטלנד", "Trail Blazers"],
    "Danny Wolf": ["דני וולף", "ברוקלין", "Nets"]
}

# --- מילון שחקני ליגת הפיתוח (G-League) ---
GLEAGUE_DATABASE = {
    "Ben Saraf": ["בן שרף", "ברוקלין/G-League", "Long Island Nets", "Blue Coats", "Squadron"]
}

# --- מילון שחקני מכללות (NCAA) ---
NCAA_DATABASE = {
    "Emanuel Sharp": ["עמנואל שארפ", "יוסטון", "Houston"],
    "Yoav Berman": ["יואב ברמן", "קווינס", "Queens"],
    "Ofri Naveh": ["עופרי נווה", "אורל רוברטס", "Oral Roberts"],
    "Daniel Gueta": ["דניאל גואטה", "אוקלהומה סטייט", "Oklahoma State"]
}

def tr(text):
    try:
        translated = translator.translate(text)
        return translated.replace("שבילים בלייזרים", "פורטלנד").replace("רשתות", "ברוקלין")
    except:
        return text

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except:
        pass

def get_combined_schedule():
    nba_games = []
    gleague_games = []
    ncaa_games = []

    # --- סריקת NBA ---
    try:
        nba_resp = requests.get(NBA_SCOREBOARD, timeout=10).json()
        for ev in nba_resp.get("events", []):
            teams_in_game = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
            for p_name, info in NBA_DATABASE.items():
                if any(info[2] in t_name for t_name in teams_in_game):
                    vs_team = [t for t in teams_in_game if info[2] not in t][0]
                    game_time_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    game_time_il = game_time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    line = f"{RTL_MARK}🏀 *{info[0]}* ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs_team)}*\n{RTL_MARK}⏰ שעה: *{game_time_il.strftime('%H:%M')}*"
                    nba_games.append(line)
    except: pass

    # --- סריקת G-League + NCAA ---
    try:
        ncaa_resp = requests.get(NCAA_SCOREBOARD, timeout=10).json()
        for ev in ncaa_resp.get("events", []):
            teams_in_game = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
            
            # בדיקת בן שרף ב-G-League
            for p_name, info in GLEAGUE_DATABASE.items():
                if any(k in t_name for k in info[2:] for t_name in teams_in_game):
                    vs_team = [t for t in teams_in_game if not any(k in t for k in info[2:])][0]
                    game_time_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    game_time_il = game_time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    line = f"{RTL_MARK}🏀 *{info[0]}* ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs_team)}*\n{RTL_MARK}⏰ שעה: *{game_time_il.strftime('%H:%M')}*"
                    gleague_games.append(line)

            # בדיקת מכללות
            for p_name, info in NCAA_DATABASE.items():
                if any(info[2] in t_name for t_name in teams_in_game):
                    vs_team = [t for t in teams_in_game if info[2] not in t][0]
                    game_time_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    game_time_il = game_time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    line = f"{RTL_MARK}🏀 *{info[0]}* ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs_team)}*\n{RTL_MARK}⏰ שעה: *{game_time_il.strftime('%H:%M')}*"
                    ncaa_games.append(line)
    except: pass

    # --- בניית ההודעה הסופית ---
    full_message = ""
    if nba_games:
        full_message += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה ב-NBA** 🇮🇱\n\n" + "\n\n".join(list(set(nba_games))) + "\n\n"
    
    if gleague_games:
        full_message += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים בליגת הפיתוח (G-League)** 🇮🇱\n\n" + "\n\n".join(list(set(gleague_games))) + "\n\n"

    if ncaa_games:
        full_message += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה במכללות** 🇮🇱\n\n" + "\n\n".join(list(set(ncaa_games)))

    if full_message:
        send_telegram(full_message)
    else:
        send_telegram(f"{RTL_MARK}🇮🇱 **אין משחקי לגיונרים מתוכננים להלילה** 😴")

if __name__ == "__main__":
    print("🚀 בוט במבנה מורחב פעיל. לו\"ז מתוזמן ל-18:30...")
    last_day = ""
    while True:
        try:
            now = datetime.now(pytz.timezone('Asia/Jerusalem'))
            today = now.strftime("%Y-%m-%d")

            # שליחת לו"ז בערב
            if now.hour == 18 and now.minute == 30 and last_day != today:
                get_combined_schedule()
                last_day = today
                
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(30)

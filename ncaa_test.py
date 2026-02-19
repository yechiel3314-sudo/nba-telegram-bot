import requests
import time
from datetime import datetime
import pytz
from deep_translator import GoogleTranslator

# ==========================================
# --- הגדרות טכניות ומפתחות גישה ---
# ==========================================

# טוקן הבוט שקיבלת מ-BotFather
TOKEN = "8514837332:AAFZmYxXJS43Dpz2x-1rM_Glpske3OxTJrE"

# מזהה הצ'אט/ערוץ אליו יישלחו ההודעות
CHAT_ID = "-1003808107418"

# כתובות ה-API הרשמיות של ESPN לנתוני ספורט בזמן אמת
# NCAA משמש גם לנתוני ליגת הפיתוח (G-League) ברוב המקרים ב-API הציבורי
NCAA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
NBA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

# הגדרת מתרגם אוטומטי מאנגלית לעברית
translator = GoogleTranslator(source='en', target='iw')

# תו מיוחד ב-Unicode לכיווניות טקסט מימין לשמאל (RTL) בטלגרם
RTL_MARK = "\u200f" 

# מילון זיכרון לשמירת מצב השחקנים (מונע כפילויות של הודעות פציעה)
status_cache = {} 

# ==========================================
# --- בסיסי נתונים - רשימת הלגיונרים המלאה ---
# ==========================================

# שחקנים הרשומים בסגלי ה-NBA
NBA_DATABASE = {
    "Deni Avdija": ["דני אבדיה", "פורטלנד", "Trail Blazers"],
    "Danny Wolf": ["דני וולף", "ברוקלין", "Nets"],
    "Ben Saraf": ["בן שרף", "ברוקלין", "Nets"]
}

# שחקנים הרשומים בליגת הפיתוח (G-League)
GLEAGUE_DATABASE = {
    "Ben Saraf": ["בן שרף", "לונג איילנד", "Long Island Nets", "Blue Coats", "Squadron"]
}

# רשימת שחקני המכללות (NCAA Division I)
NCAA_DATABASE = {
    "Emanuel Sharp": ["עמנואל שארפ", "יוסטון", "Houston"],
    "Yoav Berman": ["יואב ברמן", "קווינס", "Queens"],
    "Ofri Naveh": ["עופרי נווה", "אורל רוברטס", "Oral Roberts"],
    "Eytan Burg": ["איתן בורג", "טנסי", "Tennessee"],
    "Omer Mayer": ["עומר מאייר", "פורדו", "Purdue"],
    "Noam Dovrat": ["נועם דוברת", "מיאמי", "Miami"],
    "Or Ashkenazi": ["אור אשכנזי", "ליפסקומב", "Lipscomb"],
    "Alon Michaeli": ["אלון מיכאלי", "קולורדו", "Colorado"],
    "Yonatan Levi": ["יונתן לוי", "פפרדיין", "Pepperdine"],
    "Yuval Levin": ["יובל לוין", "פרדו פורט וויין", "Purdue Fort Wayne"],
    "Omer Hamama": ["עומר חממה", "קנט סטייט", "Kent State"],
    "Or Paran": ["אור פארן", "מרסיהרסט", "Mercyhurst"],
    "Daniel Gueta": ["דניאל גואטה", "אוקלהומה סטייט", "Oklahoma State"]
}

# ==========================================
# --- פונקציות עזר ועיבוד נתונים ---
# ==========================================

def tr(text):
    """
    מתרגם טקסט מאנגלית לעברית ומתקן שמות קבוצות נפוצים
    כדי למנוע תרגומים מצחיקים כמו 'שבילים בלייזרים'.
    """
    try:
        t = translator.translate(text)
        t = t.replace("שבילים בלייזרים", "פורטלנד")
        t = t.replace("רשתות", "ברוקלין")
        t = t.replace("לוחמים", "ווריורס")
        t = t.replace("מלכים", "קינגס")
        return t
    except:
        return text

def get_detailed_injury(ev, player_name_en):
    """
    סורק את רשימת הפציעות (Injury Report) של משחק ספציפי ב-ESPN.
    מחזיר את הסטטוס (Active/Out) ואת סיבת ההיעדרות.
    """
    try:
        for comp in ev.get("competitions", []):
            for team in comp.get("competitors", []):
                for injury in team.get("injuries", []):
                    if player_name_en in injury.get("displayName", ""):
                        return {
                            "status": injury.get("status", "").upper(),
                            "reason": injury.get("reason", "")
                        }
    except:
        pass
    return {"status": "ACTIVE", "reason": ""}

def send_telegram(text):
    """
    שולח הודעה מעוצבת לטלגרם באמצעות ה-API של Bot API.
    """
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending Telegram message: {e}")

# ==========================================
# --- לוגיקת עדכונים בזמן אמת ---
# ==========================================

def check_final_updates():
    """
    סורק את כל המשחקים ומחפש שחקנים שסומנו בלו''ז כ-'סימן שאלה'.
    אם הסטטוס השתנה ל-'משחק' או 'בחוץ', שולח הודעה מיידית.
    """
    global status_cache
    
    # אם אין שחקנים במעקב (Questionable), חוסך קריאות ל-API
    if not any(v == "QUESTIONABLE" for v in status_cache.values()):
        return

    for url in [NBA_SCOREBOARD, NCAA_SCOREBOARD]:
        try:
            resp = requests.get(url, timeout=10).json()
            for ev in resp.get("events", []):
                # בודק רק משחקים שטרם התחילו
                if ev["status"]["type"]["state"] != "pre":
                    continue
                
                all_p = {**NBA_DATABASE, **GLEAGUE_DATABASE, **NCAA_DATABASE}
                teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
                
                for p_en, info in all_p.items():
                    key = f"{p_en}_{ev['id']}"
                    
                    # בדיקה רק אם השחקן נמצא בזיכרון תחת מעקב
                    if status_cache.get(key) == "QUESTIONABLE":
                        if any(info[2] in t_name for t_name in teams):
                            inj = get_detailed_injury(ev, p_en)
                            
                            # אם קיבל אישור כשירות
                            if inj["status"] == "ACTIVE" or "PROBABLE" in inj["status"]:
                                msg = f"{RTL_MARK}🇮🇱 **עדכון סופי: הוא משחק!** 🇮🇱\n\n"
                                msg += f"{RTL_MARK}🏀 *{info[0]}* כשיר ויופיע הלילה במדי {info[1]}! ✅"
                                send_telegram(msg)
                                status_cache[key] = "FINAL" # מסמן כסופי כדי לא לשלוח שוב
                                
                            # אם הוחלט שהוא בחוץ
                            elif "OUT" in inj["status"]:
                                r = f" ({inj['reason']})" if inj['reason'] else ""
                                msg = f"{RTL_MARK}🇮🇱 **עדכון סופי: לא ישחק** 🇮🇱\n\n"
                                msg += f"{RTL_MARK}🏀 *{info[0]}* בחוץ למשחק הלילה{r}. ❌"
                                send_telegram(msg)
                                status_cache[key] = "FINAL"
        except:
            pass

# ==========================================
# --- בניית הלו''ז היומי המאוחד ---
# ==========================================

def get_combined_schedule():
    """
    הפונקציה המרכזית: סורקת את כל הליגות, מטפלת בכפילויות של בן שרף,
    ובונה הודעה אחת ארוכה ומסודרת לערוץ.
    """
    all_games = {"NBA": [], "GLEAGUE": [], "NCAA": []}
    players_handled = set() # למניעת כפילויות שחקנים (כמו בן שרף)
    global status_cache
    status_cache = {} # איפוס הזיכרון בתחילת יום חדש

    # שלב א': סריקת ליגת הפיתוח (נותן עדיפות לבן שרף ב-G-League)
    try:
        resp_ncaa = requests.get(NCAA_SCOREBOARD, timeout=10).json()
        for ev in resp_ncaa.get("events", []):
            teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
            for p_en, info in GLEAGUE_DATABASE.items():
                # בדיקה אם אחת מקבוצות ה-G-League משחקת
                if any(k in t_name for k in info[2:] for t_name in teams):
                    vs = [t for t in teams if not any(k in t for k in info[2:])][0]
                    inj = get_detailed_injury(ev, p_en)
                    
                    status_note = ""
                    # אם זה בן שרף, נציין במפורש את הירידה לסגל
                    if p_en == "Ben Saraf":
                        status_note = " ⬇️ (ירד לסגל ליגת הפיתוח)"
                    
                    if "QUESTIONABLE" in inj["status"] or "GTD" in inj["status"]:
                        status_note = " ⚠️ (בסימן שאלה)"
                        status_cache[f"{p_en}_{ev['id']}"] = "QUESTIONABLE"
                    
                    time_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    time_il = time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    
                    all_games["GLEAGUE"].append((time_il, f"{RTL_MARK}🏀 *{info[0]}*{status_note} ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"))
                    players_handled.add(p_en)
    except:
        pass

    # שלב ב': סריקת NBA (מדלג על שחקנים שכבר טופלו ב-G-League)
    try:
        resp_nba = requests.get(NBA_SCOREBOARD, timeout=10).json()
        for ev in resp_nba.get("events", []):
            teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
            for p_en, info in NBA_DATABASE.items():
                if p_en in players_handled:
                    continue # אם בן שרף כבר נמצא ב-G-League, לא נציג אותו ב-NBA
                
                if any(info[2] in t_name for t_name in teams):
                    inj = get_detailed_injury(ev, p_en)
                    vs = [t for t in teams if info[2] not in t][0]
                    
                    status_note = ""
                    if "QUESTIONABLE" in inj["status"] or "GTD" in inj["status"]:
                        status_note = " ⚠️ (בסימן שאלה)"
                        status_cache[f"{p_en}_{ev['id']}"] = "QUESTIONABLE"
                    elif "OUT" in inj["status"]:
                        status_note = " ❌ (פצוע)"
                    
                    time_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    time_il = time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    
                    all_games["NBA"].append((time_il, f"{RTL_MARK}🏀 *{info[0]}*{status_note} ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"))
                    players_handled.add(p_en)
    except:
        pass

    # שלב ג': סריקת שאר שחקני המכללות
    try:
        # משתמשים באותה תגובה של NCAA מהשלב הראשון
        for ev in resp_ncaa.get("events", []):
            teams = [t["team"]["displayName"] for t in ev["competitions"][0]["competitors"]]
            for p_en, info in NCAA_DATABASE.items():
                if p_en in players_handled:
                    continue
                if any(info[2] in t_name for t_name in teams):
                    vs = [t for t in teams if info[2] not in t][0]
                    inj = get_detailed_injury(ev, p_en)
                    
                    status_note = " ⚠️ (בסימן שאלה)" if ("QUESTIONABLE" in inj["status"] or "GTD" in inj["status"]) else ""
                    if status_note:
                        status_cache[f"{p_en}_{ev['id']}"] = "QUESTIONABLE"
                        
                    time_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc)
                    time_il = time_utc.astimezone(pytz.timezone('Asia/Jerusalem'))
                    
                    all_games["NCAA"].append((time_il, f"{RTL_MARK}🏀 *{info[0]}*{status_note} ({info[1]})\n{RTL_MARK}🆚 נגד: *{tr(vs)}*\n{RTL_MARK}⏰ שעה: *{time_il.strftime('%H:%M')}*"))
    except:
        pass

    # שלב ד': חיבור כל חלקי ההודעה
    full_msg = ""
    if all_games["NBA"]:
        full_msg += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה ב-NBA** 🇮🇱\n\n" + "\n\n".join([g[1] for g in sorted(all_games["NBA"])]) + "\n\n"
    if all_games["GLEAGUE"]:
        full_msg += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה בליגת הפיתוח** 🇮🇱\n\n" + "\n\n".join([g[1] for g in sorted(all_games["GLEAGUE"])]) + "\n\n"
    if all_games["NCAA"]:
        full_msg += f"{RTL_MARK}🇮🇱 **משחקי לגיונרים הלילה במכללות** 🇮🇱\n\n" + "\n\n".join([g[1] for g in sorted(all_games["NCAA"])]) + "\n\n"
    
    # שליחה או הודעת "אין משחקים"
    if full_msg:
        send_telegram(full_msg)
    else:
        send_telegram(f"{RTL_MARK}🇮🇱 **אין משחקי לגיונרים הלילה** 😴")

# ==========================================
# --- הרצה ובקרה (Main Loop) ---
# ==========================================

if __name__ == "__main__":
    print("🚀 הבוט המאוחד והארוך פועל במתכונת מלאה...")
    last_day_sent = ""
    
    while True:
        try:
            # הגדרת הזמן הנוכחי בישראל
            now = datetime.now(pytz.timezone('Asia/Jerusalem'))
            today_str = now.strftime("%Y-%m-%d")
            
            # 1. שליחת לו''ז יומי (מוגדר ל-15:05 כרגע לניסוי קרוב)
            if now.hour == 14 and now.minute == 51 and last_day_sent != today_str:
                print(f"🕒 שולח לו''ז יומי: {now.strftime('%H:%M')}")
                get_combined_schedule()
                last_day_sent = today_str
            
            # 2. בדיקת עדכוני סימני שאלה בכל דקה (רק בשעות המשחקים בארה''ב)
            # השעות: 18:00 בערב עד 09:00 בבוקר
            if now.hour >= 18 or now.hour <= 9:
                check_final_updates()
                
            # הדפסה קטנה ללוג של Railway כדי לוודא שהבוט לא קרס
            if now.second == 0:
                print(f"🔎 סריקת סטטוסים דקה: {now.strftime('%H:%M')}")

        except Exception as main_err:
            print(f"⚠️ שגיאה קריטית בלולאה הראשית: {main_err}")
            
        # המתנה של 60 שניות כדי לרוץ בדיוק פעם בדקה
        time.sleep(60)

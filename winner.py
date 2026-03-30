import telebot
from telebot import types
import requests
import json
import os
import schedule
import time
import threading

# --- הגדרות ---
TOKEN = '8284141482:AAGG1vPtJrleAvl7kADMeufGbEydIq08ib0'
MY_CHAT_ID = '-1003820726077'
bot = telebot.TeleBot(TOKEN)
DB_FILE = 'nba_bet_db.json'

# --- מילון תרגום מלא לכל קבוצות ה-NBA ---
TEAM_NAMES_HE = {
    "Lakers": "לוס אנג'לס לייקרס", "Celtics": "בוסטון סלטיקס", 
    "Warriors": "גולדן סטייט ווריורס", "Nuggets": "דנבר נאגטס", 
    "Bulls": "שיקגו בולס", "Suns": "פיניקס סאנס",
    "Bucks": "מילווקי באקס", "76ers": "פילדלפיה 76", 
    "Clippers": "לאק קליפרס", "Heat": "מיאמי היט",
    "Knicks": "ניו יורק ניקס", "Mavericks": "דאלאס מאבריקס",
    "Nets": "ברוקלין נטס", "Grizzlies": "ממפיס גריזליס",
    "Hawks": "אטלנטה הוקס", "Cavaliers": "קליבלנד קאבלירס",
    "Pelicans": "ניו אורלינס פליקנס", "Spurs": "סן אנטוניו ספרס",
    "Kings": "סקרמנטו קינגס", "Thunder": "אוקלהומה סיטי ת'אנדר",
    "Raptors": "טורונטו ראפטורס", "Pacers": "אינדיאנה פייסרס",
    "Jazz": "יוטה ג'אז", "Timberwolves": "מינסוטה טימברוולבס",
    "Magic": "אורלנדו מג'יק", "Rockets": "יוסטון רוקטס",
    "Hornets": "שארלוט הורנטס", "Pistons": "דטרויט פיסטונס",
    "Wizards": "וושינגטון וויזארדס", "Trail Blazers": "פורטלנד טרייל בלייזרס"
}

def translate(name):
    return TEAM_NAMES_HE.get(name, name)

# --- ניהול מסד נתונים ---
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {"monthly_scores": {}, "daily_bets": {}, "processed_games": []}

def save_db(db):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=4, ensure_ascii=False)

def is_game_started(game_id):
    url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
    try:
        data = requests.get(url).json()
        for g in data['scoreboard']['games']:
            if g['gameId'] == game_id:
                return g['gameStatus'] != 1
    except: return False
    return False

# --- שליחת לוח הימורים (הודעות נפרדות) ---
def send_betting_board():
    db = load_db()
    db['daily_bets'] = {} # איפוס הימורים יומיים
    save_db(db)
    
    url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
    try:
        data = requests.get(url).json()
        games = data['scoreboard']['games']
        if not games: 
            return

        bot.send_message(MY_CHAT_ID, "🏀🏀 **הימורי הלילה ב-NBA** 🏀🏀\nההימורים נסגרים בשריקת הפתיחה:", parse_mode="Markdown")
        
        for g in games:
            gid = g['gameId']
            h_full = translate(g['homeTeam']['teamName'])
            a_full = translate(g['awayTeam']['teamName'])
            
            msg_text = f"🏀 **{a_full}** 🆚 **{h_full}** 🏀"
            
            markup = types.InlineKeyboardMarkup()
            btn_away = types.InlineKeyboardButton(f"🚀 {a_full.split()[-1]}", callback_data=f"b_{gid}_{g['awayTeam']['teamName']}")
            btn_home = types.InlineKeyboardButton(f"🏠 {h_full.split()[-1]}", callback_data=f"b_{gid}_{g['homeTeam']['teamName']}")
            
            # הוספת כפתורים: בית מימין, חוץ משמאל
            markup.add(btn_home, btn_away)
            bot.send_message(MY_CHAT_ID, msg_text, reply_markup=markup, parse_mode="Markdown")
            
        bot.send_message(MY_CHAT_ID, "🏆 **מי יהיה אלוף הלילה? שלחו את ההימורים שלכם עכשיו!**", parse_mode="Markdown")
    except Exception as e:
        print(f"Error fetching games: {e}")

# --- סיכום תוצאות (09:15) ---
def update_and_summary():
    db = load_db()
    medals = ["🥇", "🥈", "🥉"]
    try:
        data = requests.get("https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json").json()
        games = data['scoreboard']['games']
        found = False
        
        for g in games:
            gid = g['gameId']
            # בודק אם המשחק הסתיים (Status 3) וטרם עובד
            if g['gameStatus'] == 3 and gid in db['daily_bets'] and gid not in db['processed_games']:
                found = True
                win = g['homeTeam']['teamName'] if g['homeTeam']['score'] > g['awayTeam']['score'] else g['awayTeam']['teamName']
                
                for uid, info in db['daily_bets'][gid].items():
                    if info['choice'] == win:
                        # עדכון ניקוד ושמירת שם המשתמש העדכני
                        user_data = db['monthly_scores'].get(uid, {"name": info['name'], "score": 0})
                        user_data["score"] += 1
                        user_data["name"] = info['name']
                        db['monthly_scores'][uid] = user_data
                
                db['processed_games'].append(gid)
        
        if found:
            # מיון לפי ניקוד גבוה
            scores = sorted(db['monthly_scores'].items(), key=lambda x: x[1]['score'], reverse=True)
            table = "🏆 **3 המובילים בטורניר ה-NBA:**\n\n"
            for i, (uid, data) in enumerate(scores[:3]):
                table += f"{medals[i]} מקום {i+1}: {data['name']} - {data['score']} נק'\n"
            
            bot.send_message(MY_CHAT_ID, table, parse_mode="Markdown")
            save_db(db)
    except Exception as e:
        print(f"Error in summary: {e}")

# --- טיפול בלחיצות ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('b_'))
def handle_bet(call):
    _, gid, choice = call.data.split('_')
    user_id, user_name = str(call.from_user.id), call.from_user.first_name

    if is_game_started(gid):
        bot.answer_callback_query(call.id, "🚫 המשחק כבר התחיל!", show_alert=True)
        return

    db = load_db()
    if gid not in db['daily_bets']: db['daily_bets'][gid] = {}
    
    user_info = db['daily_bets'][gid].get(user_id, {"count": 0})
    current_count = user_info.get("count", 0)

    if current_count >= 2:
        bot.answer_callback_query(call.id, "❌ ניתן לשנות הימור פעם אחת בלבד!", show_alert=True)
        return

    db['daily_bets'][gid][user_id] = {"name": user_name, "choice": choice, "count": current_count + 1}
    save_db(db)
    
    msg = f"הימור על {translate(choice)} נקלט!" if current_count == 0 else f"ההימור שונה ל-{translate(choice)} (סופי) ⚠️"
    bot.answer_callback_query(call.id, msg)

# --- לולאת תזמון ---
def run_scheduler():
    schedule.every().day.at("18:15").do(send_betting_board)
    schedule.every().day.at("09:15").do(update_and_summary)
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    print("🚀 הבוט עלה לאוויר ומתחיל לעבוד!")
    
    # שליחה ראשונית מיד בהפעלה כדי שתוכל לראות שזה עובד
    send_betting_board() 
    
    # הפעלת התזמון (Scheduler) ב-Thread נפרד
    threading.Thread(target=run_scheduler, daemon=True).start()
    
    # לולאת הפעולה הראשית של הבוט
    try:
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except Exception as e:
        print(f"Bot Polling Error: {e}")
        time.sleep(5)

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

# --- פונקציה לבדיקת סטטוס משחק (לנעילה) ---
def is_game_started(game_id):
    url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
    try:
        data = requests.get(url).json()
        for g in data['scoreboard']['games']:
            if g['gameId'] == game_id:
                return g['gameStatus'] != 1 # 1 זה "עוד לא התחיל"
    except: return False
    return False

# --- שליחת לוח הימורים מעוצב (18:15) ---
def send_betting_board():
    db = load_db()
    db['daily_bets'] = {} 
    save_db(db)
    
    url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
    try:
        data = requests.get(url).json()
        games = data['scoreboard']['games']
        if not games: return

        bot.send_message(MY_CHAT_ID, "🏀🏀 **הימורי הלילה ב-NBA** 🏀🏀\n\nבחרו את המנצחת בכל משחק (ההימורים נסגרים בשריקת הפתיחה):", parse_mode="Markdown")
        
        for g in games:
            gid = g['gameId']
            h_full = translate(g['homeTeam']['teamName'])
            a_full = translate(g['awayTeam']['teamName'])
            
            msg_text = f"--- \n🏀 **{a_full}** 🆚 **{h_full}** 🏀"
            
            markup = types.InlineKeyboardMarkup()
            # כפתורים עם המילה האחרונה של הקבוצה (למשל "לייקרס")
            btn_away = types.InlineKeyboardButton(f"🚀 {a_full.split()[-1]}", callback_data=f"b_{gid}_{g['awayTeam']['teamName']}")
            btn_home = types.InlineKeyboardButton(f"🏠 {h_full.split()[-1]}", callback_data=f"b_{gid}_{g['homeTeam']['teamName']}")
            markup.add(btn_away, btn_home)
            
            bot.send_message(MY_CHAT_ID, msg_text, reply_markup=markup, parse_mode="Markdown")
    except: print("Error fetching games")

# --- סיכום תוצאות ועדכון נקודות (09:15) ---
def update_and_summary():
    db = load_db()
    try:
        data = requests.get("https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json").json()
        games = data['scoreboard']['games']
        summary = "🎯 **תוצאות ההימורים מהלילה:**\n\n"
        found = False
        
        for g in games:
            gid = g['gameId']
            if g['gameStatus'] == 3 and gid in db['daily_bets'] and gid not in db['processed_games']:
                found = True
                win = g['homeTeam']['teamName'] if g['homeTeam']['score'] > g['awayTeam']['score'] else g['awayTeam']['teamName']
                
                for uid, info in db['daily_bets'][gid].items():
                    if info['choice'] == win:
                        db['monthly_scores'][uid] = db['monthly_scores'].get(uid, 0) + 1
                        summary += f"✅ *{info['name']}* פגע בניצחון של {translate(win)}!\n"
                db['processed_games'].append(gid)
        
        if found:
            scores = sorted(db['monthly_scores'].items(), key=lambda x: x[1], reverse=True)
            table = "\n🏆 **טבלת מובילי החודש:**\n"
            for i, (uid, score) in enumerate(scores[:5]):
                table += f"{i+1}. משתמש {uid}: {score} נק'\n"
            
            bot.send_message(MY_CHAT_ID, summary + table, parse_mode="Markdown")
            save_db(db)
    except: print("Error in summary")

# --- האזנה ללחיצות על כפתורים ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('b_'))
def handle_bet(call):
    _, gid, choice = call.data.split('_')
    
    if is_game_started(gid):
        bot.answer_callback_query(call.id, "🚫 המשחק כבר התחיל! ההימור חסום.", show_alert=True)
        return

    db = load_db()
    if gid not in db['daily_bets']: db['daily_bets'][gid] = {}
    
    db['daily_bets'][gid][str(call.from_user.id)] = {"name": call.from_user.first_name, "choice": choice}
    save_db(db)
    bot.answer_callback_query(call.id, f"ההימור על {translate(choice)} נקלט! 🎯")

# --- לולאת תזמון ---
def run_scheduler():
    schedule.every().day.at("18:15").do(send_betting_board)
    schedule.every().day.at("09:15").do(update_and_summary)
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    print("🚀 בוט ההימורים התניע!")
    send_betting_board() # הרצה ראשונית מיד
    threading.Thread(target=run_scheduler, daemon=True).start()
    bot.infinity_polling()

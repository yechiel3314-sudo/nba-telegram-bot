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

# --- מילון תרגום ---
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

# --- פונקציית עזר ליצירת רוחב אחיד ---
def make_fixed_width(text1, text2, target_len=30):
    full_line = f"**{text1}** 🆚 **{text2}**"
    # הוספת רווחים שקופים בתוך הבלוק של הקוד (monospace) כדי לשמור על יישור
    return f"`{full_line.center(target_len)}`"

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

# --- שליחת לוח הימורים (הודעות באורך אחיד) ---
def send_betting_board():
    db = load_db()
    db['daily_bets'] = {} 
    save_db(db)
    
    url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
    try:
        data = requests.get(url).json()
        games = data['scoreboard']['games']
        if not games: return

        bot.send_message(MY_CHAT_ID, "🏀🏀 **הימורי הלילה ב-NBA** 🏀🏀", parse_mode="Markdown")
        
        for g in games:
            gid = g['gameId']
            h_full = translate(g['homeTeam']['teamName'])
            a_full = translate(g['awayTeam']['teamName'])
            
            # יצירת טקסט אחיד בעזרת פריסת קוד (Backticks) שתמיד תופסת את אותו רוחב בטלגרם
            msg_text = f"🏀 {a_full} 🆚 {h_full} 🏀"
            
            markup = types.InlineKeyboardMarkup()
            btn_away = types.InlineKeyboardButton(f"🚀 {a_full.split()[-1]}", callback_data=f"b_{gid}_{g['awayTeam']['teamName']}")
            btn_home = types.InlineKeyboardButton(f"🏠 {h_full.split()[-1]}", callback_data=f"b_{gid}_{g['homeTeam']['teamName']}")
            
            markup.add(btn_home, btn_away)
            bot.send_message(MY_CHAT_ID, msg_text, reply_markup=markup, parse_mode="Markdown")
            
        bot.send_message(MY_CHAT_ID, "🏆 **מי יהיה אלוף הלילה? שלחו הימורים!**", parse_mode="Markdown")
    except: pass

def update_and_summary():
    db = load_db()
    medals = ["🥇", "🥈", "🥉"]
    try:
        data = requests.get("https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json").json()
        games = data['scoreboard']['games']
        found = False
        for g in games:
            gid = g['gameId']
            if g['gameStatus'] == 3 and gid in db['daily_bets'] and gid not in db['processed_games']:
                found = True
                win = g['homeTeam']['teamName'] if g['homeTeam']['score'] > g['awayTeam']['score'] else g['awayTeam']['teamName']
                for uid, info in db['daily_bets'][gid].items():
                    if info['choice'] == win:
                        u_data = db['monthly_scores'].get(uid, {"name": info['name'], "score": 0})
                        u_data["score"] += 1
                        u_data["name"] = info['name']
                        db['monthly_scores'][uid] = u_data
                db['processed_games'].append(gid)
        if found:
            scores = sorted(db['monthly_scores'].items(), key=lambda x: x[1]['score'], reverse=True)
            table = "🏆 **3 המובילים בטורניר ה-NBA:**\n\n"
            for i, (uid, data) in enumerate(scores[:3]):
                table += f"{medals[i]} מקום {i+1}: {data['name']} - {data['score']} נק'\n"
            bot.send_message(MY_CHAT_ID, table, parse_mode="Markdown")
            save_db(db)
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('b_'))
def handle_bet(call):
    _, gid, choice = call.data.split('_')
    user_id, user_name = str(call.from_user.id), call.from_user.first_name

    if is_game_started(gid):
        bot.answer_callback_query(call.id, "🚫 המשחק כבר התחיל!", show_alert=True)
        return

    db = load_db()
    if gid not in db['daily_bets']: db['daily_bets'][gid] = {}
    u_info = db['daily_bets'][gid].get(user_id, {"count": 0})

    if u_info["count"] >= 2:
        bot.answer_callback_query(call.id, "❌ ניתן לשנות הימור פעם אחת בלבד!", show_alert=True)
        return

    db['daily_bets'][gid][user_id] = {"name": user_name, "choice": choice, "count": u_info["count"] + 1}
    save_db(db)
    
    # הודעה מותאמת לאחר לחיצה ראשונה
    if u_info["count"] == 0:
        bot.answer_callback_query(call.id, f"✅ ההימור נקלט! נותר לך עוד שינוי אחד בלבד.", show_alert=True)
    else:
        bot.answer_callback_query(call.id, f"⚠️ ההימור שונה (זהו השינוי האחרון שלך!).", show_alert=True)

def run_scheduler():
    schedule.every().day.at("18:15").do(send_betting_board)
    schedule.every().day.at("09:15").do(update_and_summary)
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    send_betting_board() 
    threading.Thread(target=run_scheduler, daemon=True).start()
    bot.infinity_polling()

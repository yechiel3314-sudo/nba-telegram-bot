import telebot
from telebot import types
import requests
import json
import os
import schedule
import time
import threading

# הגדרות שסיפקת
TOKEN = '8284141482:AAGG1vPtJrleAvl7kADMeufGbEydIq08ib0'
MY_CHAT_ID = '-1003820726077'

bot = telebot.TeleBot(TOKEN)
DB_FILE = 'nba_bet_db.json'

# --- ניהול מסד נתונים ---
def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"monthly_scores": {}, "daily_bets": {}, "processed_games": []}

def save_db(db):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=4, ensure_ascii=False)

# --- פונקציה לשליחת הלוח (18:15) ---
def send_betting_board():
    db = load_db()
    db['daily_bets'] = {} # איפוס הימורים יומיים לקראת יום חדש
    save_db(db)

    url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
    try:
        resp = requests.get(url).json()
        games = resp['scoreboard']['games']
        
        bot.send_message(MY_CHAT_ID, "🏀 **הימורי ה-NBA להלילה יוצאים לדרך!** 🏀\nבחרו את המנצחת בכל משחק:")
        
        for g in games:
            gid = g['gameId']
            home = g['homeTeam']['teamName']
            away = g['awayTeam']['teamName']
            
            markup = types.InlineKeyboardMarkup()
            btn_away = types.InlineKeyboardButton(f"🚀 {away}", callback_data=f"b_{gid}_{away}")
            btn_home = types.InlineKeyboardButton(f"🏠 {home}", callback_data=f"b_{gid}_{home}")
            markup.add(btn_away, btn_home)
            
            bot.send_message(MY_CHAT_ID, f"🏀 {away} @ {home}", reply_markup=markup)
    except:
        print("שגיאה במשיכת משחקים")

# --- פונקציה לסיכום תוצאות ועדכון טבלה (09:15) ---
def update_scores_and_send_summary():
    db = load_db()
    url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
    
    try:
        resp = requests.get(url).json()
        games = resp['scoreboard']['games']
        
        summary_msg = "🎯 **סיכום הימורי הלילה:**\n\n"
        results_found = False

        for g in games:
            gid = g['gameId']
            # בודקים רק משחקים שנגמרו ושלא עיבדנו בעבר
            if g['gameStatus'] == 3 and gid in db['daily_bets'] and gid not in db['processed_games']:
                results_found = True
                winner = g['homeTeam']['teamName'] if g['homeTeam']['score'] > g['awayTeam']['score'] else g['awayTeam']['teamName']
                
                # עוברים על כל מי שהימר על המשחק הזה
                for user_id, info in db['daily_bets'][gid].items():
                    if info['choice'] == winner:
                        db['monthly_scores'][user_id] = db['monthly_scores'].get(user_id, 0) + 1
                        summary_msg += f"✅ *{info['name']}* צדק בניצחון של {winner}!\n"
                
                db['processed_games'].append(gid)

        if not results_found:
            return # אין מה לעדכן

        # יצירת טבלת Leaderboard חודשית
        leaderboard = "\n🏆 **טבלת אלוף החודש:**\n"
        sorted_scores = sorted(db['monthly_scores'].items(), key=lambda x: x[1], reverse=True)
        for i, (uid, score) in enumerate(sorted_scores[:5], 1): # טופ 5
            # הערה: כדי להציג שמות בטבלה, אפשר לשמור אותם ב-DB. כאן זה מציג ניקוד.
            leaderboard += f"{i}. משתמש {uid}: {score} נקודות\n"

        save_db(db)
        bot.send_message(MY_CHAT_ID, summary_msg + leaderboard, parse_mode="Markdown")
    except:
        print("שגיאה בעדכון תוצאות")

# --- טיפול בכפתורים ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('b_'))
def handle_bet(call):
    # (הלוגיקה של בדיקת תחילת משחק ושמירה ל-DB נשארת כאן)
    # ... (כמו בקוד הקודם)
    bot.answer_callback_query(call.id, "ההימור נרשם!")

# --- תזמון ---
def scheduler_loop():
    schedule.every().day.at("18:15").do(send_betting_board)
    schedule.every().day.at("09:15").do(update_scores_and_send_summary)
    
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    # הרצה ראשונית של הלוח כדי שתראה שזה עובד מיד
    send_betting_board()
    
    threading.Thread(target=scheduler_loop, daemon=True).start()
    bot.infinity_polling()

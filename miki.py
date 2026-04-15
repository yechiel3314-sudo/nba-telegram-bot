import logging
import sqlite3
import pandas as pd
import io
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

logging.basicConfig(level=logging.INFO)
TOKEN = "8489457682:AAGrl1eCDqntP6hH1Sa1y7Qtgn2lXYLEDaM"

(
    SELECT_PROJECT,
    SET_PROJECT_NAME,
    SET_FIELDS,
    INPUT_DATA,
    SELECT_TARGET,
    SELECT_GROUPBY,
    SELECT_ACTION,
    SELECT_LIMIT
) = range(8)

# ---------- DB ----------
def init_db():
    conn = sqlite3.connect('stats_pro.db')
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS projects
                 (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, fields TEXT, types TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS entries
                 (id INTEGER PRIMARY KEY, project_id INTEGER, data TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')

    conn.commit()
    conn.close()

# ---------- START ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_db()

    kb = [
        [InlineKeyboardButton("🆕 פרויקט", callback_data="new")],
        [InlineKeyboardButton("📥 הזנת נתונים", callback_data="add")],
        [InlineKeyboardButton("📊 ניתוח", callback_data="stats")],
        [InlineKeyboardButton("📂 ייצוא אקסל", callback_data="excel")],
        [InlineKeyboardButton("↩️ Undo", callback_data="undo")]
    ]

    await update.message.reply_text("🔥 StatsBot Pro", reply_markup=InlineKeyboardMarkup(kb))

# ---------- PROJECT ----------
async def select_project(update, context):
    await update.callback_query.answer()

    user_id = update.callback_query.from_user.id
    conn = sqlite3.connect('stats_pro.db')
    c = conn.cursor()

    c.execute("SELECT id, name FROM projects WHERE user_id=?", (user_id,))
    data = c.fetchall()
    conn.close()

    if not data:
        await update.callback_query.edit_message_text("❌ אין פרויקטים")
        return ConversationHandler.END

    kb = [[InlineKeyboardButton(name, callback_data=f"p_{pid}")] for pid, name in data]
    await update.callback_query.edit_message_text("בחר פרויקט:", reply_markup=InlineKeyboardMarkup(kb))
    return SELECT_PROJECT

async def project_selected(update, context):
    await update.callback_query.answer()
    p_id = int(update.callback_query.data.split("_")[1])
    context.user_data['p_id'] = p_id

    conn = sqlite3.connect('stats_pro.db')
    c = conn.cursor()
    c.execute("SELECT fields, types FROM projects WHERE id=?", (p_id,))
    row = c.fetchone()
    conn.close()

    context.user_data['fields'] = row[0].split(',')
    context.user_data['types'] = row[1].split(',')
    context.user_data['idx'] = 0
    context.user_data['payload'] = {}

    await update.callback_query.edit_message_text(f"📥 הזן: {context.user_data['fields'][0]}")
    return INPUT_DATA

# ---------- CREATE ----------
async def new_project(update, context):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("שם פרויקט?")
    return SET_PROJECT_NAME

async def save_name(update, context):
    context.user_data['name'] = update.message.text
    await update.message.reply_text("שדות בפורמט:\nשם:text, גיל:number")
    return SET_FIELDS

async def save_fields(update, context):
    user_id = update.message.from_user.id
    name = context.user_data['name']

    raw = update.message.text.split(',')
    fields = []
    types = []

    for r in raw:
        f, t = r.split(':')
        fields.append(f.strip())
        types.append(t.strip())

    conn = sqlite3.connect('stats_pro.db')
    c = conn.cursor()
    c.execute("INSERT INTO projects (user_id, name, fields, types) VALUES (?, ?, ?, ?)",
              (user_id, name, ",".join(fields), ",".join(types)))
    conn.commit()
    conn.close()

    await update.message.reply_text("✅ פרויקט נוצר!")
    return ConversationHandler.END

# ---------- INPUT ----------
async def input_start(update, context):
    return await select_project(update, context)

async def input_data(update, context):
    fields = context.user_data['fields']
    types = context.user_data['types']
    idx = context.user_data['idx']

    val = update.message.text

    # validation
    if types[idx] == "number":
        try:
            float(val)
        except:
            await update.message.reply_text("❌ חייב מספר")
            return INPUT_DATA

    context.user_data['payload'][fields[idx]] = val
    context.user_data['idx'] += 1

    if context.user_data['idx'] < len(fields):
        await update.message.reply_text(f"📥 הזן: {fields[context.user_data['idx']]}")
        return INPUT_DATA

    conn = sqlite3.connect('stats_pro.db')
    c = conn.cursor()
    c.execute("INSERT INTO entries (project_id, data) VALUES (?, ?)",
              (context.user_data['p_id'], json.dumps(context.user_data['payload'])))
    conn.commit()
    conn.close()

    await update.message.reply_text("✅ נשמר!")
    return ConversationHandler.END

# ---------- STATS ----------
async def stats_start(update, context):
    return await select_project(update, context)

async def choose_target(update, context):
    await update.callback_query.answer()

    kb = [[InlineKeyboardButton(f, callback_data=f"t_{f}")] for f in context.user_data['fields']]
    await update.callback_query.edit_message_text("בחר שדה:", reply_markup=InlineKeyboardMarkup(kb))
    return SELECT_TARGET

async def target_selected(update, context):
    context.user_data['target'] = update.callback_query.data.replace("t_", "")

    kb = [[InlineKeyboardButton(f, callback_data=f"g_{f}")] for f in context.user_data['fields']]
    kb.append([InlineKeyboardButton("הכל", callback_data="g_all")])

    await update.callback_query.edit_message_text("Group by:", reply_markup=InlineKeyboardMarkup(kb))
    return SELECT_GROUPBY

async def group_selected(update, context):
    context.user_data['group'] = update.callback_query.data.replace("g_", "")

    kb = [
        [InlineKeyboardButton("ממוצע", callback_data="avg")],
        [InlineKeyboardButton("סכום", callback_data="sum")],
        [InlineKeyboardButton("מקסימום", callback_data="max")],
        [InlineKeyboardButton("מינימום", callback_data="min")],
        [InlineKeyboardButton("ספירה", callback_data="count")],
        [InlineKeyboardButton("דירוג", callback_data="rank")]
    ]

    await update.callback_query.edit_message_text("בחר פעולה:", reply_markup=InlineKeyboardMarkup(kb))
    return SELECT_ACTION

async def calc(update, context):
    await update.callback_query.answer()

    p_id = context.user_data['p_id']
    target = context.user_data['target']
    group = context.user_data['group']
    action = update.callback_query.data

    conn = sqlite3.connect('stats_pro.db')
    df_raw = pd.read_sql_query("SELECT data FROM entries WHERE project_id=?", conn, params=(p_id,))
    conn.close()

    if df_raw.empty:
        await update.callback_query.edit_message_text("❌ אין נתונים")
        return ConversationHandler.END

    df = pd.DataFrame([json.loads(x) for x in df_raw['data']])
    df[target] = pd.to_numeric(df[target], errors='coerce')

    if group == "all":
        series = df[target]
    else:
        series = df.groupby(group)[target]

    if action == "avg":
        res = series.mean()
    elif action == "sum":
        res = series.sum()
    elif action == "max":
        res = series.max()
    elif action == "min":
        res = series.min()
    elif action == "count":
        res = series.count()
    elif action == "rank":
        res = series.mean().sort_values(ascending=False)

    await update.callback_query.edit_message_text(f"📊\n{res}")
    return ConversationHandler.END

# ---------- UNDO ----------
async def undo(update, context):
    await update.callback_query.answer()

    user_id = update.callback_query.from_user.id
    conn = sqlite3.connect('stats_pro.db')
    c = conn.cursor()

    c.execute("""
        DELETE FROM entries WHERE id = (
            SELECT e.id FROM entries e
            JOIN projects p ON e.project_id = p.id
            WHERE p.user_id=?
            ORDER BY e.id DESC LIMIT 1
        )
    """, (user_id,))

    conn.commit()
    conn.close()

    await update.callback_query.edit_message_text("↩️ בוטל")

# ---------- EXCEL ----------
async def excel(update, context):
    await update.callback_query.answer()

    user_id = update.callback_query.from_user.id
    conn = sqlite3.connect('stats_pro.db')
    c = conn.cursor()

    c.execute("SELECT id FROM projects WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
    row = c.fetchone()

    if not row:
        await update.callback_query.edit_message_text("❌ אין פרויקט")
        return

    p_id = row[0]

    df_raw = pd.read_sql_query("SELECT data FROM entries WHERE project_id=?", conn, params=(p_id,))
    conn.close()

    df = pd.DataFrame([json.loads(x) for x in df_raw['data']])

    out = io.BytesIO()
    df.to_excel(out, index=False)
    out.seek(0)

    await update.callback_query.message.reply_document(out, filename="stats.xlsx")

# ---------- MAIN ----------
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(new_project, pattern="new")],
        states={
            SET_PROJECT_NAME: [MessageHandler(filters.TEXT, save_name)],
            SET_FIELDS: [MessageHandler(filters.TEXT, save_fields)]
        },
        fallbacks=[CommandHandler("cancel", start)]
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(input_start, pattern="add")],
        states={
            SELECT_PROJECT: [CallbackQueryHandler(project_selected, pattern="^p_")],
            INPUT_DATA: [MessageHandler(filters.TEXT, input_data)]
        },
        fallbacks=[CommandHandler("cancel", start)]
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(stats_start, pattern="stats")],
        states={
            SELECT_PROJECT: [CallbackQueryHandler(project_selected, pattern="^p_")],
            SELECT_TARGET: [CallbackQueryHandler(target_selected, pattern="^t_")],
            SELECT_GROUPBY: [CallbackQueryHandler(group_selected, pattern="^g_")],
            SELECT_ACTION: [CallbackQueryHandler(calc)]
        },
        fallbacks=[CommandHandler("cancel", start)]
    ))

    app.add_handler(CallbackQueryHandler(undo, pattern="undo"))
    app.add_handler(CallbackQueryHandler(excel, pattern="excel"))

    app.run_polling()

if __name__ == "__main__":
    main()

import httpx
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ========================
# 🔐 הנתונים המלאים שלך מוזנים כאן
# ========================
TOKEN = '8284141482:AAGG1vPtJrleAvl7kADMeufGbEydIq08ib0'
MY_CHAT_ID = '-1003820726077'
SERVICE_ID = '7068194e-3cbd-48e3-8ed1-641be1fe7659'
ENVIRONMENT_ID = '089dc261-4c0c-42b3-a590-e8484bf2ac7e'
RAILWAY_API_KEY = 'f8912170-f9b4-4445-a0e8-66f05cf4a2ee'

# ========================
# לוגים - יופיעו ב-Railway Logs
# ========================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ========================
# שליחת פקודה ל־Railway
# ========================
async def send_railway_command(mutation_name, action_name):
    url = "https://backboard.railway.app/graphql"

    headers = {
        "Authorization": f"Bearer {RAILWAY_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    query = {
        "query": f"""
        mutation {{
          {mutation_name}(serviceId: "{SERVICE_ID}", environmentId: "{ENVIRONMENT_ID}")
        }}
        """
    }

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            logger.info(f"--- ניסיון {action_name} בשרת ---")

            response = await client.post(url, json=query, headers=headers)

            logger.info(f"STATUS: {response.status_code}")
            logger.info(f"RESPONSE FROM RAILWAY: {response.text}")

            if response.status_code == 200:
                return True, response.text
            else:
                return False, response.text

        except Exception as e:
            logger.error(f"שגיאת תקשורת: {e}")
            return False, str(e)

# ========================
# כפתורים
# ========================
def get_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛑 כיבוי מוחלט (Stop)", callback_data="stop")],
        [InlineKeyboardButton(text="▶️ הפעלה מחדש (Redeploy)", callback_data="start")]
    ])

# ========================
# פקודת control
# ========================
@dp.message(Command("control"))
async def control_panel(message: types.Message):
    if str(message.chat.id) == MY_CHAT_ID:
        await message.answer("🕹️ **לוח בקרה לשרת שלך:**", reply_markup=get_keyboard())

# ========================
# לחיצה על כפתור
# ========================
@dp.callback_query()
async def handle_buttons(callback: types.CallbackQuery):
    if str(callback.message.chat.id) != MY_CHAT_ID:
        await callback.answer("אין לך הרשאה!")
        return

    if callback.data == "stop":
        success, res = await send_railway_command("serviceInstanceStop", "כיבוי")
        msg = "✅ **כיבוי הצליח!** כל הבוטים נעצרו." if success else f"❌ כיבוי נכשל:\n{res}"

    elif callback.data == "start":
        success, res = await send_railway_command("serviceInstanceRedeploy", "הפעלה")
        msg = "🚀 **הפעלה הצליחה!** הבוטים עולים מחדש." if success else f"❌ הפעלה נכשלה:\n{res}"

    await callback.message.answer(msg)
    await callback.answer()

# ========================
# MAIN
# ========================
async def main():
    logger.info("🚀 בוט השלט עלה לאוויר ב-Railway")

    try:
        await bot.send_message(
            MY_CHAT_ID,
            "⚡ **שלט ה-Railway שלך מוכן!**\nהשתמש בכפתורים למטה כדי לשלוט בשרת:",
            reply_markup=get_keyboard()
        )
    except Exception as e:
        logger.error(f"שגיאה בשליחת הודעה ראשונית: {e}")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

import httpx
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- נתונים סופיים מהשרת שלך ---
TOKEN = '8284141482:AAGG1vPtJrleAvl7kADMeufGbEydIq08ib0'
MY_CHAT_ID = '-1003820726077'
SERVICE_ID = '7068194e-3cbd-48e3-8ed1-641be1fe7659'
ENVIRONMENT_ID = '089dc261-4c0c-42b3-a590-e8484bf2ac7e'
RAILWAY_API_KEY = 'f8912170-f9b4-4445-a0e8-66f05cf4a2ee'

# הגדרת לוגים - כדי שתראה ב-Railway Logs את הפעולות
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher()

async def send_railway_command(mutation_name, action_name):
    url = "https://backboard.railway.app/graphql"
    headers = {
        "Authorization": f"Bearer {RAILWAY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    query = f"""
    mutation {{
      {mutation_name}(serviceId: "{SERVICE_ID}", environmentId: "{ENVIRONMENT_ID}")
    }}
    """
    
    async with httpx.AsyncClient() as client:
        try:
            logger.info(f"--- תחילת פעולה: {action_name} ---")
            response = await client.post(url, json={"query": query}, headers=headers)
            if response.status_code == 200:
                logger.info(f"סיום בהצלחה: השרת קיבל פקודת {action_name}")
                return True
            else:
                logger.error(f"שגיאה מהשרת: {response.text}")
                return False
        except Exception as e:
            logger.error(f"שגיאת תקשורת: {e}")
            return False

def get_keyboard():
    buttons = [
        [InlineKeyboardButton(text="🛑 כיבוי מוחלט (Stop)", callback_data="stop")],
        [InlineKeyboardButton(text="▶️ הפעלה מחדש (Redeploy)", callback_data="start")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(Command("control"))
async def send_control_panel(message: types.Message):
    if str(message.chat.id) == MY_CHAT_ID:
        await message.answer("🕹️ **לוח בקרה לניהול השרת**", reply_markup=get_keyboard())

@dp.callback_query()
async def handle_callback(callback: types.CallbackQuery):
    if callback.data == "stop":
        success = await send_railway_command("serviceInstanceStop", "כיבוי")
        msg = "✅ **הכל נעצר!** הבוטים כבויים כעת." if success else "❌ שגיאה בכיבוי"
    else:
        success = await send_railway_command("serviceInstanceRedeploy", "הפעלה")
        msg = "🚀 **המערכת חוזרת!** הבוטים עולים מחדש." if success else "❌ שגיאה בהפעלה"
    
    await callback.message.answer(msg)
    await callback.answer()

async def main():
    logger.info("השלט הרחוק עלה לאוויר!")
    # שליחת הודעה עם כפתורים מיד עם ההפעלה
    try:
        await bot.send_message(MY_CHAT_ID, "⚡ **השלט הרחוק מחובר!**\nהשתמש בכפתורים לשליטה בבוטים:", reply_markup=get_keyboard())
    except Exception as e:
        logger.error(f"שגיאה בשליחת הודעה ראשונית: {e}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

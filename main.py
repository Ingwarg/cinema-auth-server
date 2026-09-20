import asyncio
import os
import random
import time
from fastapi import FastAPI, HTTPException
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
import uvicorn

BOT_TOKEN = os.getenv("BOT_TOKEN", "8812606946:AAGXmy58wS8KeRYTU8cSpTC4rJQOnsm1Ntc")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

auth_sessions = {}

def cleanup_expired():
    now = time.time()
    expired = [c for c, data in auth_sessions.items() if now - data["created_at"] > 300]
    for c in expired:
        del auth_sessions[c]

@app.get("/")
async def root():
    return {"status": "ok", "service": "Cinema Auth"}

@app.post("/api/auth/code")
async def generate_code():
    cleanup_expired()
    code = str(random.randint(100000, 999999))
    auth_sessions[code] = {
        "status": "pending",
        "created_at": time.time(),
        "user": None
    }
    return {"code": code, "expires_in": 300}

@app.get("/api/auth/status")
async def check_status(code: str):
    session = auth_sessions.get(code)
    if not session:
        raise HTTPException(status_code=404, detail="Код не найден или истек")
    
    if session["status"] == "confirmed":
        user_data = session["user"]
        del auth_sessions[code]
        return {"status": "confirmed", "user": user_data}
        
    return {"status": "pending"}

# 1. Если перешли по QR-коду (автоматический start с кодом)
@dp.message(CommandStart(deep_link=True))
async def handle_start_deep_link(message: types.Message, command: CommandObject):
    code = command.args.strip() if command.args else None
    
    if not code or code not in auth_sessions:
        await message.answer(
            "❌ <b>Код недействителен или срок его действия истек.</b>\n\n"
            "Пожалуйста, откройте окно входа на телевизоре заново и отсканируйте новый QR-код.",
            parse_mode="HTML"
        )
        return
        
    # Получаем аватарку пользователя
    photos = await bot.get_user_profile_photos(message.from_user.id, limit=1)
    avatar_url = None
    if photos.total_count > 0:
        file_id = photos.photos[0][-1].file_id
        file = await bot.get_file(file_id)
        avatar_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
        
    auth_sessions[code]["status"] = "confirmed"
    auth_sessions[code]["user"] = {
        "id": message.from_user.id,
        "name": message.from_user.full_name or message.from_user.first_name,
        "username": message.from_user.username,
        "avatar_url": avatar_url
    }
    
    await message.answer(
        f"✅ <b>Вход успешно выполнен!</b>\n\n"
        f"Телевизор авторизован под профилем <b>{message.from_user.first_name}</b>.\n"
        f"Приятного просмотра фильмов в Bcinema! 🍿",
        parse_mode="HTML"
    )

# 2. Если просто нажали /start без QR-кода
@dp.message(CommandStart())
async def handle_regular_start(message: types.Message):
    await message.answer(
        "👋 <b>Добро пожаловать в Bcinema Auth!</b>\n\n"
        "📺 Чтобы войти в приложение на телевизоре:\n"
        "1. Откройте приложение <b>Bcinema</b> на ТВ.\n"
        "2. Перейдите в раздел <b>«Профиль»</b>.\n"
        "3. На экране появится <b>6-значный код</b>.\n\n"
        "👇 <b>Просто отправьте этот код сюда ответным сообщением:</b>",
        parse_mode="HTML"
    )

# 3. Обработка ввода цифр вручную
@dp.message(F.text)
async def handle_manual_code(message: types.Message):
    # Очищаем от пробелов (если пользователь ввел '482 109')
    code = message.text.strip().replace(" ", "").replace("-", "")
    
    # Если это 6 цифр и код есть в базе
    if code in auth_sessions:
        photos = await bot.get_user_profile_photos(message.from_user.id, limit=1)
        avatar_url = None
        if photos.total_count > 0:
            file_id = photos.photos[0][-1].file_id
            file = await bot.get_file(file_id)
            avatar_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

        auth_sessions[code]["status"] = "confirmed"
        auth_sessions[code]["user"] = {
            "id": message.from_user.id,
            "name": message.from_user.full_name or message.from_user.first_name,
            "username": message.from_user.username,
            "avatar_url": avatar_url
        }
        await message.answer(
            f"✅ <b>Код принят! Вход выполнен!</b>\n\n"
            f"Экран на телевизоре обновится автоматически.",
            parse_mode="HTML"
        )
    elif len(code) == 6 and code.isdigit():
        await message.answer(
            "❌ Код не найден или уже устарел.\n"
            "Убедитесь, что окно авторизации открыто на экране ТВ прямо сейчас, и повторите ввод."
        )
    else:
        await message.answer(
            "ℹ️ Отправьте <b>6-значный код</b> с экрана телевизора (например: <code>123456</code>) для входа в Bcinema.",
            parse_mode="HTML"
        )

async def start_services():
    port = int(os.getenv("PORT", 8080))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await asyncio.gather(
        server.serve(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    asyncio.run(start_services())

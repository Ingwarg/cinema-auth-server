import asyncio
import os
import random
import time
from fastapi import FastAPI, HTTPException
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, CommandObject
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

@dp.message(CommandStart(deep_link=True))
async def handle_start_deep_link(message: types.Message, command: CommandObject):
    code = command.args.strip() if command.args else None

    if not code or code not in auth_sessions:
        await message.answer("❌ Код не найден или истек срок. Откройте окно входа на ТВ заново.")
        return

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
    await message.answer(f"✅ Вход на ТВ успешно выполнен!\nПриятного просмотра, {message.from_user.first_name}!")

@dp.message()
async def handle_text_code(message: types.Message):
    code = message.text.strip().replace(" ", "")
    if code in auth_sessions:
        auth_sessions[code]["status"] = "confirmed"
        auth_sessions[code]["user"] = {
            "id": message.from_user.id,
            "name": message.from_user.full_name or message.from_user.first_name,
            "username": message.from_user.username,
            "avatar_url": None
        }
        await message.answer("✅ Вход успешно подтвержден на ТВ!")
    else:
        await message.answer("Отправьте 6-значный код с экрана ТВ или перейдите по QR-коду.")

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

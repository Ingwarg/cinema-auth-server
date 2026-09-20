import asyncio
import os
import random
import time
import sqlite3
from typing import Optional, List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, CommandObject
import uvicorn

BOT_TOKEN = os.getenv("BOT_TOKEN", "8812606946:AAGXmy58wS8KeRYTU8cSpTC4rJQOnsm1Ntc")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

# --- БАЗА ДАННЫХ (SQLite) ---
DB_FILE = "cinema_sync.db"

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        # История просмотров
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS watch_history (
                user_id INTEGER,
                movie_id TEXT,
                title TEXT,
                poster_url TEXT,
                backdrop_url TEXT,
                season INTEGER,
                episode INTEGER,
                position_sec INTEGER,
                duration_sec INTEGER,
                updated_at INTEGER,
                PRIMARY KEY (user_id, movie_id)
            )
        """)
        # Закладки (Избранное)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                user_id INTEGER,
                movie_id TEXT,
                title TEXT,
                poster_url TEXT,
                backdrop_url TEXT,
                created_at INTEGER,
                PRIMARY KEY (user_id, movie_id)
            )
        """)
        conn.commit()

init_db()

# --- СЕССИИ АВТОРИЗАЦИИ ---
auth_sessions = {}

def cleanup_expired():
    now = time.time()
    expired = [c for c, data in auth_sessions.items() if now - data["created_at"] > 300]
    for c in expired:
        del auth_sessions[c]

@app.get("/")
async def root():
    return {"status": "ok", "service": "Bcinema Auth & Sync Cloud"}

# --- ЭНДПОИНТЫ АВТОРИЗАЦИИ ---
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

# --- ЭНДПОИНТЫ СИНХРОНИЗАЦИИ ИСТОРИИ ---
class HistoryItem(BaseModel):
    user_id: int
    movie_id: str
    title: str
    poster_url: Optional[str] = ""
    backdrop_url: Optional[str] = ""
    season: Optional[int] = 0
    episode: Optional[int] = 0
    position_sec: int
    duration_sec: int

@app.post("/api/sync/history")
async def save_history(item: HistoryItem):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO watch_history (user_id, movie_id, title, poster_url, backdrop_url, season, episode, position_sec, duration_sec, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, movie_id) DO UPDATE SET
                title=excluded.title,
                poster_url=excluded.poster_url,
                backdrop_url=excluded.backdrop_url,
                season=excluded.season,
                episode=excluded.episode,
                position_sec=excluded.position_sec,
                duration_sec=excluded.duration_sec,
                updated_at=excluded.updated_at
        """, (
            item.user_id, item.movie_id, item.title, item.poster_url, item.backdrop_url,
            item.season, item.episode, item.position_sec, item.duration_sec, int(time.time())
        ))
        conn.commit()
    return {"status": "success"}

@app.get("/api/sync/history")
async def get_history(user_id: int):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT movie_id, title, poster_url, backdrop_url, season, episode, position_sec, duration_sec, updated_at 
            FROM watch_history 
            WHERE user_id = ? 
            ORDER BY updated_at DESC LIMIT 50
        """, (user_id,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

# --- ТЕЛЕГРАМ БОТ ---
@dp.message(CommandStart(deep_link=True))
async def handle_start_deep_link(message: types.Message, command: CommandObject):
    code = command.args.strip() if command.args else None
    
    if not code or code not in auth_sessions:
        await message.answer(
            "❌ <b>Код недействителен или срок его действия истек.</b>\n\n"
            "Пожалуйста, откройте окно входа на экране ТВ заново.",
            parse_mode="HTML"
        )
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
    
    await message.answer(
        f"✅ <b>Вход успешно выполнен!</b>\n\n"
        f"Телевизор авторизован под профилем <b>{message.from_user.first_name}</b>.\n"
        f"История просмотров и закладки теперь синхронизируются со всеми вашими устройствами! 🍿",
        parse_mode="HTML"
    )

@dp.message(CommandStart())
async def handle_regular_start(message: types.Message):
    await message.answer(
        "👋 <b>Добро пожаловать в Bcinema!</b>\n\n"
        "📺 Чтобы войти на телевизоре, планшете или телефоне:\n"
        "1. Откройте приложение ➔ раздел <b>«Профиль»</b>.\n"
        "2. На экране появится 6-значный код.\n\n"
        "👇 <b>Отправьте этот код сюда ответным сообщением:</b>",
        parse_mode="HTML"
    )

@dp.message(F.text)
async def handle_manual_code(message: types.Message):
    code = message.text.strip().replace(" ", "").replace("-", "")
    
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
            f"✅ <b>Код подтвержден! Вход выполнен!</b>\n"
            f"Устройство авторизовано под именем <b>{message.from_user.first_name}</b>.",
            parse_mode="HTML"
        )
    elif len(code) == 6 and code.isdigit():
        await message.answer("❌ Код не найден или уже истек. Попробуйте еще раз.")
    else:
        await message.answer("ℹ️ Отправьте 6-значный код с экрана приложения.")

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

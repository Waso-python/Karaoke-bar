from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import aiohttp
import json
from .models import Session, User
import os
from dotenv import load_dotenv
from typing import List, Dict
import logging
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

load_dotenv()

# Конфигурация
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = "http://localhost:8000"

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=TELEGRAM_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Состояния FSM


class UserState(StatesGroup):
    waiting_for_name = State()
    waiting_for_table = State()
    ready_to_search = State()


async def fetch_songs(query: str) -> List[Dict]:
    """Получение песен из API"""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_URL}/songs/search/?query={query}") as response:
            return await response.json()


def create_song_buttons(songs: List[Dict]) -> InlineKeyboardMarkup:
    """Создание клавиатуры с кнопками песен"""
    keyboard = []
    for song in songs[:10]:  # Ограничиваем до 10 результатов
        backing = "🎵" if song.get("has_backing") else ""
        button_text = f"{song['artist']} - {song['title']} {backing}"
        callback_data = f"song_{song['id']}"
        keyboard.append([InlineKeyboardButton(
            text=button_text, callback_data=callback_data)])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


@dp.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    """Обработка команды /start"""
    session = Session()
    user = session.query(User).filter_by(
        telegram_id=message.from_user.id).first()

    if not user:
        # Сохраняем данные о пользователе
        user = User(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            language_code=message.from_user.language_code,
            is_registered=False
        )
        session.add(user)
        session.commit()

        await message.reply(
            "Добро пожаловать в караоке-бот! 🎤\n"
            "Пожалуйста, введите ваше имя:"
        )
        await state.set_state(UserState.waiting_for_name)
    else:
        if not user.is_registered:
            await message.reply("Пожалуйста, введите ваше имя:")
            await state.set_state(UserState.waiting_for_name)
        elif not user.table_number:
            await message.reply("Пожалуйста, укажите номер вашего столика:")
            await state.set_state(UserState.waiting_for_table)
        else:
            await message.reply(
                f"С возвращением, {user.display_name}! Ваш столик: {user.table_number}\n"
                "Введите название песни или исполнителя для поиска:"
            )
            await state.set_state(UserState.ready_to_search)

    session.close()


@dp.message(StateFilter(UserState.waiting_for_name))
async def process_name(message: types.Message, state: FSMContext):
    """Обработка ввод�� имени"""
    session = Session()
    user = session.query(User).filter_by(
        telegram_id=message.from_user.id).first()

    user.display_name = message.text
    user.is_registered = True
    session.commit()

    await message.reply(
        f"Спасибо, {message.text}! Теперь укажите номер вашего столика:"
    )
    await state.set_state(UserState.waiting_for_table)
    session.close()


@dp.message(StateFilter(UserState.waiting_for_table))
async def process_table(message: types.Message, state: FSMContext):
    """Обработка ввода номера столика"""
    session = Session()
    user = session.query(User).filter_by(
        telegram_id=message.from_user.id).first()

    user.table_number = message.text
    session.commit()

    await message.reply(
        f"Отлично! Ваш столик: {message.text}\n"
        "Теперь введите название песни или исполнителя для поиска:"
    )
    await state.set_state(UserState.ready_to_search)
    session.close()


@dp.message(StateFilter(UserState.ready_to_search))
async def process_search(message: types.Message, state: FSMContext):
    """Обработка поискового запроса"""
    songs = await fetch_songs(message.text)

    if not songs:
        await message.reply(
            "К сожалению, ничего не найдено. Попробуйте другой запрос."
        )
        return

    keyboard = create_song_buttons(songs)
    await message.reply(
        "Выберите песню из списка:",
        reply_markup=keyboard
    )


@dp.callback_query(lambda c: c.data.startswith('song_'))
async def process_song_selection(callback_query: types.CallbackQuery):
    """Обработка выбора песни"""
    song_id = callback_query.data.split('_')[1]
    await callback_query.message.reply(
        f"ID выбранной песни: {song_id}\n"
        "Вы можете продолжить поиск, введя новый запрос."
    )
    await callback_query.answer()


async def run_bot():
    """Запуск бота"""
    try:
        logger.info("Starting bot...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(run_bot())

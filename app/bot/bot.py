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
from sqlalchemy.exc import SQLAlchemyError

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


async def check_registration_state(user: User, message: types.Message, state: FSMContext) -> bool:
    """Проверяет состояние регистрации пользователя и устанавливает нужное состояние"""
    try:
        if not user.is_registered:
            await message.reply(
                "Кажется, регистрация не была завершена.\n"
                "Пожалуйста, введите ваше имя:"
            )
            await state.set_state(UserState.waiting_for_name)
            return False

        if not user.table_number:
            await message.reply(
                "Пожалуйста, укажите номер вашего столика:"
            )
            await state.set_state(UserState.waiting_for_table)
            return False

        return True
    except Exception as e:
        logger.error(f"Error in check_registration_state: {e}")
        await message.reply("Произошла ошибка. Пожалуйста, начните сначала с команды /start")
        return False


async def fetch_songs(query: str) -> List[Dict]:
    """Получение песен из API"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL}/songs/search/?query={query}") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"API error: {response.status}")
                    return []
    except Exception as e:
        logger.error(f"Error fetching songs: {e}")
        return []


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
    try:
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
            # Проверяем состояние регистрации
            await check_registration_state(user, message, state)

    except SQLAlchemyError as e:
        logger.error(f"Database error: {e}")
        await message.reply("Произошла ошибка базы данных. Пожалуйста, попробуйте позже.")
    except Exception as e:
        logger.error(f"Unexpected error in start_command: {e}")
        await message.reply("Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже.")
    finally:
        session.close()


@dp.message(StateFilter(UserState.waiting_for_name))
async def process_name(message: types.Message, state: FSMContext):
    """Обработка ввода имени"""
    try:
        session = Session()
        user = session.query(User).filter_by(
            telegram_id=message.from_user.id).first()

        if not user:
            await message.reply("Произошла ошибка. Пожалуйста, начните сначала с команды /start")
            return

        user.display_name = message.text
        user.is_registered = True
        session.commit()

        await message.reply(
            f"Спасибо, {message.text}! Теперь укажите номер вашего столика:"
        )
        await state.set_state(UserState.waiting_for_table)

    except SQLAlchemyError as e:
        logger.error(f"Database error in process_name: {e}")
        await message.reply("Произошла ошибка при сохранении данных. Пожалуйста, попробуйте еще раз.")
    except Exception as e:
        logger.error(f"Error in process_name: {e}")
        await message.reply("Произошла ошибка. Пожалуйста, попробуйте еще раз.")
    finally:
        session.close()


@dp.message(StateFilter(UserState.waiting_for_table))
async def process_table(message: types.Message, state: FSMContext):
    """Обработка ввода номера столика"""
    try:
        session = Session()
        user = session.query(User).filter_by(
            telegram_id=message.from_user.id).first()

        if not user:
            await message.reply("Произошла ошибка. Пожалуйста, начните сначала с команды /start")
            return

        user.table_number = message.text
        session.commit()

        await message.reply(
            f"Отлично! Ваш столик: {message.text}\n"
            "Теперь введите название песни или исполнителя для поиска:"
        )
        await state.set_state(UserState.ready_to_search)

    except SQLAlchemyError as e:
        logger.error(f"Database error in process_table: {e}")
        await message.reply("Произошла ошибка при сохранении данных. Пожалуйста, попробуйте еще раз.")
    except Exception as e:
        logger.error(f"Error in process_table: {e}")
        await message.reply("Произошла ошибка. Пожалуйста, попробуйте еще раз.")
    finally:
        session.close()


@dp.message(StateFilter(UserState.ready_to_search))
async def process_search(message: types.Message, state: FSMContext):
    """Обработка поискового запроса"""
    try:
        # Проверяем состояние регистрации
        session = Session()
        user = session.query(User).filter_by(
            telegram_id=message.from_user.id).first()

        if not await check_registration_state(user, message, state):
            return

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

    except Exception as e:
        logger.error(f"Error in process_search: {e}")
        await message.reply(
            "Произошла ошибка при поиске. Пожалуйста, попробуйте еще раз или используйте другой запрос."
        )
    finally:
        session.close()


@dp.callback_query(lambda c: c.data.startswith('song_'))
async def process_song_selection(callback_query: types.CallbackQuery):
    """Обработка выбора песни"""
    try:
        song_id = callback_query.data.split('_')[1]
        await callback_query.message.reply(
            f"ID выбранной песни: {song_id}\n"
            "Вы можете продолжить поиск, введя новый запрос."
        )
        await callback_query.answer()
    except Exception as e:
        logger.error(f"Error in process_song_selection: {e}")
        await callback_query.message.reply("Произошла ошибка при выборе песни. Пожалуйста, попробуйте еще раз.")


@dp.message()
async def handle_unknown_message(message: types.Message, state: FSMContext):
    """Обработка всех необработанных сообщений"""
    try:
        session = Session()
        user = session.query(User).filter_by(
            telegram_id=message.from_user.id).first()

        if not user:
            await message.reply(
                "Добро пожаловать в караоке-бот! 🎤\n"
                "Пожалуйста, начните с команды /start"
            )
            return

        current_state = await state.get_state()
        if not current_state:
            # Проверяем состояние регистрации и устанавливаем соответствующее состояние
            if not user.is_registered:
                await message.reply(
                    "Кажется, регистрация не была завершена.\n"
                    "Пожалуйста, введите ваше имя:"
                )
                await state.set_state(UserState.waiting_for_name)
            elif not user.table_number:
                await message.reply(
                    "Пожалуйста, укажите номер вашего столика:"
                )
                await state.set_state(UserState.waiting_for_table)
            else:
                await message.reply(
                    f"Здравствуйте, {user.display_name}! Ваш столик: {user.table_number}\n"
                    "Введите название песни или исполнителя для поиска:"
                )
                await state.set_state(UserState.ready_to_search)

    except Exception as e:
        logger.error(f"Error in handle_unknown_message: {e}")
        await message.reply(
            "Произошла ошибка. Пожалуйста, начните с команды /start"
        )
    finally:
        session.close()


async def run_bot():
    """Запуск бота"""
    try:
        logger.info("Starting bot...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
    finally:
        if bot.session:
            await bot.session.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(run_bot())

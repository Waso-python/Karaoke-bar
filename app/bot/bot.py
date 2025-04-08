from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, StateFilter, or_f, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import aiohttp
import json
from .models import Session, User, Admin, Order
from app.utils import SONGS
import os
from dotenv import load_dotenv
from typing import List, Dict
import logging
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timezone, timedelta
from aiogram import F
from logging.handlers import RotatingFileHandler
from functools import wraps

load_dotenv()

# Конфигурация
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = "http://localhost:8009"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

# Статусы заказов
ORDER_STATUSES = {
    "pending": "⏳ Ожидает исполнения",
    "completed": "✅ Исполнена",
    "cancelled": "❌ Отменена"
}


async def ensure_registered_user(message: types.Message, state: FSMContext) -> bool:
    """Проверяет, зарегистрирован ли пользователь, и перенаправляет на регистрацию, если нет"""
    session = Session()
    user = session.query(User).filter_by(
        telegram_id=message.from_user.id).first()
    session.close()

    if not user or not user.is_registered:
        await message.reply(
            "Вы не зарегистрированы. Пожалуйста, используйте команду /start для регистрации."
        )
        return False
    return True


async def check_registration_expiry(user: User, message: types.Message, state: FSMContext) -> bool:
    """Проверяет, не истек ли срок регистрации пользователя"""
    if not user.registered_at:
        return True

    # Убедимся, что registered_at имеет часовой пояс
    if user.registered_at.tzinfo is None:
        registered_at = user.registered_at.replace(tzinfo=timezone.utc)
    else:
        registered_at = user.registered_at

    expiry_time = registered_at + timedelta(hours=16)
    current_time = datetime.now(timezone.utc)

    if current_time > expiry_time:
        # Сбрасываем регистрацию
        session = Session()
        try:
            user = session.query(User).filter_by(
                telegram_id=user.telegram_id).first()
            user.is_registered = False
            user.display_name = None
            user.table_number = None
            user.registered_at = None
            session.commit()

            await state.clear()
            await message.reply(
                "⏰ Срок вашей регистрации истек.\n"
                "Пожалуйста, используйте команду /start для повторной регистрации."
            )
            return False
        except Exception as e:
            logger.error(f"Error in check_registration_expiry: {e}")
        finally:
            session.close()

    return True


def require_registration(handler):
    @wraps(handler)
    async def wrapper(event, *args, **kwargs):
        print("require_registration")

        # Определяем telegram_id в зависимости от типа события
        if isinstance(event, types.CallbackQuery):
            telegram_id = event.from_user.id
            reply_to = event.message.reply
        else:  # Message
            telegram_id = event.from_user.id
            reply_to = event.reply

        session = Session()
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        admin = session.query(Admin).filter_by(telegram_id=telegram_id).first()
        session.close()

        # Пропускаем проверку, если пользователь является администратором
        if admin:
            return await handler(event, *args, **kwargs)

        if not user or not user.is_registered:
            print("user not registered")
            await reply_to(
                "Вы не зарегистрированы. Пожалуйста, используйте команду /start для регистрации."
            )
            return

        # Проверяем срок регистрации
        if not await check_registration_expiry(user, event if isinstance(event, types.Message) else event.message, kwargs.get('state')):
            return

        return await handler(event, *args, **kwargs)

    return wrapper


def moscow_time(dt: datetime) -> datetime:
    """Конвертация времени в московское"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    moscow_tz = timezone(timedelta(hours=3))  # UTC+3 для Москвы
    return dt.astimezone(moscow_tz)


# Настройка логирования
log_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log_file = "logs/user_searches.log"

# Создаем директорию для логов, если она не существует
os.makedirs(os.path.dirname(log_file), exist_ok=True)

file_handler = RotatingFileHandler(
    log_file, maxBytes=5*1024*1024, backupCount=2)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)

# Инициализация бота и диспетчера
bot = Bot(token=TELEGRAM_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Состояния FSM


class UserState(StatesGroup):
    waiting_for_name = State()
    waiting_for_table = State()
    ready_to_search = State()
    waiting_for_admin_password = State()


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


def create_song_buttons(songs: List[Dict], page: int = 0, is_admin: bool = False) -> InlineKeyboardMarkup:
    """Создание клавиатуры с кнопками песен и навигацией"""
    keyboard = []
    start_idx = page * 10
    end_idx = start_idx + 10
    current_songs = songs[start_idx:end_idx]

    # Добавляем кнопки с песнями
    for song in current_songs:
        backing = "🎵" if song.get("has_backing") else "🎤"
        button_text = f"{backing} {song['artist']} - {song['title']}"
        callback_data = f"song_{song['id']}"
        keyboard.append([InlineKeyboardButton(
            text=button_text, callback_data=callback_data)])

    # Добавляем навигационные кнопки
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="⬅️ Назад", callback_data=f"page_{page-1}"))

    if end_idx < len(songs):
        nav_buttons.append(InlineKeyboardButton(
            text="Вперед ➡️", callback_data=f"page_{page+1}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    # Добавляем счетчик страниц и кнопку выхода
    bottom_row = []
    bottom_row.append(InlineKeyboardButton(
        text=f"📄 {page + 1}/{(len(songs) - 1) // 10 + 1}",
        callback_data="ignore"
    ))
    bottom_row.append(InlineKeyboardButton(
        text="❌ Выход",
        callback_data="exit_search"
    ))
    keyboard.append(bottom_row)

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def create_order_buttons(song_id: str) -> InlineKeyboardMarkup:
    """Создание клавиатуры с кнопками 'Заказать' и 'Найти другую'"""
    keyboard = [
        [InlineKeyboardButton(
            text="🎵 Заказать", callback_data=f"order_{song_id}")],
        [InlineKeyboardButton(text="🔍 Найти другую",
                              callback_data="find_another")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def create_search_type_buttons() -> InlineKeyboardMarkup:
    """Создание клавиатуры с кнопками типов поиска"""
    keyboard = [
        [InlineKeyboardButton(
            text="🎤 Поиск по исполнителю",
            callback_data="search_by_artist"
        )],
        [InlineKeyboardButton(
            text="🎵 Поиск по названию песни",
            callback_data="search_by_title"
        )],
        [InlineKeyboardButton(
            text="🔍 Свободный поиск",
            callback_data="search_free"
        )]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def create_reorder_button(song_id: int) -> InlineKeyboardMarkup:
    """Создание кнопки для повторного заказа песни"""
    keyboard = [
        [InlineKeyboardButton(
            text="🔄 Заказать снова",
            callback_data=f"order_{song_id}"
        )]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


@dp.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    """Обработка команды /start"""
    print("start_command")
    try:
        print(message.from_user.id)
        session = Session()

        # Проверяем, является ли пользователь администратором
        admin = session.query(Admin).filter_by(
            telegram_id=message.from_user.id).first()

        if admin:
            await message.reply(
                "👋 Добро пожаловать в панель администратора!\n\n"
                "Доступные команды:\n"
                "/orders - просмотр активных заказов\n"
                "/completed - просмотр исполненных заказов\n"
                "/search - поиск песен\n"
                "/new_admin - добавить нового администратора",
                parse_mode="HTML"
            )
            return

        user = session.query(User).filter_by(
            telegram_id=message.from_user.id).first()

        if not user:
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
                "👋 Добро пожаловать в караоке-бот!\n\n"
                "<b>Давайте познакомимся!</b>\n"
                "Пожалуйста, введите ваше имя:",
                parse_mode="HTML"
            )
            await state.set_state(UserState.waiting_for_name)
        else:
            await check_registration_state(user, message, state)

    except SQLAlchemyError as e:
        logger.error(f"Database error: {e}")
        await message.reply("❌ Произошла ошибка базы данных. Пожалуйста, попробуйте позже.")
    finally:
        session.close()


@dp.message(Command("history"))
@require_registration
async def show_user_history(message: types.Message):
    """Показать последние 10 уникальных исполненных заказов пользователя"""
    print("show_user_history")
    try:
        session = Session()
        # Получаем все исполненные заказы пользователя
        orders = session.query(Order).filter_by(
            user_id=message.from_user.id,
            status="completed"
        ).order_by(
            Order.ordered_at.desc()
        ).all()

        if not orders:
            await message.reply(
                "📝 У вас пока нет исполненных заказов.\n"
                "Используйте команду /search для поиска и заказа песен."
            )
            return

        # Создаем словарь для хранения уникальных песен
        unique_songs = {}
        for order in orders:
            song_key = f"{order.song_artist}:{order.song_title}"
            if song_key not in unique_songs:
                unique_songs[song_key] = order

        # Берем только 10 последних уникальных песен
        unique_orders = list(unique_songs.values())[:10]

        # Отправляем заголовок
        await message.reply(
            "📋 <b>Ваши последние исполненные песни:</b>",
            parse_mode="HTML"
        )

        # Отправляем каждую песню отдельным сообщением
        for order in unique_orders:
            backing_emoji = "🎵" if order.has_backing else "🎤"
            song_info = (
                f"{backing_emoji} <b>Песня #{order.song_id}</b>\n"
                f"👨‍🎤 <b>Исполнитель:</b> {order.song_artist}\n"
                f"🎵 <b>Название:</b> {order.song_title}\n"
                f"🎹 <b>Тип:</b> {'С бэк-треком' if order.has_backing else 'Без бэк-трека'}"
            )
            
            # Создаем кнопку для повторного заказа
            keyboard = create_reorder_button(order.song_id)
            
            await message.reply(
                song_info,
                parse_mode="HTML",
                reply_markup=keyboard
            )

    except Exception as e:
        logger.error(f"Error in show_user_history: {e}")
        await message.reply(
            "❌ Произошла ошибка при получении истории заказов."
        )
    finally:
        session.close()

@dp.message(
    Command("reset"),
    F.text == "/reset",
    flags={"command_priority": 1}
)
@require_registration
async def reset_command(message: types.Message, state: FSMContext):
    """Сброс регистрации пользователя"""
    print("reset_command")
    try:
        session = Session()

        # Проверяем, является ли пользователь администратором
        admin = session.query(Admin).filter_by(
            telegram_id=message.from_user.id).first()

        if admin:
            await message.reply(
                "❌ Команда сброса регистрации недоступна для администраторов."
            )
            return

        user = session.query(User).filter_by(
            telegram_id=message.from_user.id).first()

        if user:
            # Сбрасываем данные пользователя
            user.display_name = None
            user.table_number = None
            user.is_registered = False

            try:
                session.commit()  # Фиксируем изменения
                session.refresh(user)  # Обновляем объект пользователя

                # Проверяем, что изменения сохранены
                if not user.is_registered and user.display_name is None and user.table_number is None:
                    await message.reply(
                        "🔄 Регистрация сброшена.\n"
                        "Для повторной регистрации используйте команду /start"
                    )
                else:
                    await message.reply(
                        "❌ Не удалось сбросить регистрацию. Пожалуйста, попробуйте еще раз."
                    )
            except Exception as e:
                logger.error(f"Error committing changes: {e}")
                await message.reply(
                    "❌ Произошла ошибка при сбросе регистрации. Пожалуйста, попробуйте позже."
                )

            # Очищаем состояние FSM
            await state.clear()

            # Очищаем данные поиска
            await state.set_data({})

        else:
            await message.reply(
                "❓ Вы еще не зарегистрированы.\n"
                "Для регистрации используйте команду /start"
            )

    except SQLAlchemyError as e:
        logger.error(f"Database error in reset_command: {e}")
        await message.reply(
            "❌ Произошла ошибка при сбросе регистрации. Пожалуйста, попробуйте позже."
        )
    except Exception as e:
        logger.error(f"Error in reset_command: {e}")
        await message.reply(
            "❌ Произошла ошибка. Пожалуйста, попробуйте позже."
        )
    finally:
        session.close()


@dp.message(Command("new_admin"))
async def new_admin_command(message: types.Message, state: FSMContext):
    """Обработка команды /new_admin"""
    print("new_admin_command")
    await message.reply("Пожалуйста, введите пароль администратора:")
    await state.set_state(UserState.waiting_for_admin_password)


@dp.message(StateFilter(UserState.waiting_for_admin_password))
async def process_admin_password(message: types.Message, state: FSMContext):
    """Обработка ввода пароля администратора"""
    print("process_admin_password")
    if message.text == ADMIN_PASSWORD:
        try:
            session = Session()
            admin = session.query(Admin).filter_by(
                telegram_id=message.from_user.id).first()
            if not admin:
                # Добавляем нового администратора
                admin = Admin(
                    telegram_id=message.from_user.id,
                    username=message.from_user.username
                )
                session.add(admin)
                session.commit()
                await message.reply("Вы успешно добавлены в список администраторов!")
            else:
                await message.reply("Вы уже являетесь администратором.")
        except SQLAlchemyError as e:
            logger.error(f"Database error in process_admin_password: {e}")
            await message.reply("Произошла ошибка базы данных. Пожалуйста, попробуйте позже.")
        finally:
            session.close()
    else:
        await message.reply("Неверный пароль. Попробуйте еще раз или отмените команду.")
    await state.clear()


@dp.message(StateFilter(UserState.waiting_for_name))
async def process_name(message: types.Message, state: FSMContext):
    """Обработка ввода имени"""
    print("process_name")
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

        if user:
            user.table_number = message.text
            user.is_registered = True
            # Устанавливаем время регистрации с явным указанием UTC
            user.registered_at = datetime.now(timezone.utc)
            session.commit()

            await message.reply(
                f"Отлично! Ваш столик: {message.text}\n\n"
                "Доступные команды:\n"
                "/search - поиск и заказ песен\n"
                "/history - ваши последние заказы\n"
                "/reset - сброс регистрации\n\n"
                "Выберите тип поиска:",
                reply_markup=create_search_type_buttons()
            )
            await state.set_state(UserState.ready_to_search)
        else:
            await message.reply(
                "Произошла ошибка. Пожалуйста, начните регистрацию заново с команды /start"
            )
            await state.clear()

    except SQLAlchemyError as e:
        logger.error(f"Database error in process_table: {e}")
        await message.reply("Произошла ошибка при сохранении данных. Пожалуйста, попробуйте еще раз.")
    finally:
        session.close()


@dp.message(StateFilter(UserState.ready_to_search))
async def show_search_options(message: types.Message, state: FSMContext):
    """Показ опций поиска"""
    print("show_search_options")
    await message.reply(
        "Выберите тип поиска:",
        reply_markup=create_search_type_buttons()
    )


class SearchState(StatesGroup):
    waiting_for_artist = State()
    waiting_for_title = State()
    waiting_for_free_search = State()


def get_name_variations(name: str) -> list[str]:
    """Создает варианты написания имени исполнителя"""
    name = name.lower().strip()
    parts = name.split()
    variations = [name]  # оригинальное написание

    # Если имя состоит из нескольких частей
    if len(parts) > 1:
        # Добавляем вариант с обратным порядком слов
        variations.append(' '.join(reversed(parts)))

        # Если частей больше двух, пробуем разные комбинации
        if len(parts) > 2:
            for i in range(len(parts)):
                rotated = parts[i:] + parts[:i]
                variations.append(' '.join(rotated))

    return list(set(variations))  # убираем дубликаты


@dp.callback_query(lambda c: c.data.startswith('search_'))
@require_registration
async def process_search_type(callback_query: CallbackQuery, state: FSMContext):
    """Обработка выбора типа поиска"""
    search_type = callback_query.data
    print(search_type)

    if search_type == "search_by_artist":
        await state.set_state(SearchState.waiting_for_artist)
        await callback_query.message.reply(
            "Введите имя исполнителя:"
        )
    elif search_type == "search_by_title":
        await state.set_state(SearchState.waiting_for_title)
        await callback_query.message.reply(
            "Введите название песни:"
        )
    elif search_type == "search_free":
        await state.set_state(SearchState.waiting_for_free_search)
        await callback_query.message.reply(
            "Введите любой текст для поиска:"
        )
    else:
        await callback_query.answer("Неизвестный тип поиска.")
        return

    await callback_query.answer()


@dp.message(StateFilter(SearchState.waiting_for_artist))
@require_registration
async def process_artist_search(message: types.Message, state: FSMContext):
    """Обработка поиска по исполнителю"""
    try:
        # Получаем все возможные варианты написания имени
        name_variations = get_name_variations(message.text)
        all_results = []

        async with aiohttp.ClientSession() as session:
            # Проверяем каждый вариант написания
            for name_variant in name_variations:
                async with session.get(
                    f"{API_URL}/songs/by-artist/?artist={name_variant}"
                ) as response:
                    if response.status == 200:
                        songs = await response.json()
                        all_results.extend(songs)

        # Убираем дубликаты по ID песни
        unique_results = {song['id']: song for song in all_results}.values()
        songs = list(unique_results)

        if not songs:
            await message.reply(
                "Исполнитель не найден. Попробуйте другой запрос или выберите другой тип поиска:",
                reply_markup=create_search_type_buttons()
            )
            return

        # Логируем успешный поиск
        logger.info(
            f"User {message.from_user.id} searched artist: {message.text}. "
            f"Variations tried: {name_variations}. Found: {len(songs)} songs"
        )

        await state.update_data(search_results=songs)
        keyboard = create_song_buttons(songs, page=0)
        await message.reply(
            f"Найдено песен исполнителя: {len(songs)}\n"
            "Выберите песню из списка:",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Error in process_artist_search: {e}")
        await message.reply("Произошла ошибка при поиске.")


@dp.message(StateFilter(SearchState.waiting_for_title))
@require_registration
async def process_title_search(message: types.Message, state: FSMContext):
    """Обработка поиска по названию песни"""
    print("process_title_search")
    try:
        user_id = message.from_user.id
        logger.info(f"User {user_id} searching by title: {message.text}")

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{API_URL}/songs/by-title/?title={message.text}"
            ) as response:
                if response.status == 200:
                    songs = await response.json()
                    if not songs:
                        await message.reply(
                            "Песня не найдена. Попробуйте другой запрос или выберите другой тип поиска:",
                            reply_markup=create_search_type_buttons()
                        )
                        return

                    await state.update_data(search_results=songs)
                    keyboard = create_song_buttons(songs, page=0)
                    await message.reply(
                        f"Найдено песен: {len(songs)}\n"
                        "Выберите песню из списка:",
                        reply_markup=keyboard
                    )
                else:
                    await message.reply("Произошла ошибка при поиске.")
    except Exception as e:
        logger.error(f"Error in process_title_search: {e}")
        await message.reply("Произошла ошибка при поиске.")


@dp.message(StateFilter(SearchState.waiting_for_free_search))
@require_registration
async def process_free_search(message: types.Message, state: FSMContext):
    """Обработка свободного поиска"""
    print("process_free_search")
    try:
        user_id = message.from_user.id
        logger.info(f"User {user_id} performing free search: {message.text}")

        songs = await fetch_songs(message.text)
        if not songs:
            await message.reply(
                "Ничего не найдено. Попробуйте другой запрос или выберите другой тип поиска:",
                reply_markup=create_search_type_buttons()
            )
            return

        await state.update_data(search_results=songs)
        keyboard = create_song_buttons(songs, page=0)
        await message.reply(
            f"Найдено песен: {len(songs)}\n"
            "Выберите песню из списка:",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Error in process_free_search: {e}")
        await message.reply("Произошла ошибка при поиске.")


@dp.callback_query(lambda c: c.data.startswith('song_'))
@require_registration
async def process_song_selection(callback_query: CallbackQuery):
    """Обработка выбора песни"""
    print("process_song_selection")
    try:
        song_id = callback_query.data.split('_')[1]
        await callback_query.message.reply(
            f"ID выбранной песни: {song_id}\n"
            "Выберите действие:",
            reply_markup=create_order_buttons(song_id)
        )
        await callback_query.answer()
    except Exception as e:
        logger.error(f"Error in process_song_selection: {e}")
        await callback_query.message.reply("Произошла ошибка при выборе песни. Пожалуйста, попробуйте еще раз.")


@dp.callback_query(lambda c: c.data.startswith('order_'))
@require_registration
async def process_order(callback_query: CallbackQuery, state: FSMContext):
    """Обработка заказа песни"""
    try:
        song_id = callback_query.data.split('_')[1]
        session = Session()
        user = session.query(User).filter_by(
            telegram_id=callback_query.from_user.id).first()

        song = next((song for song in SONGS if str(song.id) == song_id), None)

        if user and song:
            # Создаем новый заказ
            order = Order(
                user_id=user.telegram_id,
                song_id=song.id,
                song_title=song.title,
                song_artist=song.artist,
                has_backing=song.has_backing,
                status="pending"
            )
            session.add(order)
            session.commit()

            backing_status = "🎵 С бэк-треком" if song.has_backing else "🎤 Без бэк-трека"
            order_info = (
                f"<b>Новый заказ песни! (ID: {order.id})</b>\n\n"
                f"🎼 <b>Песня:</b> {song.title}\n"
                f"👨‍🎤 <b>Исполнитель:</b> {song.artist}\n"
                f"ℹ️ <b>ID песни:</b> {song_id}\n"
                f"🎹 <b>Тип:</b> {backing_status}\n\n"
                f"👤 <b>Информация о клиенте:</b>\n"
                f"• Имя: {user.display_name}\n"
                f"• Столик: {user.table_number}\n"
                f"• Username: @{user.username}\n"
                f"• Name: {user.first_name} {user.last_name}\n"
                f"• Заказано: {moscow_time(order.ordered_at).strftime('%H:%M:%S')}\n"
                f"• Статус: {ORDER_STATUSES[order.status]}"
            )

            # Передаем ID заказа в функцию уведомления
            await notify_admins(order_info, order.id)

            await callback_query.message.reply(
                "✅ Ваш заказ отправлен!\n\n"
                "Выберите тип поиска для нового заказа или используйте /reset для сброса регистрации:",
                reply_markup=create_search_type_buttons(),
                parse_mode="HTML"
            )

            await state.set_state(UserState.ready_to_search)

        else:
            await callback_query.message.reply(
                "❌ Произошла ошибка при заказе. Пожалуйста, попробуйте еще раз.",
                parse_mode="HTML"
            )

        await callback_query.answer()
    except Exception as e:
        logger.error(f"Error in process_order: {e}")
        await callback_query.message.reply(
            "❌ Произошла ошибка при заказе. Пожалуйста, попробуйте еще раз.",
            parse_mode="HTML"
        )
    finally:
        session.close()


@dp.callback_query(lambda c: c.data == 'find_another')
@require_registration
async def process_find_another(callback_query: CallbackQuery):
    """Обработка нажатия 'Найти другую'"""
    try:
        await callback_query.message.reply(
            "Выберите тип поиска:",
            reply_markup=create_search_type_buttons()
        )
        await callback_query.answer()
    except Exception as e:
        logger.error(f"Error in process_find_another: {e}")
        await callback_query.message.reply("Произошла ошибка. Пожалуйста, попробуйте еще раз.")


async def notify_admins(order_info: str, order_id: int):
    """Отправка уведомления администраторам о новом заказе"""
    session = Session()
    try:
        admins = session.query(Admin).all()
        for admin in admins:
            # Добавляем команды управления в конец сообщения
            full_message = (
                f"{order_info}\n\n"
                f"Действия с заказом:\n"
                f"/complete_{order_id} - отметить как исполненный\n"
                f"/cancel_{order_id} - отменить заказ"
            )
            await bot.send_message(
                admin.telegram_id,
                full_message,
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Error in notify_admins: {e}")
    finally:
        session.close()


@dp.message(Command("completed"))
async def list_completed_orders(message: types.Message):
    """Показать список исполненных заказов за последние 16 часов"""
    print("list_completed_orders")
    try:
        session = Session()
        admin = session.query(Admin).filter_by(
            telegram_id=message.from_user.id).first()

        if not admin:
            await message.reply("❌ Эта команда доступна только администраторам.")
            return

        # Вычисляем время 16 часов назад
        time_threshold = datetime.now(timezone.utc) - timedelta(hours=16)

        # Получаем все исполненные и отмененные заказы за последние 16 часов
        orders = session.query(Order).filter(
            Order.status.in_(["completed", "cancelled"]),
            Order.completed_at >= time_threshold
        ).order_by(Order.completed_at.desc()).all()

        if not orders:
            await message.reply(
                "📝 Нет исполненных заказов за последние 16 часов",
                parse_mode="HTML"
            )
            return

        # Группируем заказы по столикам
        orders_by_table = {}
        for order in orders:
            table = order.user.table_number
            if table not in orders_by_table:
                orders_by_table[table] = []
            orders_by_table[table].append(order)

        # Отправляем сводную информацию
        summary = (
            "📊 <b>Статистика за последние 16 часов:</b>\n"
            f"Всего заказов: {len(orders)}\n"
            f"Исполнено: {len([o for o in orders if o.status == 'completed'])}\n"
            f"Отменено: {len([o for o in orders if o.status == 'cancelled'])}\n"
            f"Активных столиков: {len(orders_by_table)}\n\n"
            "📝 <b>Детальный отчет по столикам:</b>\n"
        )
        await message.reply(summary, parse_mode="HTML")

        # Отправляем информацию по каждому столику
        for table, table_orders in sorted(orders_by_table.items()):
            # Собираем информацию о пользователях за столиком
            users = {order.user.display_name for order in table_orders}

            table_info = (
                f"🎯 <b>Столик {table}</b>\n"
                f"👥 Клиенты: {', '.join(users)}\n"
                f"📋 Всего заказов: {len(table_orders)}\n"
                "┌──────────────────────────────────\n"
            )

            # Добавляем информацию о каждом заказе
            for order in table_orders:
                status_emoji = "✅" if order.status == "completed" else "❌"
                backing_emoji = "🎵" if order.has_backing else "🎤"

                order_line = (
                    f"├ {status_emoji} <b>#{order.id}</b> {backing_emoji} "
                    f"{order.song_artist} - {order.song_title}({order.song_id})\n"
                    f"│  ⏰ {moscow_time(order.ordered_at).strftime('%H:%M')} → "
                    f"{moscow_time(order.completed_at).strftime('%H:%M')}\n"
                )
                table_info += order_line

            table_info += "└──────────────────────────────────\n"

            # Добавляем статистику по столику
            completed = len(
                [o for o in table_orders if o.status == "completed"])
            cancelled = len(
                [o for o in table_orders if o.status == "cancelled"])
            table_info += (
                f"✅ Исполнено: {completed}\n"
                f"❌ Отменено: {cancelled}\n"
            )

            await message.reply(table_info, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error in list_completed_orders: {e}")
        await message.reply("❌ Произошла ошибка при получении списка исполненных заказов.")
    finally:
        session.close()


@dp.message(Command("search"))
async def admin_search_command(message: types.Message, state: FSMContext):
    """Команда поиска для администраторов"""
    session = Session()
    admin = session.query(Admin).filter_by(
        telegram_id=message.from_user.id).first()
    session.close()

    if not admin:
        await message.reply("❌ Эта команда доступна только администраторам.")
        return

    await message.reply(
        "Выберите тип поиска:",
        reply_markup=create_search_type_buttons()
    )
    await state.set_state(UserState.ready_to_search)


@dp.message(Command("orders"))
@require_registration
async def list_orders(message: types.Message):
    """Показать список активных заказов"""
    print("list_orders")
    try:
        session = Session()
        admin = session.query(Admin).filter_by(
            telegram_id=message.from_user.id).first()

        if not admin:
            await message.reply("❌ Эта команда доступна только администраторам.")
            return

        orders = session.query(Order).filter_by(status="pending").all()

        if not orders:
            await message.reply(
                "📝 Активных заказов нет",
                parse_mode="HTML"
            )
            return

        for order in orders:
            user = order.user
            order_info = (
                f"🎵 <b>Заказ #{order.id}</b>\n\n"
                f"🎼 <b>Песня:</b> {order.song_title}\n"
                f"👨‍🎤 <b>Исполнитель:</b> {order.song_artist}\n"
                f"ℹ️ <b>ID песни:</b> {order.song_id}\n"
                f"🎹 <b>Тип:</b> {'🎵 С бэк-треком' if order.has_backing else '🎤 Без бэк-трека'}\n\n"
                f"👤 <b>Информация о клиенте:</b>\n"
                f"• Имя: {user.display_name}\n"
                f"• Столик: {user.table_number}\n"
                f"• Username: @{user.username}\n"
                f"• Заказано: {moscow_time(order.ordered_at).strftime('%H:%M:%S')}\n"
                f"• Статус: {ORDER_STATUSES[order.status]}\n\n"
                f"Действия: /complete_{order.id} | /cancel_{order.id}"
            )
            await message.reply(order_info, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error in list_orders: {e}")
        await message.reply("❌ Произошла ошибка при получении списка заказов.")
    finally:
        session.close()


@dp.message(lambda message: message.text and message.text.startswith(('/complete_', '/cancel_')))
@dp.message(Command("orders", "completed"))
async def handle_order_action(message: types.Message):
    """Обработка действий с заказами"""
    try:
        session = Session()
        admin = session.query(Admin).filter_by(
            telegram_id=message.from_user.id).first()

        if not admin:
            await message.reply("❌ Эта команда доступна только администраторам.")
            return

        # Обработка команд complete_ и cancel_
        if message.text.startswith(('/complete_', '/cancel_')):
            try:
                action, order_id = message.text.split('_')
                order_id = int(order_id)
                order = session.query(Order).filter_by(id=order_id).first()

                if not order:
                    await message.reply(f"❌ Заказ #{order_id} не найден.")
                    return

                # Проверяем, не обработан ли уже заказ
                if order.status != "pending":
                    await message.reply(
                        f"❌ Заказ #{order_id} уже обработан.\n"
                        f"Текущий статус: {ORDER_STATUSES[order.status]}"
                    )
                    return

                # Обновляем статус заказа
                order.status = "completed" if action == "/complete" else "cancelled"
                order.completed_at = datetime.now(timezone.utc)
                session.commit()

                # Отправляем подтверждение администратору
                status_text = "✅ исполнен" if action == "/complete" else "❌ отменен"
                await message.reply(f"Заказ #{order_id} {status_text}.")

                # Отправляем уведомление клиенту
                user_notification = (
                    f"🎵 <b>Обновление статуса заказа #{order.id}</b>\n\n"
                    f"Песня: {order.song_title}\n"
                    f"Исполнитель: {order.song_artist}\n"
                    f"Статус: {ORDER_STATUSES[order.status]}\n"
                    f"Время: {moscow_time(order.completed_at).strftime('%H:%M:%S')}"
                    "\n"
                )
                user_notification += "Вы прекрасно поёте" if order.status == "completed" else "Жаль, что мы не услышим ваше прекрасное пение"
                try:
                    await bot.send_message(
                        order.user_id,
                        user_notification,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(
                        f"Error sending notification to user {order.user_id}: {e}")
                    await message.reply(
                        "⚠️ Заказ обработан, но не удалось отправить уведомление клиенту."
                    )

            except ValueError:
                await message.reply("❌ Неверный формат команды.")
                return

        # Обработка команды /orders
        elif message.text == "/orders":
            # Получаем только активные (pending) заказы
            orders = session.query(Order).filter_by(
                status="pending"
            ).order_by(Order.ordered_at.desc()).all()

            if not orders:
                await message.reply("📝 Нет активных заказов.")
                return

            await message.reply(
                "📋 <b>Список активных заказов:</b>",
                parse_mode="HTML"
            )

            # Отправляем информацию о каждом заказе
            for order in orders:
                user = order.user
                order_info = (
                    f"🎵 <b>Заказ #{order.id}</b>\n"
                    f"🎼 <b>Песня:</b> {order.song_title}\n"
                    f"👨‍🎤 <b>Исполнитель:</b> {order.song_artist}\n"
                    f"🎹 <b>Тип:</b> {'🎵 С бэк-треком' if order.has_backing else '🎤 Без бэк-трека'}\n"
                    f"👤 <b>Клиент:</b> {user.display_name} (Столик: {user.table_number})\n"
                    f"⏰ <b>Заказано:</b> {moscow_time(order.ordered_at).strftime('%H:%M:%S')}\n\n"
                    f"Действия:\n"
                    f"/complete_{order.id} - отметить как исполненный\n"
                    f"/cancel_{order.id} - отменить заказ"
                )
                await message.reply(order_info, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error in handle_order_action: {e}")
        await message.reply("❌ Произошла ошибка при обработке команды.")
    finally:
        session.close()


@dp.callback_query(lambda c: c.data.startswith('page_'))
async def process_pagination(callback_query: CallbackQuery, state: FSMContext):
    """Обработка навигации по страницам"""
    print("process_pagination")
    try:
        page = int(callback_query.data.split('_')[1])

        # Получаем сохраненные результаты поиска
        data = await state.get_data()
        songs = data.get('search_results')

        if not songs:
            await callback_query.answer("Результаты поиска устарели. Выполните новый поис.")
            return

        keyboard = create_song_buttons(songs, page)

        await callback_query.message.edit_reply_markup(
            reply_markup=keyboard
        )
        await callback_query.answer()

    except Exception as e:
        logger.error(f"Error in process_pagination: {e}")
        await callback_query.answer("Произошла ошибка при навигации.")


@dp.callback_query(lambda c: c.data == 'ignore')
async def process_ignore(callback_query: CallbackQuery):
    """Обработка нажатия на счетчик страниц"""
    print("process_ignore")
    await callback_query.answer()


@dp.callback_query(lambda c: c.data == "exit_search")
async def process_exit_search(callback_query: CallbackQuery, state: FSMContext):
    """Обработка выхода из поиска"""
    print("process_exit_search")
    try:
        session = Session()
        admin = session.query(Admin).filter_by(
            telegram_id=callback_query.from_user.id).first()

        if admin:
            await callback_query.message.edit_text(
                "Поиск завершен.\n\n"
                "Доступные команды:\n"
                "/orders - просмотр активных заказов\n"
                "/completed - просмотр исполненных заказов\n"
                "/search - поиск песен\n"
                "/new_admin - добавить нового администратора"
            )
        else:
            await callback_query.message.edit_text(
                "Поиск завершен. Выберите тип поиска:",
                reply_markup=create_search_type_buttons()
            )
            await state.set_state(UserState.ready_to_search)

        await state.clear()
        await callback_query.answer()

    except Exception as e:
        logger.error(f"Error in process_exit_search: {e}")
        await callback_query.answer("Произошла ошибка при выходе из поиска.")
    finally:
        session.close()


@dp.message()
async def handle_unknown_message(message: types.Message, state: FSMContext):
    """Обработка всех необработанных сообщений"""
    print("handle_unknown_message")
    try:
        session = Session()

        # Проверяем, является ли пользователь администратором
        admin = session.query(Admin).filter_by(
            telegram_id=message.from_user.id).first()

        if admin:
            await message.reply(
                "Доступные команды:\n"
                "/orders - просмотр активных заказов\n"
                "/completed - просмотр исполненных заказов\n"
                "/search - поиск песен\n"
                "/new_admin - добавить нового администратора"
            )
            return

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
                    "Выберите тип поиска:\n\n"
                    "💡 Используйте /reset для сброса регистрации",
                    reply_markup=create_search_type_buttons()
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
    """Зпуск бота"""
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

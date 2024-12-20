from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, StateFilter
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

load_dotenv()

# Конфигурация
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = "http://localhost:8000"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

# Статусы заказов
ORDER_STATUSES = {
    "pending": "⏳ Ожидает исполнения",
    "completed": "✅ Исполнена",
    "cancelled": "❌ Отменена"
}


def moscow_time(dt: datetime) -> datetime:
    """Конвертация времени в московское"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    moscow_tz = timezone(timedelta(hours=3))  # UTC+3 для Москвы
    return dt.astimezone(moscow_tz)


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


def create_song_buttons(songs: List[Dict]) -> InlineKeyboardMarkup:
    """Создание клавиатуры с кнопками песен"""
    keyboard = []
    for song in songs[:10]:
        backing = "🎵" if song.get("has_backing") else "🎤"
        button_text = f"{backing} {song['artist']} - {song['title']}"
        callback_data = f"song_{song['id']}"
        keyboard.append([InlineKeyboardButton(
            text=button_text, callback_data=callback_data)])
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


@dp.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    """Обработка команды /start"""
    try:
        session = Session()
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


@dp.message(Command("new_admin"))
async def new_admin_command(message: types.Message, state: FSMContext):
    """Обработка команды /new_admin"""
    await message.reply("Пожалуйста, введите пароль администратора:")
    await state.set_state(UserState.waiting_for_admin_password)


@dp.message(StateFilter(UserState.waiting_for_admin_password))
async def process_admin_password(message: types.Message, state: FSMContext):
    """Обработка ввода пароля администратора"""
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
            "Тепеь введите название песни или исполнителя для поиска:"
        )
        await state.set_state(UserState.ready_to_search)

    except SQLAlchemyError as e:
        logger.error(f"Database error in process_table: {e}")
        await message.reply("Произошла ошибка при сохранении данных. Пожалуйста, попробуйте еще раз.")
    except Exception as e:
        logger.error(f"Error in process_table: {e}")
        await message.reply("Произошла ошибк��. Пожалуйста, попробуйте еще раз.")
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
        await message.reply(
            "Введите новый запрос для поиска, если хотите продолжить."
        )

    except Exception as e:
        logger.error(f"Error in process_search: {e}")
        await message.reply(
            "Произошла ошибка при поиске. Пожалуйста, попробуйте еще раз или используйте другой запрос."
        )
        await notify_admins(f"Произошла ошибка в процессе поиска: {e}")
    finally:
        session.close()


@dp.callback_query(lambda c: c.data.startswith('song_'))
async def process_song_selection(callback_query: CallbackQuery):
    """Обработка выбора песни"""
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
async def process_order(callback_query: CallbackQuery):
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
                has_backing=song.has_backing
            )
            session.add(order)
            session.commit()

            backing_status = "🎵 С бэк-треком" if song.has_backing else "🎤 Без бэк-трека"
            order_info = (
                f"🎵 <b>Новый заказ песни! (ID: {order.id})</b>\n\n"
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
            await notify_admins(order_info)
            await callback_query.message.reply(
                "✅ Ваш заказ отправлен!\n"
                "Введите новый запрос для поиска песни.",
                parse_mode="HTML"
            )
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
async def process_find_another(callback_query: CallbackQuery):
    """Обработка нажатия 'Найти другую'"""
    try:
        await callback_query.message.reply(
            "Введите новый запрос для поиска."
        )
        await callback_query.answer()
    except Exception as e:
        logger.error(f"Error in process_find_another: {e}")
        await callback_query.message.reply("Произошла ошибка. Пожалуйста, попробуйте еще раз.")


async def notify_admins(message_text: str):
    """Отправка сообщения всем администраторам"""
    try:
        session = Session()
        admins = session.query(Admin).all()
        for admin in admins:
            try:
                await bot.send_message(
                    admin.telegram_id,
                    message_text,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(
                    f"Error sending message to admin {admin.telegram_id}: {e}")
    except SQLAlchemyError as e:
        logger.error(f"Database error in notify_admins: {e}")
    finally:
        session.close()


@dp.message(Command("orders"))
async def list_orders(message: types.Message):
    """Показать список активных заказов"""
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
                f"⏰ Заказано: {moscow_time(order.ordered_at).strftime('%H:%M:%S')}\n"
                f"• Статус: {ORDER_STATUSES[order.status]}\n\n"
                f"Действия: /complete_{order.id} | /cancel_{order.id}"
            )
            await message.reply(order_info, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error in list_orders: {e}")
        await message.reply("❌ Произошла ошибка при получении списка заказов.")
    finally:
        session.close()


@dp.message(lambda message: message.text and message.text.startswith(("/complete_", "/cancel_")))
async def handle_order_action(message: types.Message):
    """Обработка действий с заказами"""
    try:
        session = Session()
        admin = session.query(Admin).filter_by(
            telegram_id=message.from_user.id).first()

        if not admin:
            await message.reply("❌ Эта команда доступна только администраторам.")
            return

        action, order_id = message.text.split("_")
        order = session.query(Order).filter_by(id=int(order_id)).first()

        if not order:
            await message.reply("❌ Заказ не найден.")
            return

        if action == "/complete":
            order.status = "completed"
            order.completed_at = datetime.now(timezone.utc)
            status_text = ORDER_STATUSES["completed"]
        else:
            order.status = "cancelled"
            order.completed_at = datetime.now(timezone.utc)
            status_text = ORDER_STATUSES["cancelled"]

        session.commit()

        # Уведомляем пользователя о статусе заказа
        user_notification = (
            f"{status_text}!\n"
            f"Песня: {order.song_title} - {order.song_artist}\n"
            f"Время: {moscow_time(order.completed_at).strftime('%H:%M:%S')}"
        )
        await bot.send_message(order.user_id, user_notification, parse_mode="HTML")
        await message.reply(f"{status_text} (ID: {order.id})")

    except Exception as e:
        logger.error(f"Error in handle_order_action: {e}")
        await message.reply("❌ Произошла ошибка при о��работке действия.")
    finally:
        session.close()


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

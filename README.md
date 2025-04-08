# Karaoke Bar Bot

Телеграм бот для караоке-бара с возможностью поиска и заказа песен.

## Функциональность

- 🔍 Поиск песен по названию и исполнителю
- 🎵 Заказ песен через бота
- 👤 Регистрация пользователей с привязкой к столику
- 👨‍💼 Административная панель для управления заказами
- 📊 История заказов пользователей
- 🎤 Информация о наличии бэка для каждой песни

## Технологии

- Python 3.11
- FastAPI
- SQLite
- aiogram 3.x
- Docker

## Требования

- Docker и Docker Compose
- Telegram Bot Token
- Python 3.11 (для локальной разработки)

## Установка и запуск

### Через Docker (рекомендуется)

1. Клонируйте репозиторий:
```bash
git clone <repository-url>
cd karaoke-bar
```

2. Создайте файл `.env` со следующими переменными:
```env
TELEGRAM_TOKEN=your_telegram_bot_token
ADMIN_PASSWORD=your_admin_password
```

3. Запустите контейнер:
```bash
docker-compose up --build
```

4. Для запуска в фоновом режиме:
```bash
docker-compose up -d --build
```

### Локальная установка

1. Создайте виртуальное окружение:
```bash
python -m venv venv
source venv/bin/activate  # для Linux/Mac
# или
.\venv\Scripts\activate  # для Windows
```

2. Установите зависимости:
```bash
pip install -r requirements.txt
```

3. Запустите приложение:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8009 & python -m app.bot
```

## Структура проекта

```
.
├── app/
│   ├── bot/           # Код телеграм бота
│   ├── main.py        # FastAPI приложение
│   └── utils.py       # Вспомогательные функции
├── songs.csv          # База песен
├── karaoke_bot.db     # База данных SQLite
├── user_searches.log  # Лог поисковых запросов
├── .env              # Переменные окружения
└── requirements.txt   # Зависимости проекта
```

## API Endpoints

- `GET /songs/` - список всех песен
- `GET /songs/search/` - поиск песен
- `GET /songs/by-artist/` - поиск по исполнителю
- `GET /songs/with-backing/` - песни с бэком
- `GET /songs/by-title/` - поиск по названию

## Команды бота

- `/start` - регистрация пользователя
- `/search` - поиск песен
- `/history` - история заказов
- `/orders` - текущие заказы
- `/reset` - сброс регистрации
- `/new_admin` - регистрация администратора

## Разработка

1. Убедитесь, что у вас установлены все зависимости:
```bash
pip install -r requirements.txt
```

2. Запустите тесты:
```bash
pytest
```

3. Для разработки с hot-reload:
```bash
uvicorn app.main:app --reload & python -m app.bot
```

## Лицензия

MIT License

import logging
import os
import asyncio
import aiohttp
import json
import pytz
from datetime import datetime, timedelta
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    BotCommand,
    ChatMember
)
from telegram.constants import ParseMode
from telegram.error import Forbidden, BadRequest
from telegram.ext import (
    Application, 
    CommandHandler, 
    ContextTypes, 
    CallbackQueryHandler
)
from quart import Quart, request, Response
import psycopg
from psycopg.rows import dict_row
from io import BytesIO

# TOKEN из переменных окружения Render
TOKEN = os.environ.get("TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")  # Строка подключения к Neon.tech
CREATOR_ID = int(os.environ.get("CREATOR_ID", "7106925462"))  # ID создателя бота

# Настройки канала
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-1002699957973"))  # ID вашего канала
CHANNEL_LINK = os.environ.get("CHANNEL_LINK", "https://t.me/+57Wq6w2wbYhkNjYy")
WEBHOOK_PATH = "webhook"

# URL для самопинга (замените на ваш актуальный URL)
SELF_PING_URL = "https://miaphotoroom.onrender.com"
PING_INTERVAL = 600  # 10 минут

# Настройки логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальная переменная для задачи пинга
ping_task = None
cleanup_task = None  # Для периодической очистки данных

# --- Функции для работы с базой данных Neon.tech ---
async def create_tables():
    """Создает таблицы в базе данных, если они не существуют"""
    try:
        async with await psycopg.AsyncConnection.connect(
            DATABASE_URL, 
            row_factory=dict_row
        ) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT,
                        country_code TEXT,
                        device_type TEXT,
                        start_time TIMESTAMP DEFAULT NOW()
                    );
                    
                    CREATE TABLE IF NOT EXISTS events (
                        event_id SERIAL PRIMARY KEY,
                        user_id BIGINT REFERENCES users(user_id),
                        event_type TEXT,
                        event_time TIMESTAMP DEFAULT NOW()
                    );
                    
                    CREATE TABLE IF NOT EXISTS channel_joins (
                        join_id SERIAL PRIMARY KEY,
                        user_id BIGINT REFERENCES users(user_id),
                        join_time TIMESTAMP DEFAULT NOW(),
                        UNIQUE(user_id)
                    );
                ''')
        logger.info("✅ Таблицы в базе данных созданы/проверены")
    except Exception as e:
        logger.error(f"❌ Ошибка создания таблиц: {e}")
        raise

async def clean_old_data():
    """Очищает старые данные (старше 1 недели)"""
    try:
        one_week_ago = datetime.utcnow() - timedelta(days=7)
        
        async with await psycopg.AsyncConnection.connect(
            DATABASE_URL, 
            row_factory=dict_row
        ) as conn:
            async with conn.cursor() as cursor:
                # Удаляем старые события
                await cursor.execute('''
                    DELETE FROM events 
                    WHERE event_time < %s
                ''', (one_week_ago,))
                
                # Удаляем старые вступления в канал
                await cursor.execute('''
                    DELETE FROM channel_joins 
                    WHERE join_time < %s
                ''', (one_week_ago,))
                
        logger.info(f"🧹 Очищены старые данные (старше {one_week_ago})")
    except Exception as e:
        logger.error(f"❌ Ошибка очистки старых данных: {e}")

async def save_user(user):
    """Сохраняет или обновляет пользователя в базе данных"""
    try:
        async with await psycopg.AsyncConnection.connect(
            DATABASE_URL, 
            row_factory=dict_row
        ) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    INSERT INTO users (user_id, username, first_name, last_name)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        username = EXCLUDED.username,
                        first_name = EXCLUDED.first_name,
                        last_name = EXCLUDED.last_name
                ''', (user.id, user.username, user.first_name, user.last_name))
                
        logger.info(f"👤 Пользователь {user.id} сохранен/обновлен в БД")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения пользователя {user.id}: {e}")

async def log_event(user_id, event_type):
    """Логирует событие в базе данных"""
    try:
        async with await psycopg.AsyncConnection.connect(
            DATABASE_URL, 
            row_factory=dict_row
        ) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    INSERT INTO events (user_id, event_type)
                    VALUES (%s, %s)
                ''', (user_id, event_type))
                
        logger.info(f"📝 Событие '{event_type}' для {user_id} записано в БД")
    except Exception as e:
        logger.error(f"❌ Ошибка записи события: {e}")

async def log_channel_join(user_id):
    """Логирует вступление пользователя в канал"""
    try:
        async with await psycopg.AsyncConnection.connect(
            DATABASE_URL, 
            row_factory=dict_row
        ) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    INSERT INTO channel_joins (user_id)
                    VALUES (%s)
                    ON CONFLICT (user_id) DO NOTHING
                ''', (user_id,))
                
        logger.info(f"✅ Пользователь {user_id} вступил в канал")
    except Exception as e:
        logger.error(f"❌ Ошибка записи вступления в канал: {e}")

async def is_user_joined(user_id):
    """Проверяет, вступил ли пользователь в канал"""
    try:
        async with await psycopg.AsyncConnection.connect(
            DATABASE_URL, 
            row_factory=dict_row
        ) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    SELECT EXISTS(SELECT 1 FROM channel_joins WHERE user_id = %s)
                ''', (user_id,))
                result = await cursor.fetchone()
                return result[0] if result else False
    except Exception as e:
        logger.error(f"❌ Ошибка проверки подписки: {e}")
        return False

async def get_basic_stats():
    """Возвращает базовую статистику"""
    stats = {
        "total_users": 0,
        "active_users_week": 0,
        "channel_joins_week": 0
    }
    try:
        one_week_ago = datetime.utcnow() - timedelta(days=7)
        
        async with await psycopg.AsyncConnection.connect(
            DATABASE_URL, 
            row_factory=dict_row
        ) as conn:
            async with conn.cursor() as cursor:
                # Общее количество пользователей
                await cursor.execute('SELECT COUNT(*) FROM users')
                stats['total_users'] = (await cursor.fetchone())['count']
                
                # Активные пользователи за неделю
                await cursor.execute(
                    "SELECT COUNT(DISTINCT user_id) AS count FROM events "
                    "WHERE event_time >= %s",
                    (one_week_ago,)
                )
                stats['active_users_week'] = (await cursor.fetchone())['count']
                
                # Вступления в канал за неделю
                await cursor.execute(
                    "SELECT COUNT(*) AS count FROM channel_joins "
                    "WHERE join_time >= %s",
                    (one_week_ago,)
                )
                stats['channel_joins_week'] = (await cursor.fetchone())['count']
                
        return stats
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики: {e}")
    return stats

async def get_geo_stats():
    """Возвращает статистику по странам (уникальные пользователи)"""
    try:
        async with await psycopg.AsyncConnection.connect(
            DATABASE_URL, 
            row_factory=dict_row
        ) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    SELECT country_code, COUNT(*) AS user_count
                    FROM users
                    WHERE country_code IS NOT NULL
                    GROUP BY country_code
                    ORDER BY user_count DESC
                ''')
                result = await cursor.fetchall()
                return {row['country_code']: row['user_count'] for row in result}
    except Exception as e:
        logger.error(f"❌ Ошибка получения гео-статистики: {e}")
        return {}

async def get_device_stats():
    """Возвращает статистику по устройствам (уникальные пользователи)"""
    try:
        async with await psycopg.AsyncConnection.connect(
            DATABASE_URL, 
            row_factory=dict_row
        ) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    SELECT device_type, COUNT(*) AS user_count
                    FROM users
                    WHERE device_type IS NOT NULL
                    GROUP BY device_type
                    ORDER BY user_count DESC
                ''')
                result = await cursor.fetchall()
                return {row['device_type']: row['user_count'] for row in result}
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики устройств: {e}")
        return {}

async def get_time_stats():
    """Возвращает статистику по времени активности (уникальные пользователи)"""
    try:
        one_week_ago = datetime.utcnow() - timedelta(days=7)
        local_tz = pytz.timezone('Europe/Moscow')  # Замените на нужный часовой пояс
        
        async with await psycopg.AsyncConnection.connect(
            DATABASE_URL, 
            row_factory=dict_row
        ) as conn:
            async with conn.cursor() as cursor:
                # Статистика по часам (в локальном времени)
                await cursor.execute('''
                    SELECT EXTRACT(HOUR FROM event_time AT TIME ZONE 'UTC' AT TIME ZONE %s) AS hour, 
                           COUNT(DISTINCT user_id) AS user_count
                    FROM events
                    WHERE event_time >= %s
                    GROUP BY hour
                    ORDER BY hour
                ''', (local_tz.zone, one_week_ago))
                hourly_stats = await cursor.fetchall()
                
                # Статистика по дням недели (в локальном времени)
                await cursor.execute('''
                    SELECT EXTRACT(DOW FROM event_time AT TIME ZONE 'UTC' AT TIME ZONE %s) AS day, 
                           COUNT(DISTINCT user_id) AS user_count
                    FROM events
                    WHERE event_time >= %s
                    GROUP BY day
                    ORDER BY day
                ''', (local_tz.zone, one_week_ago))
                daily_stats = await cursor.fetchall()
        
        return {
            "hourly": {int(row['hour']): row['user_count'] for row in hourly_stats},
            "daily": {int(row['day']): row['user_count'] for row in daily_stats}
        }
    except Exception as e:
        logger.error(f"❌ Ошибка получения временной статистики: {e}")
        return {"hourly": {}, "daily": {}}

async def get_full_stats():
    """Возвращает полную статистику для экспорта"""
    try:
        async with await psycopg.AsyncConnection.connect(
            DATABASE_URL, 
            row_factory=dict_row
        ) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT * FROM users")
                users = await cursor.fetchall()
                
                await cursor.execute("SELECT * FROM events")
                events = await cursor.fetchall()
                
                await cursor.execute("SELECT * FROM channel_joins")
                joins = await cursor.fetchall()
        
        return {
            "users": users,
            "events": events,
            "channel_joins": joins
        }
    except Exception as e:
        logger.error(f"❌ Ошибка получения полной статистики: {e}")
        return {}

async def setup_menu(application: Application):
    """Устанавливает меню команд в боте"""
    commands = [
        BotCommand("start", "Начать работу с ботом"),
        BotCommand("help", "Помощь по использованию бота"),
        BotCommand("channel", "Получить доступ к каналу"),
        BotCommand("check", "Проверить подписку на канал"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Меню команд установлено")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команду /start"""
    user = update.effective_user
    logger.info(f"Received /start command from user {user.id}")
    
    # Сохраняем/обновляем пользователя в БД
    await save_user(user)
    await log_event(user.id, 'start')
    
    # Создаем клавиатуру с кнопками
    keyboard = [
        [InlineKeyboardButton("Перейти в канал", url=CHANNEL_LINK)],
        [InlineKeyboardButton("✅ Проверить подписку", callback_data='check_subscription')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await update.message.reply_html(
            f"Привет, {user.mention_html()}! Чтобы получить доступ к нашему закрытому каналу, "
            "пожалуйста, подпишись на него по ссылке ниже, а затем нажми кнопку для проверки.",
            reply_markup=reply_markup
        )
        logger.info(f"Sent /start response to user {user.id}")
    except Exception as e:
        logger.error(f"Error sending /start response to user {user.id}: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команду /help"""
    help_text = (
        "🤖 <b>Команды бота:</b>\n\n"
        "/start - Начать работу с ботом\n"
        "/help - Показать эту справку\n"
        "/channel - Получить доступ к каналу\n"
        "/check - Проверить подписку на канал\n"
        "\n"
        "После подписки на канал нажмите кнопку <b>«Проверить подписку»</b>, "
        "чтобы получить доступ к контенту."
    )
    await update.message.reply_html(help_text)

async def channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команду /channel"""
    keyboard = [
        [InlineKeyboardButton("Перейти в канал", url=CHANNEL_LINK)],
        [InlineKeyboardButton("✅ Проверить подписку", callback_data='check_subscription')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Подпишись на наш канал, затем нажми кнопку для проверки:",
        reply_markup=reply_markup
    )

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команду /check"""
    await check_subscription(update, context)

async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Проверяет подписку пользователя на канал"""
    query = update.callback_query
    if query:
        await query.answer()
        user = query.from_user
        message = query.message
    else:
        user = update.effective_user
        message = update.message
    
    logger.info(f"Checking subscription for user {user.id}")
    
    # Обновляем информацию о пользователе
    await save_user(user)
    await log_event(user.id, 'subscription_check')
    
    try:
        # Проверяем подписку
        chat_member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user.id)
        is_member = chat_member.status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]
        
        if is_member:
            # Логируем вступление
            await log_channel_join(user.id)
            await log_event(user.id, 'channel_join')
            
            # Отправляем сообщение с предложением поделиться ссылкой
            response_text = (
                f"🎉 Отлично, {user.mention_html()}! Ты подписан на наш канал.\n\n"
                "Можешь поделиться ссылкой с друзьями:\n"
                f"👉 {CHANNEL_LINK}\n\n"
                "Приглашай друзей - вместе интереснее!"
            )
            
            # Обновляем сообщение с кнопкой
            if query:
                await query.edit_message_text(
                    text=response_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=None
                )
            else:
                await message.reply_html(response_text)
        else:
            response_text = (
                f"❌ {user.mention_html()}, ты еще не подписан на наш канал.\n\n"
                "Пожалуйста, подпишись по ссылке ниже и нажми кнопку проверки снова."
            )
            
            # Создаем клавиатуру с кнопкой
            keyboard = [
                [InlineKeyboardButton("Перейти в канал", url=CHANNEL_LINK)],
                [InlineKeyboardButton("✅ Проверить подписку", callback_data='check_subscription')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if query:
                await query.edit_message_text(
                    text=response_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
            else:
                await message.reply_html(
                    response_text,
                    reply_markup=reply_markup
                )
    
    except Forbidden as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        error_text = (
            "⚠️ Недостаточно прав для проверки подписки.\n\n"
            "Пожалуйста, убедитесь, что бот:\n"
            "1. Добавлен как участник канала\n"
            "2. Имеет право 'Публикация сообщений' в настройках администратора канала"
        )
        if query:
            await query.edit_message_text(error_text)
        else:
            await message.reply_text(error_text)
    
    except BadRequest as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        error_text = "⚠️ Ошибка конфигурации бота. Пожалуйста, сообщите администратору."
        if query:
            await query.edit_message_text(error_text)
        else:
            await message.reply_text(error_text)
    
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        error_text = (
            "⚠️ Произошла неизвестная ошибка при проверке подписки. "
            "Пожалуйста, попробуйте позже."
        )
        if query:
            await query.edit_message_text(error_text)
        else:
            await message.reply_text(error_text)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет статистику создателю бота"""
    user = update.effective_user
    
    # Проверяем права доступа
    if user.id != CREATOR_ID:
        await update.message.reply_text("⛔ У вас нет прав для выполнения этой команды.")
        return
    
    # Получаем статистику из БД
    basic_stats = await get_basic_stats()
    geo_stats = await get_geo_stats()
    device_stats = await get_device_stats()
    time_stats = await get_time_stats()
    full_stats = await get_full_stats()
    
    # Форматируем гео-статистику
    geo_text = "\n".join([f"  - {country}: {count}" for country, count in geo_stats.items()]) or "  Нет данных"
    
    # Форматируем статистику устройств
    device_text = "\n".join([f"  - {device}: {count}" for device, count in device_stats.items()]) or "  Нет данных"
    
    # Форматируем временную статистику
    peak_hour = max(time_stats.get('hourly', {}).items(), key=lambda x: x[1], default=(0, 0))
    peak_day = max(time_stats.get('daily', {}).items(), key=lambda x: x[1], default=(0, 0))
    
    # Дни недели для удобства
    weekdays = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    
    # Локальное время для отображения
    local_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    message = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👤 <u>Пользователи</u>\n"
        f"  Всего: <b>{basic_stats['total_users']}</b>\n"
        f"  Активных за неделю: <b>{basic_stats['active_users_week']}</b>\n"
        f"  Подписались на канал: <b>{basic_stats['channel_joins_week']}</b>\n\n"
        f"🗺️ <u>География (уникальные пользователи)</u>\n{geo_text}\n\n"
        f"📱 <u>Устройства (уникальные пользователи)</u>\n{device_text}\n\n"
        f"⏱ <u>Активность (уникальные пользователи)</u>\n"
        f"  Пиковый час: <b>{int(peak_hour[0])}:00</b> ({peak_hour[1]} пользователей)\n"
        f"  Самый активный день: <b>{weekdays[int(peak_day[0])]}</b> ({peak_day[1]} пользователей)\n\n"
        f"🕒 Последнее обновление: {local_time}"
    )
    
    try:
        # Отправляем текстовую статистику
        await update.message.reply_html(message)
        
        # Отправляем файл с полной статистикой
        stats_json = json.dumps(full_stats, indent=2, default=str, ensure_ascii=False)
        await update.message.reply_document(
            document=BytesIO(stats_json.encode('utf-8')),
            filename='bot_stats.json',
            caption="Полная статистика"
        )
        logger.info(f"Sent stats to creator {user.id}")
    except Exception as e:
        logger.error(f"Error sending stats: {e}")
        await update.message.reply_text(f"Ошибка при формировании статистики: {e}")

async def self_ping():
    """Функция для самопинга сервера"""
    while True:
        try:
            await asyncio.sleep(PING_INTERVAL)
            
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                logger.info(f"📡 Отправляем самопинг в {timestamp}")
                
                async with session.get(f"{SELF_PING_URL}/") as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"✅ Самопинг успешен: {data.get('status', 'OK')}")
                    else:
                        logger.warning(f"⚠️ Самопинг вернул статус {response.status}")
                        
        except asyncio.CancelledError:
            logger.info("🛑 Самопинг остановлен")
            break
        except Exception as e:
            logger.error(f"❌ Ошибка самопинга: {e}")

async def periodic_cleanup():
    """Периодическая очистка старых данных"""
    while True:
        try:
            # Очищаем раз в день
            await asyncio.sleep(24 * 60 * 60)  # 24 часа
            await clean_old_data()
        except asyncio.CancelledError:
            logger.info("🛑 Очистка данных остановлена")
            break
        except Exception as e:
            logger.error(f"❌ Ошибка при очистке данных: {e}")

# --- Настройка объекта Application из python-telegram-bot ---
if not TOKEN:
    logger.error("Error: Bot TOKEN not found in environment variables!")
    raise ValueError("Bot TOKEN not set")

logger.info("Creating Application object...")
telegram_application = Application.builder().token(TOKEN).build()
logger.info("Application object created.")

logger.info("Adding command handlers...")
telegram_application.add_handler(CommandHandler("start", start))
telegram_application.add_handler(CommandHandler("help", help_command))
telegram_application.add_handler(CommandHandler("channel", channel_command))
telegram_application.add_handler(CommandHandler("check", check_command))
telegram_application.add_handler(CommandHandler("stats", stats_command))
telegram_application.add_handler(CallbackQueryHandler(check_subscription, pattern='^check_subscription$'))
logger.info("Command handlers added.")

# --- Настройка Quart приложения (ASGI совместимый) ---
app = Quart(__name__)
logger.info("Quart app created.")

# Флаг для отслеживания инициализации Application
is_application_initialized = False

@app.before_serving
async def startup():
    """Запускается при старте приложения"""
    global ping_task, cleanup_task
    
    # Инициализация базы данных
    logger.info("🚀 Инициализация базы данных...")
    await create_tables()
    logger.info("✅ База данных готова")
    
    # Очистка старых данных при запуске
    logger.info("🧹 Первоначальная очистка старых данных...")
    await clean_old_data()
    
    logger.info("🚀 Запуск самопинга...")
    ping_task = asyncio.create_task(self_ping())
    
    logger.info("🚀 Запуск периодической очистки данных...")
    cleanup_task = asyncio.create_task(periodic_cleanup())
    
    # Устанавливаем меню команд
    logger.info("Устанавливаем меню команд...")
    await setup_menu(telegram_application)

@app.after_serving
async def shutdown():
    """Запускается при остановке приложения"""
    global ping_task, cleanup_task
    
    if ping_task:
        logger.info("🛑 Остановка самопинга...")
        ping_task.cancel()
        try:
            await ping_task
        except asyncio.CancelledError:
            pass
    
    if cleanup_task:
        logger.info("🛑 Остановка очистки данных...")
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass

@app.route(f"/{WEBHOOK_PATH}", methods=["POST"])
async def telegram_webhook_handler():
    """Обрабатывает входящие запросы от Телеграма."""
    global is_application_initialized
    logger.info("Received POST request on /webhook")

    # Инициализируем Application, если это еще не сделано
    if not is_application_initialized:
        logger.info("Initializing Application...")
        try:
            await telegram_application.initialize()
            is_application_initialized = True
            logger.info("Application initialized.")
        except Exception as e:
            logger.error(f"Error during Application initialization: {e}")
            return Response(status=500)

    update_json = await request.get_json()
    if not update_json:
        logger.warning("Received empty webhook request")
        return Response(status=400)

    logger.info("Received update JSON, attempting to parse...")
    try:
        update = Update.de_json(update_json, telegram_application.bot)
        logger.info(f"Update parsed: {update.update_id}")
    except Exception as e:
         logger.error(f"Error parsing update JSON: {e}")
         return Response(status=400)

    # --- Передаем обновление Application для обработки ---
    logger.info(f"Processing update {update.update_id} using application.process_update...")
    try:
        await telegram_application.process_update(update)
        logger.info(f"Update {update.update_id} processing finished.")
    except Exception as e:
        logger.error(f"Error processing update {update.update_id} in Application: {e}")
        pass

    # Возвращаем ответ Телеграму
    logger.info("Returning 200 OK to Telegram")
    return Response(status=200)

# Добавляем обработчик для корневого пути
@app.route("/", methods=["GET"])
async def health_check():
    """Проверка состояния сервера."""
    try:
        # Проверяем подключение к базе данных
        async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
            db_status = "connected"
    except Exception as e:
        db_status = f"disconnected: {str(e)}"
    
    stats = await get_basic_stats()
    geo_stats = await get_geo_stats()
    device_stats = await get_device_stats()
    
    return {
        "status": "Bot is running", 
        "webhook_url": f"/{WEBHOOK_PATH}",
        "ping_status": "active" if ping_task and not ping_task.done() else "inactive",
        "database": db_status,
        "timestamp": datetime.now().isoformat(),
        "stats": {
            "total_users": stats.get('total_users', 0),
            "active_users_week": stats.get('active_users_week', 0),
            "channel_joins_week": stats.get('channel_joins_week', 0),
            "countries": geo_stats,
            "devices": device_stats
        }
    }

# Добавляем маршрут для установки webhook
@app.route("/set_webhook", methods=["GET"])
async def set_webhook():
    """Устанавливает webhook для бота."""
    webhook_url = f"{SELF_PING_URL}/webhook"
    
    try:
        # Инициализируем Application если нужно
        global is_application_initialized
        if not is_application_initialized:
            await telegram_application.initialize()
            is_application_initialized = True
        
        # Устанавливаем webhook
        await telegram_application.bot.set_webhook(webhook_url)
        logger.info(f"Webhook set to: {webhook_url}")
        return {"status": "success", "webhook_url": webhook_url}
    except Exception as e:
        logger.error(f"Error setting webhook: {e}")
        return {"status": "error", "error": str(e)}

# Добавляем маршрут для проверки статуса пинга
@app.route("/ping_status", methods=["GET"])
async def ping_status():
    """Возвращает статус пинга"""
    return {
        "ping_active": ping_task and not ping_task.done(),
        "ping_interval": PING_INTERVAL,
        "self_ping_url": SELF_PING_URL,
        "timestamp": datetime.now().isoformat()
    }

# --- Для uvicorn ---
# app уже определен как Quart приложение, которое является ASGI совместимым

logger.info("ASGI application ready.")

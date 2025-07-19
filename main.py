import logging
import os
import asyncio
import aiohttp
import json
import pytz
from datetime import datetime
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    BotCommand,
    ChatMember
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, 
    CommandHandler, 
    ContextTypes, 
    CallbackQueryHandler,
    CallbackContext
)
from quart import Quart, request, Response, jsonify
import asyncpg
from io import BytesIO
import humanize
from collections import defaultdict
import tzlocal

# TOKEN из переменных окружения Render
TOKEN = os.environ.get("TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")  # Строка подключения к Neon.tech
CREATOR_ID = 7106925462  # ID создателя бота

# Настройки канала
CHANNEL_ID = -1002699957973  # ID вашего канала
CHANNEL_LINK = "https://t.me/+57Wq6w2wbYhkNjYy"
WEBHOOK_PATH = "webhook"

# URL для самопинга (замените на ваш актуальный URL)
SELF_PING_URL = "https://my-telegram-webhook-bot.onrender.com"
PING_INTERVAL = 600  # 10 минут

# Настройки логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальная переменная для задачи пинга
ping_task = None

# --- Функции для работы с базой данных Neon.tech ---
async def create_tables():
    """Создает таблицы в базе данных, если они не существуют"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                country_code TEXT,
                start_time TIMESTAMP DEFAULT NOW()
            );
            
            CREATE TABLE IF NOT EXISTS events (
                event_id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                event_type TEXT,
                device_type TEXT,
                event_time TIMESTAMP DEFAULT NOW()
            );
            
            CREATE TABLE IF NOT EXISTS channel_joins (
                join_id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                join_time TIMESTAMP DEFAULT NOW(),
                UNIQUE(user_id)
            );
        ''')
        
        # Добавляем колонки, если они не существуют
        await conn.execute('''
            ALTER TABLE users ADD COLUMN IF NOT EXISTS country_code TEXT;
        ''')
        await conn.execute('''
            ALTER TABLE events ADD COLUMN IF NOT EXISTS device_type TEXT;
        ''')
        
        logger.info("✅ Таблицы в базе данных созданы/проверены")
        await conn.close()
    except Exception as e:
        logger.error(f"❌ Ошибка создания таблиц: {e}")
        raise

async def save_user(user, country_code=None):
    """Сохраняет пользователя в базу данных"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute('''
            INSERT INTO users (user_id, username, first_name, last_name, country_code)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id) DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                country_code = EXCLUDED.country_code
        ''', user.id, user.username, user.first_name, user.last_name, country_code)
        await conn.close()
        logger.info(f"👤 Пользователь {user.id} сохранен в БД")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения пользователя {user.id}: {e}")

async def log_event(user_id, event_type, device_type=None):
    """Логирует событие в базе данных"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute('''
            INSERT INTO events (user_id, event_type, device_type)
            VALUES ($1, $2, $3)
        ''', user_id, event_type, device_type)
        await conn.close()
        logger.info(f"📝 Событие '{event_type}' для {user_id} записано в БД")
    except Exception as e:
        logger.error(f"❌ Ошибка записи события: {e}")

async def log_channel_join(user_id):
    """Логирует вступление пользователя в канал"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute('''
            INSERT INTO channel_joins (user_id)
            VALUES ($1)
            ON CONFLICT (user_id) DO NOTHING
        ''', user_id)
        await conn.close()
        logger.info(f"✅ Пользователь {user_id} вступил в канал")
    except Exception as e:
        logger.error(f"❌ Ошибка записи вступления в канал: {e}")

async def is_user_joined(user_id):
    """Проверяет, вступил ли пользователь в канал"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        joined = await conn.fetchval('''
            SELECT EXISTS(SELECT 1 FROM channel_joins WHERE user_id = $1)
        ''', user_id)
        await conn.close()
        return joined
    except Exception as e:
        logger.error(f"❌ Ошибка проверки подписки: {e}")
        return False

async def get_basic_stats():
    """Возвращает базовую статистику"""
    stats = {
        "total_users": 0,
        "link_clicks": 0,
        "channel_joins": 0
    }
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        stats['total_users'] = await conn.fetchval('SELECT COUNT(*) FROM users')
        stats['link_clicks'] = await conn.fetchval("SELECT COUNT(*) FROM events WHERE event_type = 'link_click'")
        stats['channel_joins'] = await conn.fetchval("SELECT COUNT(*) FROM channel_joins")
        await conn.close()
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики: {e}")
    return stats

async def get_geo_stats():
    """Возвращает статистику по странам"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        result = await conn.fetch('''
            SELECT country_code, COUNT(*) AS count
            FROM users
            WHERE country_code IS NOT NULL
            GROUP BY country_code
            ORDER BY count DESC
        ''')
        await conn.close()
        return {row['country_code']: row['count'] for row in result}
    except Exception as e:
        logger.error(f"❌ Ошибка получения гео-статистики: {e}")
        return {}

async def get_device_stats():
    """Возвращает статистику по устройствам"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        result = await conn.fetch('''
            SELECT device_type, COUNT(*) AS count
            FROM events
            WHERE device_type IS NOT NULL
            GROUP BY device_type
            ORDER BY count DESC
        ''')
        await conn.close()
        return {row['device_type']: row['count'] for row in result}
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики устройств: {e}")
        return {}

async def get_time_stats():
    """Возвращает статистику по времени активности"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Статистика по часам
        hourly_stats = await conn.fetch('''
            SELECT EXTRACT(HOUR FROM event_time AT TIME ZONE 'UTC') AS hour, COUNT(*) AS count
            FROM events
            GROUP BY hour
            ORDER BY hour
        ''')
        
        # Статистика по дням недели
        daily_stats = await conn.fetch('''
            SELECT EXTRACT(DOW FROM event_time AT TIME ZONE 'UTC') AS day, COUNT(*) AS count
            FROM events
            GROUP BY day
            ORDER BY day
        ''')
        
        await conn.close()
        
        return {
            "hourly": {int(row['hour']): row['count'] for row in hourly_stats},
            "daily": {int(row['day']): row['count'] for row in daily_stats}
        }
    except Exception as e:
        logger.error(f"❌ Ошибка получения временной статистики: {e}")
        return {"hourly": {}, "daily": {}}

async def get_full_stats():
    """Возвращает полную статистику для экспорта"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        users = await conn.fetch("SELECT * FROM users")
        events = await conn.fetch("SELECT * FROM events")
        joins = await conn.fetch("SELECT * FROM channel_joins")
        await conn.close()
        
        return {
            "users": [dict(user) for user in users],
            "events": [dict(event) for event in events],
            "channel_joins": [dict(join) for join in joins]
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
    
    # Определяем страну и устройство
    country_code = None
    if hasattr(user, 'language_code') and user.language_code:
        country_code = user.language_code.split('-')[-1].upper() if '-' in user.language_code else user.language_code.upper()
    
    device_type = "mobile" if update.effective_message and update.effective_message.via_bot else "desktop"
    
    # Сохраняем пользователя в БД
    await save_user(user, country_code)
    await log_event(user.id, 'start', device_type)
    
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
    
    # Определяем устройство
    device_type = "mobile" if message and message.via_bot else "desktop"
    await log_event(user.id, 'subscription_check', device_type)
    
    try:
        # Проверяем подписку
        chat_member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user.id)
        is_member = chat_member.status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]
        
        if is_member:
            # Логируем вступление
            await log_channel_join(user.id)
            await log_event(user.id, 'channel_join', device_type)
            
            # Отправляем приветствие и ссылку
            response_text = (
                f"🎉 Отлично, {user.mention_html()}! Ты подписан на наш канал.\n\n"
                "Теперь ты можешь перейти в канал по этой ссылке:\n"
                f"👉 {CHANNEL_LINK}"
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
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        error_text = (
            "⚠️ Произошла ошибка при проверке подписки. "
            "Убедитесь, что бот добавлен как администратор канала с правом просмотра участников. "
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
    
    message = (
        f"📊 <b>Расширенная статистика бота</b>\n\n"
        f"👤 <u>Пользователи</u>\n"
        f"  Всего: <b>{basic_stats['total_users']}</b>\n"
        f"  Подписались на канал: <b>{basic_stats['channel_joins']}</b>\n"
        f"  Переходов по ссылке: <b>{basic_stats['link_clicks']}</b>\n\n"
        f"🗺️ <u>География</u>\n{geo_text}\n\n"
        f"📱 <u>Устройства</u>\n{device_text}\n\n"
        f"⏱ <u>Активность</u>\n"
        f"  Пиковый час: <b>{int(peak_hour[0])}:00</b> ({peak_hour[1]} действий)\n"
        f"  Самый активный день: <b>{weekdays[int(peak_day[0])]}</b> ({peak_day[1]} действий)\n\n"
        f"🕒 Последнее обновление: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    try:
        # Отправляем текстовую статистику
        await update.message.reply_html(message)
        
        # Отправляем файл с полной статистикой
        stats_json = json.dumps(full_stats, indent=2, default=str, ensure_ascii=False)
        await update.message.reply_document(
            document=BytesIO(stats_json.encode('utf-8')),
            filename='bot_stats.json',
            caption="Полная статистика в JSON"
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
    global ping_task
    
    # Инициализация базы данных
    logger.info("🚀 Инициализация базы данных...")
    await create_tables()
    logger.info("✅ База данных готова")
    
    logger.info("🚀 Запуск самопинга...")
    ping_task = asyncio.create_task(self_ping())
    
    # Устанавливаем меню команд
    logger.info("Устанавливаем меню команд...")
    await setup_menu(telegram_application)

@app.after_serving
async def shutdown():
    """Запускается при остановке приложения"""
    global ping_task
    if ping_task:
        logger.info("🛑 Остановка самопинга...")
        ping_task.cancel()
        try:
            await ping_task
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
        conn = await asyncpg.connect(DATABASE_URL)
        db_status = "connected"
        await conn.close()
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
            "channel_joins": stats.get('channel_joins', 0),
            "link_clicks": stats.get('link_clicks', 0),
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

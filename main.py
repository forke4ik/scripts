import logging
import os
import asyncio
import aiohttp
import json
from datetime import datetime
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from quart import Quart, request, Response
import asyncpg
from asyncpg import Record
from asyncpg.pool import Pool
from io import BytesIO

# TOKEN из переменных окружения Render
TOKEN = os.environ.get("TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")  # Строка подключения к Neon.tech
CREATOR_ID = 7106925462  # ID создателя бота

# Замени на ссылку на твой закрытый канал
CHANNEL_LINK = "https://t.me/+57Wq6w2wbYhkNjYy"
WEBHOOK_PATH = "webhook"

# URL для самопинга (замените на ваш актуальный URL)
SELF_PING_URL = "https://my-telegram-webhook-bot.onrender.com"
PING_INTERVAL = 600  # 10 минут

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
                start_time TIMESTAMP DEFAULT NOW()
            );
            
            CREATE TABLE IF NOT EXISTS events (
                event_id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                event_type TEXT,
                event_time TIMESTAMP DEFAULT NOW()
            );
        ''')
        logger.info("✅ Таблицы в базе данных созданы/проверены")
        await conn.close()
    except Exception as e:
        logger.error(f"❌ Ошибка создания таблиц: {e}")
        raise

async def save_user(user):
    """Сохраняет пользователя в базу данных"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute('''
            INSERT INTO users (user_id, username, first_name, last_name)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id) DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name
        ''', user.id, user.username, user.first_name, user.last_name)
        await conn.close()
        logger.info(f"👤 Пользователь {user.id} сохранен в БД")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения пользователя {user.id}: {e}")

async def log_event(user_id, event_type):
    """Логирует событие в базе данных"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute('''
            INSERT INTO events (user_id, event_type)
            VALUES ($1, $2)
        ''', user_id, event_type)
        await conn.close()
        logger.info(f"📝 Событие '{event_type}' для {user_id} записано в БД")
    except Exception as e:
        logger.error(f"❌ Ошибка записи события: {e}")

async def get_stats():
    """Возвращает статистику из базы данных"""
    stats = {
        "total_users": 0,
        "link_clicks": 0
    }
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        stats['total_users'] = await conn.fetchval('SELECT COUNT(*) FROM users')
        stats['link_clicks'] = await conn.fetchval("SELECT COUNT(*) FROM events WHERE event_type = 'link_click'")
        await conn.close()
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики: {e}")
    return stats

async def get_full_stats():
    """Возвращает полную статистику для экспорта"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        users = await conn.fetch("SELECT * FROM users")
        events = await conn.fetch("SELECT * FROM events")
        await conn.close()
        
        return {
            "users": [dict(user) for user in users],
            "events": [dict(event) for event in events]
        }
    except Exception as e:
        logger.error(f"❌ Ошибка получения полной статистики: {e}")
        return {}

async def setup_menu(application: Application):
    """Устанавливает меню команд в боте"""
    commands = [
        BotCommand("start", "Начать работу с ботом"),
        BotCommand("help", "Помощь по использованию бота"),
        BotCommand("channel", "Получить ссылку на канал"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Меню команд установлено")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команду /start и отправляет ссылку с клавиатурой."""
    user = update.effective_user
    logger.info(f"Received /start command from user {user.id}")
    
    # Сохраняем пользователя в БД
    await save_user(user)
    await log_event(user.id, 'start')
    
    # Создаем клавиатуру с кнопкой
    keyboard = [
        [InlineKeyboardButton("Зайти в канал", url=CHANNEL_LINK)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await update.message.reply_html(
            f"Привет, {user.mention_html()}! Я помогу тебе получить доступ к нашему закрытому каналу.",
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
        "/channel - Получить ссылку на канал\n"
        "\n"
        "Просто нажми на кнопку <b>«Зайти в канал»</b>, чтобы присоединиться к нашему сообществу!"
    )
    await update.message.reply_html(help_text)

async def channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команду /channel"""
    keyboard = [
        [InlineKeyboardButton("Зайти в канал", url=CHANNEL_LINK)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Нажми кнопку ниже, чтобы перейти в наш закрытый канал:",
        reply_markup=reply_markup
    )

async def track_link_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отслеживает нажатия на кнопку (для статистики)"""
    query = update.callback_query
    await query.answer()
    logger.info(f"Button clicked by user {query.from_user.id}")
    
    # Логируем событие в БД
    await log_event(query.from_user.id, 'link_click')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет статистику создателю бота"""
    user = update.effective_user
    
    # Проверяем права доступа
    if user.id != CREATOR_ID:
        await update.message.reply_text("⛔ У вас нет прав для выполнения этой команды.")
        return
    
    # Получаем статистику из БД
    stats = await get_stats()
    full_stats = await get_full_stats()
    
    message = (
        f"📊 <b>Статистика бота:</b>\n\n"
        f"👤 Всего пользователей: <b>{stats['total_users']}</b>\n"
        f"🖱️ Переходов по ссылке: <b>{stats['link_clicks']}</b>\n"
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
telegram_application.add_handler(CommandHandler("stats", stats_command))
telegram_application.add_handler(CallbackQueryHandler(track_link_click))
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
    
    stats = await get_stats()
    
    return {
        "status": "Bot is running", 
        "webhook_url": f"/{WEBHOOK_PATH}",
        "ping_status": "active" if ping_task and not ping_task.done() else "inactive",
        "database": db_status,
        "timestamp": datetime.now().isoformat(),
        "stats": stats
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

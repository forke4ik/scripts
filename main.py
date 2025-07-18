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

# TOKEN из переменных окружения Render
TOKEN = os.environ.get("TOKEN")
CREATOR_ID = 7106925462  # ID создателя бота

# Замени на ссылку на твой закрытый канал
CHANNEL_LINK = "https://t.me/+57Wq6w2wbYhkNjYy"
WEBHOOK_PATH = "webhook"

# URL для самопинга (замените на ваш актуальный URL)
SELF_PING_URL = "https://my-telegram-webhook-bot.onrender.com"
PING_INTERVAL = 600  # 10 минут

# Путь к файлу статистики
STATS_FILE = "stats.json"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальная переменная для задачи пинга
ping_task = None

# --- Система статистики ---
def load_stats():
    """Загружает статистику из файла"""
    try:
        if Path(STATS_FILE).exists():
            with open(STATS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading stats: {e}")
    return {
        "total_users": 0,
        "link_clicks": 0,
        "users": {}
    }

def save_stats(stats):
    """Сохраняет статистику в файл"""
    try:
        with open(STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving stats: {e}")

# Инициализация статистики
stats = load_stats()

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
    global stats
    user = update.effective_user
    logger.info(f"Received /start command from user {user.id}")
    
    # Обновляем статистику
    user_id_str = str(user.id)
    if user_id_str not in stats['users']:
        stats['total_users'] += 1
        stats['users'][user_id_str] = {
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "start_time": datetime.now().isoformat(),
            "link_clicks": 0
        }
        save_stats(stats)
    
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
    
    # Обновляем статистику переходов
    user_id_str = str(query.from_user.id)
    global stats
    
    if user_id_str in stats['users']:
        stats['users'][user_id_str]['link_clicks'] += 1
        stats['link_clicks'] += 1
        save_stats(stats)
        logger.info(f"Updated link click stats for user {query.from_user.id}")
    else:
        logger.warning(f"User {query.from_user.id} clicked but not in stats")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет статистику создателю бота"""
    user = update.effective_user
    
    # Проверяем права доступа
    if user.id != CREATOR_ID:
        await update.message.reply_text("⛔ У вас нет прав для выполнения этой команды.")
        return
    
    global stats
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
        with open(STATS_FILE, 'rb') as f:
            await update.message.reply_document(
                document=f,
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
    return {
        "status": "Bot is running", 
        "webhook_url": f"/{WEBHOOK_PATH}",
        "ping_status": "active" if ping_task and not ping_task.done() else "inactive",
        "timestamp": datetime.now().isoformat(),
        "stats": {
            "total_users": stats['total_users'],
            "link_clicks": stats['link_clicks']
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

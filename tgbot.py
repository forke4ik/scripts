import logging
import os
import asyncio
import aiohttp
import json
from datetime import datetime
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальная переменная для задачи пинга
ping_task = None

# --- Система статистики ---
def load_stats():
    """Загружает статистику из файла"""
    try:
        if Path(STATS_FILE).exists():
            with open(STATS_FILE, 'r') as f:
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
        with open(STATS_FILE, 'w') as f:
            json.dump(stats, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving stats: {e}")

# Инициализация статистики
stats = load_stats()

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
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await update.message.reply_html(
            f"Привет, {user.mention_html()}! Нажми кнопку ниже, чтобы перейти в наш закрытый канал.",
            reply_markup=reply_markup
        )
        logger.info(f"Sent /start response to user {user.id}")
    except Exception as e:
        logger.error(f"Error sending /start response to user {user.id}: {e}")

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает нажатие на кнопку (для будущего использования)"""
    query = update.callback_query
    await query.answer()
    logger.info(f"Button clicked by user {query.from_user.id}")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет статистику создателю бота"""
    user = update.effective_user
    
    # Проверяем права доступа
    if user.id != CREATOR_ID:
        await update.message.reply_text("⛔ У вас нет прав для выполнения этой команды.")
        return
    
    global stats
    message = (
        f"📊 Статистика бота:\n"
        f"👤 Всего пользователей: {stats['total_users']}\n"
        f"🖱️ Переходов по ссылке: {stats['link_clicks']}\n"
        f"🕒 Последнее обновление: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    try:
        # Отправляем текстовую статистику
        await update.message.reply_text(message)
        
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
telegram_application.add_handler(CommandHandler("stats", stats_command))
telegram_application.add_handler(CallbackQueryHandler(button_click))
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

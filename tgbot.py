import logging
import os
import asyncio
import aiohttp
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from quart import Quart, request, Response

# TOKEN из переменных окружения Render
TOKEN = os.environ.get("TOKEN")

# Замени на ссылку на твой закрытый канал
CHANNEL_LINK = "https://t.me/+57Wq6w2wbYhkNjYy"
WEBHOOK_PATH = "webhook"

# URL для самопинга (замените на ваш актуальный URL)
SELF_PING_URL = "https://my-telegram-webhook-bot.onrender.com"
PING_INTERVAL = 600  # 10 минут

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальная переменная для задачи пинга
ping_task = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команду /start и отправляет ссылку."""
    logger.info(f"Received /start command from user {update.effective_user.id}")
    user = update.effective_user
    try:
        await update.message.reply_html(
            f"Привет, {user.mention_html()}! Держи ссылку на наш закрытый канал:\n{CHANNEL_LINK}"
        )
        logger.info(f"Sent /start response to user {user.id}")
    except Exception as e:
        logger.error(f"Error sending /start response to user {user.id}: {e}")

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
            # Продолжаем работу даже при ошибке

# --- Настройка объекта Application из python-telegram-bot ---
if not TOKEN:
    logger.error("Error: Bot TOKEN not found in environment variables!")
    raise ValueError("Bot TOKEN not set")

logger.info("Creating Application object...")
telegram_application = Application.builder().token(TOKEN).build()
logger.info("Application object created.")

logger.info("Adding command handlers...")
telegram_application.add_handler(CommandHandler("start", start))
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
        "timestamp": datetime.now().isoformat()
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

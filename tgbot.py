#import logging
#import os
#from telegram import Update
#from telegram.ext import Application, CommandHandler, ContextTypes
from flask import Flask, request, Response
# asyncio не нужен, Flask async views справляются
# import asyncio

# TOKEN из переменных окружения Render
TOKEN = os.environ.get("TOKEN")

# Замени на ссылку на твой закрытый канал
CHANNEL_LINK = "https://t.me/+57Wq6w2wbYhkNjYy"
WEBHOOK_PATH = "webhook"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

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

# --- Настройка Flask приложения ---
app = Flask(__name__)
logger.info("Flask app created.")

# Флаг для отслеживания инициализации Application
# Инициализация произойдет при первом входящем запросе
is_application_initialized = False

@app.route(f"/{WEBHOOK_PATH}", methods=["POST"])
async def telegram_webhook_handler():
    """Обрабатывает входящие запросы от Телеграма."""
    global is_application_initialized # Используем глобальный флаг
    logger.info("Received POST request on /webhook")

    # Инициализируем Application, если это еще не сделано
    if not is_application_initialized:
        logger.info("Initializing Application...")
        try:
            # Application как асинхронный контекстный менеджер вызывает initialize() при входе и shutdown() при выходе
            # В данном случае initialize() выполнится при первом запросе
            # Нам не нужен долгоживущий контекст здесь, просто вызов initialize() достаточен перед process_update
            # Вызовем initialize() явно, если флаг False
            await telegram_application.initialize() # <-- ЯВНЫЙ ВЫЗОВ initialize()
            is_application_initialized = True
            logger.info("Application initialized.")
        except Exception as e:
            logger.error(f"Error during Application initialization: {e}")
            # Если инициализация не удалась, возвращаем ошибку сервера
            return Response(status=500)

    update_json = request.get_json()
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
    # Теперь Application должен быть инициализирован
    logger.info(f"Processing update {update.update_id} using application.process_update...")
    try:
        # Вызываем process_update, который требует инициализированного Application
        await telegram_application.process_update(update)
        logger.info(f"Update {update.update_id} processing finished.")
    except Exception as e:
        logger.error(f"Error processing update {update.update_id} in Application: {e}")
        # Продолжаем возвращать 200, если ошибка внутри обработчика
        pass

    # Возвращаем ответ Телеграму
    logger.info("Returning 200 OK to Telegram")
    return Response(status=200)

# --- ТО, ЧТО НУЖНО GUNICORN ---
application = app
logger.info("WSGI application variable set to Flask app.")
# --- КОНЕЦ ТОГО, ЧТО НУЖНО GUNICORN ---

# --- Блок для ручной установки webhook ОСТАЕТСЯ ЗАКОММЕНТИРОВАННЫМ ---
# ... (код из предыдущего примера)

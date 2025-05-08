import logging
import os
# Удаляем импорт Thread, threading больше не нужен
# from threading import Thread
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from flask import Flask, request, Response

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
# При использовании process_update, ApplicationBuilder не требует специфичной настройки для webhook
telegram_application = Application.builder().token(TOKEN).build()
logger.info("Application object created.")

logger.info("Adding command handlers...")
telegram_application.add_handler(CommandHandler("start", start))
logger.info("Command handlers added.")

# --- Удаляем код с запуском треда ---
# def run_ptb_application_in_thread():
#    ...
# ptb_thread = Thread(...)
# ptb_thread.start()
# logger.info("PTB Application background thread started.")
# --- Конец кода с тредом ---


# --- Настройка Flask приложения ---
app = Flask(__name__)
logger.info("Flask app created.")

@app.route(f"/{WEBHOOK_PATH}", methods=["POST"])
async def telegram_webhook_handler():
    """Обрабатывает входящие запросы от Телеграма."""
    logger.info("Received POST request on /webhook")

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

    # --- ПЕРЕДАЕМ ОБНОВЛЕНИЕ Application ДЛЯ ОБРАБОТКИ ---
    logger.info(f"Processing update {update.update_id} using application.process_update...")
    try:
        # Явно вызываем process_update для обработки этого обновления
        await telegram_application.process_update(update)
        logger.info(f"Update {update.update_id} processing finished.")
    except Exception as e:
        # Логируем любые ошибки, которые могут возникнуть во время обработки обновления внутри Application/хэндлера
        logger.error(f"Error processing update {update.update_id} in Application: {e}")
        # Важно: даже если при обработке возникла ошибка, Телеграму лучше вернуть 200 OK,
        # чтобы он не пытался повторно отправить это же обновление.
        # Ошибки обработки мы логируем для себя.
        pass # Просто пропускаем ошибку, чтобы вернуть 200 ниже


    # Возвращаем ответ Телеграму, что запрос принят и обработан (или попытка обработки была выполнена)
    logger.info("Returning 200 OK to Telegram")
    return Response(status=200)

# --- ТО, ЧТО НУЖНО GUNICORN ---
# Gunicorn будет искать переменную 'application' на верхнем уровне.
# Мы предоставляем Flask приложение.
application = app
logger.info("WSGI application variable set to Flask app.")
# --- КОНЕЦ ТОГО, ЧТО НУЖНО GUNICORN ---

# --- Блок для ручной установки webhook ОСТАЕТСЯ ЗАКОММЕНТИРОВАННЫМ ---
# ... (код из предыдущего примера)

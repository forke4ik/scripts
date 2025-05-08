import logging
import os
# import asyncio # Не нужно, тред будет использовать свой луп или синхронный раннер
from threading import Thread # <-- Импортируем Thread
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
telegram_application = Application.builder().token(TOKEN).build()
logger.info("Application object created.")

logger.info("Adding command handlers...")
telegram_application.add_handler(CommandHandler("start", start))
logger.info("Command handlers added.")

# --- ЗАПУСК ЦИКЛА ОБРАБОТКИ Application В ОТДЕЛЬНОМ ПОТОКЕ ---
# Эта функция будет выполняться в фоновом потоке,
# вытягивая обновления из update_queue и передавая их диспатчеру.
def run_ptb_application_in_thread():
    logger.info("Starting PTB Application background processing loop in a separate thread...")
    # run_until_disconnected() будет работать, пока приложение не будет остановлено извне
    try:
        telegram_application.run_until_disconnected()
    except Exception as e:
        logger.error(f"Exception in PTB Application thread: {e}")
    logger.info("PTB Application background processing loop stopped.")

# Создаем и запускаем отдельный поток для Application
ptb_thread = Thread(target=run_ptb_application_in_thread)
# daemon=True позволит основному процессу Flask/Gunicorn завершиться,
# даже если этот поток еще работает (хотя Render сам управляет жизнью процесса)
# ptb_thread.daemon = True # Можно добавить, но не всегда обязательно на хостингах
ptb_thread.start()
logger.info("PTB Application background thread started.")
# --- КОНЕЦ ЗАПУСКА ЦИКЛА ОБРАБОТКИ ---


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
         # Возвращаем 400, если не можем распарсить обновление
         return Response(status=400)


    logger.info(f"Putting update {update.update_id} into update queue...")
    try:
        # Добавляем обновление в очередь Application.
        # Фоновый поток (запущенный выше) должен будет забрать его оттуда.
        await telegram_application.update_queue.put(update)
        logger.info(f"Update {update.update_id} successfully added to queue.")
    except Exception as e:
         logger.error(f"Error putting update {update.update_id} into queue: {e}")
         # Возвращаем 500, если не можем добавить в очередь (хотя это маловероятно)
         return Response(status=500)


    # Возвращаем ответ Телеграму, что запрос принят и поставлен в очередь на обработку
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

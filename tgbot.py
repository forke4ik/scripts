import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from flask import Flask, request, Response

# TOKEN из переменных окружения Render
TOKEN = os.environ.get("TOKEN")

# Замени на ссылку на твой закрытый канал
CHANNEL_LINK = "https://t.me/+57Wq6w2wbYhkNjYy"
WEBHOOK_PATH = "webhook"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO # Можно поставить DEBUG для еще больше деталей
)
logger = logging.getLogger(__name__) # Получаем логгер для этого модуля

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команду /start и отправляет ссылку."""
    logger.info(f"Received /start command from user {update.effective_user.id}") # Лог: Получена команда /start
    user = update.effective_user
    try:
        await update.message.reply_html(
            f"Привет, {user.mention_html()}! Держи ссылку на наш закрытый канал:\n{CHANNEL_LINK}"
        )
        logger.info(f"Sent /start response to user {user.id}") # Лог: Ответ отправлен
    except Exception as e:
        logger.error(f"Error sending /start response to user {user.id}: {e}") # Лог: Ошибка при отправке ответа
        # Можно добавить отправку сообщения об ошибке себе в Телеграм для отладки

# --- Настройка объекта Application из python-telegram-bot ---
# Создаем и конфигурируем объект Application
if not TOKEN:
    logger.error("Error: Bot TOKEN not found in environment variables!")
    raise ValueError("Bot TOKEN not set")

logger.info("Creating Application object...") # Лог: Создаем Application
telegram_application = Application.builder().token(TOKEN).build()
logger.info("Application object created.") # Лог: Application создан

# Добавляем обработчики команд
logger.info("Adding command handlers...") # Лог: Добавляем обработчики
telegram_application.add_handler(CommandHandler("start", start))
logger.info("Command handlers added.") # Лог: Обработчики добавлены

# --- Настройка Flask приложения ---
app = Flask(__name__)
logger.info("Flask app created.") # Лог: Flask создан

@app.route(f"/{WEBHOOK_PATH}", methods=["POST"])
async def telegram_webhook_handler():
    """Обрабатывает входящие запросы от Телеграма."""
    logger.info("Received POST request on /webhook") # Лог: Получен POST запрос

    update_json = request.get_json()
    if not update_json:
        logger.warning("Received empty webhook request")
        return Response(status=400)

    logger.info("Received update JSON, attempting to parse...") # Лог: Парсим JSON
    try:
        update = Update.de_json(update_json, telegram_application.bot)
        logger.info(f"Update parsed: {update.update_id}") # Лог: Update распарсен
    except Exception as e:
         logger.error(f"Error parsing update JSON: {e}") # Лог: Ошибка парсинга
         return Response(status=400)


    # Обновление помещается в очередь Application для обработки
    # Application должен сам запустить обработку этого обновления в своем фоне
    logger.info(f"Putting update {update.update_id} into update queue...") # Лог: Добавляем в очередь
    try:
        await telegram_application.update_queue.put(update)
        logger.info(f"Update {update.update_id} successfully added to queue.") # Лог: Добавлено
    except Exception as e:
         logger.error(f"Error putting update {update.update_id} into queue: {e}") # Лог: Ошибка очереди


    # Возвращаем ответ Телеграму
    logger.info("Returning 200 OK to Telegram") # Лог: Возвращаем 200
    return Response(status=200)

# --- ТО, ЧТО НУЖНО GUNICORN ---
# Gunicorn будет искать переменную 'application' на верхнем уровне.
# Мы предоставляем Flask приложение.
application = app
logger.info("WSGI application variable set to Flask app.") # Лог: WSGI приложение готово
# --- КОНЕЦ ТОГО, ЧТО НУЖНО GUNICORN ---

# --- Блок для ручной установки webhook ОСТАЕТСЯ ЗАКОММЕНТИРОВАННЫМ ---
# ... (код из предыдущего примера)

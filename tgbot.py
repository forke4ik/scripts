import logging
import os
# НЕ НУЖНО import asyncio, Flask обрабатывает асинхронность иначе
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from flask import Flask, request, Response # Импортируем Flask

# TOKEN из переменных окружения Render
TOKEN = os.environ.get("TOKEN")

# Замени на ссылку на твой закрытый канал
CHANNEL_LINK = "https://t.me/+57Wq6w2wbYhkNjYy"
# WEBHOOK_PATH оставим для консистентности
WEBHOOK_PATH = "webhook"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команду /start и отправляет ссылку."""
    user = update.effective_user
    await update.message.reply_html(
        f"Привет, {user.mention_html()}! Держи ссылку на наш закрытый канал:\n{CHANNEL_LINK}"
    )

# --- Настройка объекта Application из python-telegram-bot ---
# Создаем и конфигурируем объект Application
if not TOKEN:
    logging.error("Error: Bot TOKEN not found in environment variables!")
    raise ValueError("Bot TOKEN not set")

# Создаем объект Application
# Здесь мы НЕ вызываем run_webhook() или run_polling().
# Application будет использоваться Flask'ом для обработки входящих обновлений.
telegram_application = Application.builder().token(TOKEN).build()
# Добавляем обработчики команд
telegram_application.add_handler(CommandHandler("start", start))

# --- Настройка Flask приложения ---
# Создаем экземпляр Flask приложения
app = Flask(__name__)

# Определяем маршрут для webhook.
# Телеграм будет отправлять POST-запросы на URL твоего сервиса Render + '/webhook'.
@app.route(f"/{WEBHOOK_PATH}", methods=["POST"])
async def telegram_webhook_handler():
    """Обрабатывает входящие запросы от Телеграма."""
    # Получаем JSON данные из запроса
    update_json = request.get_json()
    # Проверяем, что данные пришли
    if not update_json:
        logging.warning("Received empty webhook request")
        return Response(status=400)

    # Создаем объект Update из JSON данных
    update = Update.de_json(update_json, telegram_application.bot)

    # Обрабатываем обновление с помощью Application из python-telegram-bot
    # Используем process_update для обработки обновления в асинхронном цикле Application
    # await telegram_application.process_update(update) # process_update - асинхронный

    # Flask требует синхронный ответ для простого роута.
    # Вызов process_update нужно выполнить в асинхронном контексте.
    # Можно использовать asyncio.run(), но это может быть проблематично в WSGI.
    # Лучше передать обработку в Application другим способом или использовать ASGI-сервер (Uvicorn).
    # Однако, для простоты, let's try just calling process_update directly if it works asyncly...
    # No, process_update is a coroutine, needs await.

    # Стандартный способ в Flask+PTB - использовать Application.update_queue
    # или Dispatcher, но с PTB v22 Application сам диспатчер.
    # В вебхуке нужно передать update в application.
    # https://docs.python-telegram-bot.org/en/stable/telegram.ext.application.html#telegram.ext.Application.process_update
    # process_update needs to be awaited.

    # Option 1: Use a separate async function and run it (can have issues in WSGI)
    # async def process_and_respond():
    #     await telegram_application.process_update(update)
    # asyncio.run(process_and_respond()) # This is bad in WSGI

    # Option 2: Let PTB handle async within the Flask route (might not work directly)
    # await telegram_application.process_update(update) # Flask needs async setup

    # Correct approach for Flask/WSGI: Application.update_queue
    # Add the update to the application's update queue
    await telegram_application.update_queue.put(update) # Add update to internal queue

    # Возвращаем ответ Телеграму, что запрос принят
    return Response(status=200)

# --- ТО, ЧТО НУЖНО GUNICORN ---
# Gunicorn будет искать переменную 'application' на верхнем уровне.
# Мы предоставляем Flask приложение.
application = app
# --- КОНЕЦ ТОГО, ЧТО НУЖНО GUNICORN ---

# --- Этот блок не нужен для работы с Render/Gunicorn/Flask ---
# run_polling() и run_webhook() не используются.
# if __name__ == "__main__":
#     # Этот блок только для локального запуска Flask приложения (для тестирования)
#     # Не используется Render/Gunicorn
#     # Убедись, что у тебя установлен Flask: pip install Flask
#     # Убедись, что токен бота установлен как переменная окружения
#     if not TOKEN:
#         logging.error("Error: Bot TOKEN not found for local testing!")
#     # Flask будет слушать на порту 5000 по умолчанию
#     app.run(debug=True) # debug=True только для разработки

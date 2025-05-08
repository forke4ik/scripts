import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import os

# TOKEN теперь лучше получать из переменных окружения Render
TOKEN = os.environ.get("TOKEN") # Читаем токен из переменной окружения
# Замени на ссылку на твой закрытый канал
CHANNEL_LINK = "https://t.me/+57Wq6w2wbYhkNjYy"
# URL твоего Web App на Render будет предоставлен Render, webhook_path тот же
WEBHOOK_PATH = "webhook" # Просто путь, без домена

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_html(
        f"Привет, {user.mention_html()}! Держи ссылку на наш закрытый канал:\n{CHANNEL_LINK}"
    )

# Создаем объект Application
def create_application() -> Application:
    # Убедись, что токен прочитан успешно
    if not TOKEN:
        logging.error("Error: Bot TOKEN not found in environment variables!")
        # Возможно, стоит как-то иначе обработать ошибку
        raise ValueError("Bot TOKEN not set")
        
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    return application

# --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
# Создаем объект Application
telegram_application = create_application()

# Настраиваем Application для работы с webhook
# Добавляем bootstrap_webhook=False, чтобы НЕ пытаться установить webhook при каждом запуске
telegram_application.run_webhook(
    listen='0.0.0.0',
    port=8080,
    url_path=WEBHOOK_PATH,
    bootstrap_webhook=False # <-- ДОБАВЬ ЭТО
)

# Определяем переменную 'application', которую Gunicorn будет искать.
# Это специальный WSGI-интерфейс из telegram_application.
application = telegram_application.webhooks.wsgi_app
# --- КОНЕЦ ИСПРАВЛЕНИЯ ---

# --- ЭТОТ БЛОК ДОЛЖЕН БЫТЬ ЗАКОММЕНТИРОВАН ---
# Он нужен только для ОДНОКРАТНОЙ установки webhook через консоль.
# async def set_my_webhook(render_url: str):
#     webhook_url = f"{render_url}/{WEBHOOK_PATH}"
#     await telegram_application.bot.set_webhook(url=webhook_url)
#     logging.info(f"Webhook установлен на {webhook_url}")

# if __name__ == "__main__":
#     # Этот блок выполнится только при запуске файла напрямую (для установки webhook)
#     import asyncio
#     # !!! Замени 'YOUR_RENDER_SERVICE_URL' на реальный URL твоего сервиса на Render !!!
#     render_service_url = "https://YOUR_RENDER_SERVICE_URL.onrender.com" # <-- ИСПРАВЬ ЭТО
#     asyncio.run(set_my_webhook(render_service_url))
# --- КОНЕЦ ЗАКОММЕНТИРОВАННОГО БЛОКА ---

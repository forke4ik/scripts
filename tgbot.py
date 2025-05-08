import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import os

# TOKEN из переменных окружения Render
TOKEN = os.environ.get("TOKEN")

# Замени на ссылку на твой закрытый канал
CHANNEL_LINK = "https://t.me/+57Wq6w2wbYhkNjYy"
# WEBHOOK_PATH может понадобиться для ручной установки webhook URL
WEBHOOK_PATH = "webhook"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_html(
        f"Привет, {user.mention_html()}! Держи ссылку на наш закрытый канал:\n{CHANNEL_LINK}"
    )

# --- ТО, ЧТО НУЖНО GUNICORN ---
# Создаем объект Application
# Мы будем создавать его напрямую здесь, чтобы Gunicorn мог найти 'application'
if not TOKEN:
    logging.error("Error: Bot TOKEN not found in environment variables!")
    # Если токен не найден, Gunicorn не сможет запустить приложение
    raise ValueError("Bot TOKEN not set")

# Создаем объект Application прямо здесь
telegram_application = Application.builder().token(TOKEN).build()
# Добавляем обработчики команд
telegram_application.add_handler(CommandHandler("start", start))

# Определяем переменную 'application', которую Gunicorn будет искать.
# Это специальный WSGI-интерфейс из telegram_application.
# Если здесь возникнет AttributeError, значит, webhooks.wsgi_app недоступен.
try:
    application = telegram_application.webhooks.wsgi_app
    logging.info("Successfully accessed webhooks.wsgi_app")
except AttributeError:
    logging.error("Error: 'Application' object has no attribute 'webhooks'. "
                  "Make sure python-telegram-bot is installed with the [webhooks] extra.")
    # Перевыбрасываем ошибку, чтобы деплой Render провалился
    raise

# --- КОНЕЦ ТОГО, ЧТО НУЖНО GUNICORN ---


# --- ЭТОТ БЛОК ДОЛЖЕН БЫТЬ ЗАКОММЕНТИРОВАН ДЛЯ РАБОТЫ С WEB APP ---
# Он нужен только для ОДНОКРАТНОЙ установки webhook через консоль.
# ... (остальная часть кода set_my_webhook и if __name__ == "__main__": остается закомментированной)
# ... (код из предыдущего примера)

# async def set_my_webhook(render_url: str):
#     # Замени 'YOUR_RENDER_SERVICE_URL' на реальный URL твоего сервиса на Render
#     webhook_url = f"{render_url}/{WEBHOOK_PATH}"
#     # Создаем временное Application для вызова set_webhook
#     # Убедись, что TOKEN доступен в окружении, где запускаешь этот блок
#     temp_application = Application.builder().token(TOKEN).build()
#     async with temp_application: # Нужен контекстный менеджер для инициализации бота
#         await temp_application.bot.set_webhook(url=webhook_url)
#     logging.info(f"Webhook установлен на {webhook_url}")
#
# if __name__ == "__main__":
#     import asyncio
#     # !!! Замени 'https://ВАШ_УРЛ_НА_RENDER.onrender.com' на реальный URL твоего сервиса на Render !!!
#     render_service_url = "https://ВАШ_УРЛ_НА_RENDER.onrender.com" # <-- ИСПРАВЬ ЭТО ПЕРЕД ЗАПУСКОМ ДЛЯ УСТАНОВКИ WEBHOOK
#     asyncio.run(set_my_webhook(render_service_url))

import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import os

# TOKEN из переменных окружения Render
TOKEN = os.environ.get("TOKEN")

# Замени на ссылку на твой закрытый канал
CHANNEL_LINK = "https://t.me/+57Wq6w2wbYhkNjYy"
# WEBHOOK_PATH оставим, он может понадобиться для ручной установки webhook URL
WEBHOOK_PATH = "webhook"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_html(
        f"Привет, {user.mention_html()}! Держи ссылку на наш закрытый канал:\n{CHANNEL_LINK}"
    )

# Создаем и конфигурируем объект Application
# Эта функция возвращает Application, готовый к приему обновлений через webhook
def create_webhook_application() -> Application:
    if not TOKEN:
        logging.error("Error: Bot TOKEN not found in environment variables!")
        raise ValueError("Bot TOKEN not set")

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))

    # Здесь мы НЕ вызываем run_webhook().
    # Gunicorn сам будет слушать входящие HTTP запросы и передавать их
    # WSGI-приложению, которое мы определим ниже.

    return application

# --- ЭТО ТО, ЧТО НУЖНО GUNICORN ---
# Создаем объект Application
telegram_application = create_webhook_application()

# Определяем переменную 'application', которую Gunicorn будет искать.
# Это специальный WSGI-интерфейс из telegram_application.
application = telegram_application.webhooks.wsgi_app
# --- КОНЕЦ ТОГО, ЧТО НУЖНО GUNICORN ---


# --- ЭТОТ БЛОК ДОЛЖЕН БЫТЬ ЗАКОММЕНТИРОВАН ДЛЯ РАБОТЫ С WEB APP ---
# Он нужен только для ОДНОКРАТНОЙ установки webhook через консоль.
# Используй этот блок локально или в отдельном скрипте для установки webhook
# после того, как сервис на Render будет запущен и получит свой публичный URL.
#
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
#     # !!! Замени 'https://YOUR_RENDER_SERVICE_URL.onrender.com' на реальный URL твоего сервиса на Render !!!
#     render_service_url = "https://ВАШ_УРЛ_НА_RENDER.onrender.com" # <-- ИСПРАВЬ ЭТО ПЕРЕД ЗАПУСКОМ ДЛЯ УСТАНОВКИ WEBHOOK
#     asyncio.run(set_my_webhook(render_service_url))
# --- КОНЕЦ ЗАКОММЕНТИРОВАННОГО БЛОКА ---

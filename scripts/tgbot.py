import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import os
# import asyncio # asyncio не нужен в этой версии, его вызывает asyncio.run() ниже

TOKEN = "8040453883:AAGRRWGDOCMFipxpFfkGmG2HrRJZ9jYtOzg"
CHANNEL_LINK = "https://t.me/+57Wq6w2wbYhkNjYy"
WEBHOOK_URL = "https://foke4ika.pythonanywhere.com/webhook" # Этот URL используется при ОДНОКРАТНОЙ установке webhook

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_html(
        f"Привет, {user.mention_html()}! Держи ссылку на наш закрытый канал:\n{CHANNEL_LINK}"
    )

# Функция main создает и возвращает объект Application
def main() -> Application:
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    return application

# Эта переменная будет импортирована в wsgi.py
application = main()

# --- ЭТОТ БЛОК ДОЛЖЕН БЫТЬ ЗАКОММЕНТИРОВАН ДЛЯ РАБОТЫ С WEB APP ---
# Он нужен только для ОДНОКРАТНОЙ установки webhook через консоль.
# async def set_my_webhook():
#     await application.bot.set_webhook(url=WEBHOOK_URL)
#     logging.info(f"Webhook установлен на {WEBHOOK_URL}")

# if __name__ == "__main__":
#     # Этот блок выполнится только при запуске файла напрямую (например, в консоли)
#     # Используй его ОДИН РАЗ для установки webhook!
#     import asyncio
#     asyncio.run(set_my_webhook())
# --- КОНЕЦ ЗАКОММЕНТИРОВАННОГО БЛОКА ---
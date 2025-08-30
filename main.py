import logging
import os
import asyncio
import aiohttp
from datetime import datetime
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    BotCommand,
    ChatMember
)
from telegram.constants import ParseMode
from telegram.error import Forbidden, BadRequest
from telegram.ext import (
    Application, 
    CommandHandler, 
    ContextTypes, 
    CallbackQueryHandler
)
from quart import Quart, request, Response

TOKEN = os.environ.get("TOKEN")
CREATOR_ID = int(os.environ.get("CREATOR_ID", "7106925462"))  
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-1002699957973"))  
CHANNEL_LINK = os.environ.get("CHANNEL_LINK", "https://t.me/+57Wq6w2wbYhkNjYy")
WEBHOOK_PATH = "webhook"
SELF_PING_URL = "https://miaphotoroom.onrender.com"
PING_INTERVAL = 600  

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

ping_task = None

async def setup_menu(application: Application):
    commands = [
        BotCommand("start", "Начать работу с ботом"),
        BotCommand("help", "Помощь по использованию бота"),
        BotCommand("channel", "Получить доступ к каналу"),
        BotCommand("check", "Проверить подписку на канал"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Меню команд установлено")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info(f"Received /start command from user {user.id}")
    keyboard = [
        [InlineKeyboardButton("Перейти в канал", url=CHANNEL_LINK)],
        [InlineKeyboardButton("✅ Проверить подписку", callback_data='check_subscription')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await update.message.reply_html(
            f"Привет, {user.mention_html()}! Чтобы получить доступ к нашему закрытому каналу, "
            "пожалуйста, подпишись на него по ссылке ниже, а затем нажми кнопку для проверки.",
            reply_markup=reply_markup
        )
        logger.info(f"Sent /start response to user {user.id}")
    except Exception as e:
        logger.error(f"Error sending /start response to user {user.id}: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "🤖 <b>Команды бота:</b>\n"
        "/start - Начать работу с ботом\n"
        "/help - Показать эту справку\n"
        "/channel - Получить доступ к каналу\n"
        "/check - Проверить подписку на канал\n"
        "\n"
        "После подписки на канал нажмите кнопку <b>«Проверить подписку»</b>, "
        "чтобы получить доступ к контенту."
    )
    await update.message.reply_html(help_text)

async def channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("Перейти в канал", url=CHANNEL_LINK)],
        [InlineKeyboardButton("✅ Проверить подписку", callback_data='check_subscription')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Подпишись на наш канал, затем нажми кнопку для проверки:",
        reply_markup=reply_markup
    )

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await check_subscription(update, context)

async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query:
        await query.answer()
        user = query.from_user
        message = query.message
    else:
        user = update.effective_user
        message = update.message
    logger.info(f"Checking subscription for user {user.id}")
    try:
        chat_member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user.id)
        is_member = chat_member.status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]
        if is_member:
            response_text = (
                f"🎉 Отлично, {user.mention_html()}! Ты подписан на наш канал.\n"
                "Можешь поделиться ссылкой с друзьями:\n"
                f"👉 {CHANNEL_LINK}\n"
                "Приглашай друзей - вместе интереснее!"
            )
            if query:
                await query.edit_message_text(
                    text=response_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=None
                )
            else:
                await message.reply_html(response_text)
        else:
            response_text = (
                f"❌ {user.mention_html()}, ты еще не подписан на наш канал.\n"
                "Пожалуйста, подпишись по ссылке ниже и нажми кнопку проверки снова."
            )
            keyboard = [
                [InlineKeyboardButton("Перейти в канал", url=CHANNEL_LINK)],
                [InlineKeyboardButton("✅ Проверить подписку", callback_data='check_subscription')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            if query:
                await query.edit_message_text(
                    text=response_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
            else:
                await message.reply_html(
                    response_text,
                    reply_markup=reply_markup
                )
    except Forbidden as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        error_text = (
            "⚠️ Недостаточно прав для проверки подписки.\n"
            "Пожалуйста, убедитесь, что бот:\n"
            "1. Добавлен как участник канала\n"
            "2. Имеет право 'Публикация сообщений' в настройках администратора канала"
        )
        if query:
            await query.edit_message_text(error_text)
        else:
            await message.reply_text(error_text)
    except BadRequest as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        error_text = "⚠️ Ошибка конфигурации бота. Пожалуйста, сообщите администратору."
        if query:
            await query.edit_message_text(error_text)
        else:
            await message.reply_text(error_text)
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        error_text = (
            "⚠️ Произошла неизвестная ошибка при проверке подписки. "
            "Пожалуйста, попробуйте позже."
        )
        if query:
            await query.edit_message_text(error_text)
        else:
            await message.reply_text(error_text)

async def self_ping():
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

if not TOKEN:
    logger.error("Error: Bot TOKEN not found in environment variables!")
    raise ValueError("Bot TOKEN not set")

logger.info("Creating Application object...")
telegram_application = Application.builder().token(TOKEN).build()
logger.info("Application object created.")

logger.info("Adding command handlers...")
telegram_application.add_handler(CommandHandler("start", start))
telegram_application.add_handler(CommandHandler("help", help_command))
telegram_application.add_handler(CommandHandler("channel", channel_command))
telegram_application.add_handler(CommandHandler("check", check_command))
telegram_application.add_handler(CallbackQueryHandler(check_subscription, pattern='^check_subscription$'))
logger.info("Command handlers added.")

app = Quart(__name__)
logger.info("Quart app created.")

is_application_initialized = False

@app.before_serving
async def startup():
    global ping_task
    logger.info("🚀 Запуск самопинга...")
    ping_task = asyncio.create_task(self_ping())
    logger.info("Устанавливаем меню команд...")
    await setup_menu(telegram_application)

@app.after_serving
async def shutdown():
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
    global is_application_initialized
    logger.info("Received POST request on /webhook")
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
    logger.info(f"Processing update {update.update_id} using application.process_update...")
    try:
        await telegram_application.process_update(update)
        logger.info(f"Update {update.update_id} processing finished.")
    except Exception as e:
        logger.error(f"Error processing update {update.update_id} in Application: {e}")
        pass
    logger.info("Returning 200 OK to Telegram")
    return Response(status=200)

@app.route("/", methods=["GET"])
async def health_check():
    return {
        "status": "Bot is running", 
        "webhook_url": f"/{WEBHOOK_PATH}",
        "ping_status": "active" if ping_task and not ping_task.done() else "inactive",
        "timestamp": datetime.now().isoformat()
    }

@app.route("/set_webhook", methods=["GET"])
async def set_webhook():
    webhook_url = f"{SELF_PING_URL}/webhook"
    try:
        global is_application_initialized
        if not is_application_initialized:
            await telegram_application.initialize()
            is_application_initialized = True
        await telegram_application.bot.set_webhook(webhook_url)
        logger.info(f"Webhook set to: {webhook_url}")
        return {"status": "success", "webhook_url": webhook_url}
    except Exception as e:
        logger.error(f"Error setting webhook: {e}")
        return {"status": "error", "error": str(e)}

@app.route("/ping_status", methods=["GET"])
async def ping_status():
    return {
        "ping_active": ping_task and not ping_task.done(),
        "ping_interval": PING_INTERVAL,
        "self_ping_url": SELF_PING_URL,
        "timestamp": datetime.now().isoformat()
    }

logger.info("ASGI application ready.")

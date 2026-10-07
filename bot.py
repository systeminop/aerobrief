import os
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚗 Auto Radar запущен!\n\n"
        "Я ищу автомобили с потенциалом для перепродажи.\n\n"
        "Команды:\n"
        "/help — помощь\n"
        "/cars — поиск автомобилей"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔎 Auto Radar\n\n"
        "Сейчас доступна тестовая система поиска.\n\n"
        "/cars — начать поиск автомобиля"
    )


async def cars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚗 Поиск автомобиля\n\n"
        "Напиши параметры в одном сообщении.\n\n"
        "Например:\n"
        "Kia Rio, до 700 000 ₽, от 2016 года, "
        "пробег до 200 000 км, Москва\n\n"
        "Я обработаю эти параметры."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    await update.message.reply_text(
        "🔎 Получил запрос:\n\n"
        f"{text}\n\n"
        "⏳ Сейчас это тестовый режим.\n"
        "Следующим этапом подключим реальные объявления "
        "и анализ цены."
    )


def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cars", cars))

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    print("Auto Radar Bot запущен")

    app.run_polling()


if __name__ == "__main__":
    main()

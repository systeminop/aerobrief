import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚗 Auto Radar запущен!\n\n"
        "Я буду искать интересные автомобили для перепродажи.\n\n"
        "Пока это тестовая версия."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Доступные команды:\n\n"
        "/start — запустить бота\n"
        "/help — помощь\n"
        "/cars — поиск автомобилей"
    )


async def cars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔎 Модуль поиска автомобилей пока подключается.\n"
        "Следующим этапом подключим источники объявлений."
    )


def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cars", cars))

    print("Auto Radar Bot запущен")
    app.run_polling()


if __name__ == "__main__":
    main()

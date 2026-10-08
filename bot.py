import os
import re

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
        "Я могу обработать запрос на поиск автомобиля.\n\n"
        "/cars — начать поиск автомобиля"
    )


async def cars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚗 Поиск автомобиля\n\n"
        "Напиши параметры в одном сообщении.\n\n"
        "Например:\n"
        "Kia Rio, до 700 000 ₽, от 2016 года, "
        "пробег до 200 000 км, Москва"
    )


def extract_parameters(text):
    price = None
    year = None
    mileage = None
    city = None

    price_match = re.search(
        r"до\s*([\d\s]+)\s*(?:₽|руб|рублей)?",
        text,
        re.IGNORECASE
    )

    if price_match:
        price = int(price_match.group(1).replace(" ", ""))

    year_match = re.search(
        r"от\s*(20\d{2})\s*(?:года|г)?",
        text,
        re.IGNORECASE
    )

    if year_match:
        year = int(year_match.group(1))

    mileage_match = re.search(
        r"пробег\s*до\s*([\d\s]+)\s*(?:км)?",
        text,
        re.IGNORECASE
    )

    if mileage_match:
        mileage = int(mileage_match.group(1).replace(" ", ""))

    cities = [
        "Москва",
        "Санкт-Петербург",
        "Казань",
        "Самара",
        "Сочи",
        "Краснодар",
        "Ростов-на-Дону",
        "Воронеж",
        "Нижний Новгород",
        "Екатеринбург",
        "Уфа",
        "Пермь",
        "Омск",
        "Тула",
        "Тверь",
    ]

    for city_name in cities:
        if city_name.lower() in text.lower():
            city = city_name
            break

    return price, year, mileage, city


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    price, year, mileage, city = extract_parameters(text)

    result = (
        "🔎 AUTO RADAR\n\n"
        f"Запрос:\n{text}\n\n"
        "🧠 Распознанные параметры:\n\n"
        f"🚗 Автомобиль: {text.split(',')[0].strip()}\n"
        f"💰 Максимальная цена: "
        f"{price:,} ₽\n".replace(",", " ")
        if price
        else "💰 Максимальная цена: не определена\n"
    )

    if price:
        result += f"📅 Минимальный год: {year or 'не определён'}\n"
        result += f"📏 Максимальный пробег: "
        result += f"{mileage:,} км\n".replace(",", " ") if mileage else "не определён\n"
        result += f"📍 Город: {city or 'не определён'}\n\n"
    else:
        result += (
            f"📅 Минимальный год: {year or 'не определён'}\n"
            f"📏 Максимальный пробег: "
            f"{mileage:,} км\n".replace(",", " ") if mileage else "📏 Максимальный пробег: не определён\n"
        )
        result += f"📍 Город: {city or 'не определён'}\n\n"

    result += (
        "✅ Запрос успешно обработан.\n\n"
        "⏳ Следующий этап:\n"
        "подключаем реальные объявления "
        "и анализируем цену."
    )

    await update.message.reply_text(result)


def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cars", cars))

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print("Auto Radar Bot запущен")

    app.run_polling()


if __name__ == "__main__":
    main()

import os
import re
import json
import threading
from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RADARS_FILE = "radars.json"

app_web = Flask(__name__)


@app_web.route("/")
def home():
    return "AUTO RADAR BOT IS RUNNING", 200


def run_web():
    port = int(os.getenv("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)


def load_radars():
    if not os.path.exists(RADARS_FILE):
        return {}

    try:
        with open(RADARS_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return {}


def save_radars(radars):
    with open(RADARS_FILE, "w", encoding="utf-8") as file:
        json.dump(radars, file, ensure_ascii=False, indent=2)


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

    parts = [part.strip() for part in text.split(",")]
    car = parts[0] if parts else text

    return {
        "car": car,
        "price": price,
        "year": year,
        "mileage": mileage,
        "city": city,
    }


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚗 AUTO RADAR\n\n"
        "Я автоматически ищу новые автомобили "
        "по заданным тобой параметрам.\n\n"
        "Команды:\n"
        "/radar — создать новый радар\n"
        "/radars — мои радары\n"
        "/help — помощь"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔎 AUTO RADAR\n\n"
        "Создай радар командой /radar.\n\n"
        "Например:\n"
        "Kia Rio, до 700 000 ₽, от 2016 года, "
        "пробег до 200 000 км, Москва"
    )


async def radar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["creating_radar"] = True

    await update.message.reply_text(
        "🚨 СОЗДАНИЕ РАДАРА\n\n"
        "Отправь одним сообщением параметры автомобиля.\n\n"
        "Например:\n\n"
        "Kia Rio, до 700 000 ₽, от 2016 года, "
        "пробег до 200 000 км, Москва"
    )


async def radars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    all_radars = load_radars()
    user_radars = all_radars.get(user_id, [])

    if not user_radars:
        await update.message.reply_text(
            "📭 У тебя пока нет активных радаров.\n\n"
            "Создай первый через /radar"
        )
        return

    message = "🚨 ТВОИ РАДАРЫ\n\n"

    for index, radar_data in enumerate(user_radars, start=1):
        price = radar_data.get("price")
        mileage = radar_data.get("mileage")

        message += (
            f"🔎 Радар #{index}\n"
            f"🚗 {radar_data.get('car', '—')}\n"
            f"💰 до {price:,} ₽\n".replace(",", " ")
        )

        message += (
            f"📅 от {radar_data.get('year', '—')}\n"
            f"📏 до {mileage:,} км\n".replace(",", " ")
            if mileage
            else "📏 пробег —\n"
        )

        message += (
            f"📍 {radar_data.get('city', '—')}\n\n"
        )

    await update.message.reply_text(message)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if context.user_data.get("creating_radar"):
        radar_data = extract_parameters(text)

        user_id = str(update.effective_user.id)

        all_radars = load_radars()

        if user_id not in all_radars:
            all_radars[user_id] = []

        all_radars[user_id].append(radar_data)

        save_radars(all_radars)

        context.user_data["creating_radar"] = False

        await update.message.reply_text(
            "✅ РАДАР СОЗДАН!\n\n"
            f"🚗 {radar_data['car']}\n"
            f"💰 До {radar_data['price']:,} ₽\n".replace(",", " ")
            + f"📅 От {radar_data['year']} года\n"
            + f"📏 До {radar_data['mileage']:,} км\n".replace(",", " ")
            + f"📍 {radar_data['city']}\n\n"
            "🔔 Запрос сохранён.\n\n"
            "Следующий этап — автоматический мониторинг "
            "новых объявлений."
        )

        return

    await update.message.reply_text(
        "🤔 Я не понял команду.\n\n"
        "Используй /radar, чтобы создать автоматический поиск."
    )


def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")

    threading.Thread(target=run_web, daemon=True).start()

    telegram_app = Application.builder().token(TOKEN).build()

    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("help", help_command))
    telegram_app.add_handler(CommandHandler("radar", radar))
    telegram_app.add_handler(CommandHandler("radars", radars))

    telegram_app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print("AUTO RADAR BOT запущен")

    telegram_app.run_polling()


if __name__ == "__main__":
    main()

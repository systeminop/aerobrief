import os
import re
import json
import requests

from html import unescape
from flask import Flask

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# =========================================================
# НАСТРОЙКИ
# =========================================================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

RADARS_FILE = "radars.json"
SEEN_FILE = "seen_ads.json"
USERS_FILE = "users.json"

CHECK_INTERVAL = 10 * 60  # 10 минут


# Пока тестируем на этом поиске:
# Kia Rio / Москва / до 700 000 / от 2016 / до 200 000 км

AVITO_URL = (
    "https://m.avito.ru/moskva/avtomobili/kia/rio-ASgBAgICAkTgtg3KmCjitg3Krig"
    "?context=H4sIAAAAAAAA_wGeAGH_YTo0OntzOjk6ImZyb21fcGFnZSI7czo3OiJmaWx0ZXJzIjtzOjY6InNvdXJjZSI7czo4OiJvcmRpbmFyeSI7czo1Mjoic291cmNlX3F1ZXJ5IjtzOjc6ImtpYSByaW8iO3M6NToieF9zZ3QiO3M6NDA6IjM4MDNiMzU2Mzk1ZDIwMDk4NjY3Y2IzMzliMGRhZjkzZTcxYzNlODMiO32uyOswngAAAA"
    "&f=ASgBAgECAkTgtg3KmCjitg3KrigDRf4pGXsiZnJvbSI6bnVsbCwidG8iOjIwMDAwMH3GmgwWeyJmcm9tIjowLCJ0byI6NzAwMDAwffqMFBd7ImZyb20iOjIwMTYsInRvIjpudWxsfQ"
    "&moreExpensive=0&presentationType=serp&radius=0"
)


# =========================================================
# FLASK ДЛЯ RENDER
# =========================================================

app_web = Flask(__name__)


@app_web.route("/")
def home():
    return "AUTO RADAR BOT IS RUNNING", 200


# =========================================================
# ФАЙЛЫ
# =========================================================

def load_json(filename, default):
    if not os.path.exists(filename):
        return default

    try:
        with open(filename, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return default


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )


def load_radars():
    return load_json(
        RADARS_FILE,
        {}
    )


def save_radars(radars):
    save_json(
        RADARS_FILE,
        radars
    )


def load_seen():
    return load_json(
        SEEN_FILE,
        []
    )


def save_seen(seen):
    save_json(
        SEEN_FILE,
        seen
    )


def load_users():
    return load_json(
        USERS_FILE,
        []
    )


def save_users(users):
    save_json(
        USERS_FILE,
        users
    )


# =========================================================
# ТЕКСТ
# =========================================================

def clean_text(value):

    if not value:
        return ""

    value = unescape(value)
    value = value.replace("\xa0", " ")
    value = value.replace("\\/", "/")
    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


# =========================================================
# AVITO
# =========================================================

def get_avito_ads():

    print("")
    print("====================================")
    print("🔎 ПРОВЕРКА AVITO")
    print("====================================")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 "
            "Version/17.0 Mobile/15E148 Safari/604.1"
        )
    }

    try:

        response = requests.get(
            AVITO_URL,
            headers=headers,
            timeout=30
        )

        text = response.text

        print(
            "AVITO STATUS:",
            response.status_code
        )

        print(
            "AVITO HTML LENGTH:",
            len(text)
        )

        item_ids = re.findall(
            r'itemId[=:]\\?["\']?(\d{8,})',
            text
        )

        unique_ids = []

        for item_id in item_ids:

            if item_id not in unique_ids:
                unique_ids.append(item_id)

        print(
            "UNIQUE ITEM IDS:",
            len(unique_ids)
        )

        ads = []

        for item_id in unique_ids:

            positions = [
                match.start()
                for match in re.finditer(
                    re.escape(item_id),
                    text
                )
            ]

            if not positions:
                continue

            best_title = None
            best_href = None
            best_block = None

            for position in positions:

                block_start = max(
                    0,
                    position - 5000
                )

                block_end = min(
                    len(text),
                    position + 5000
                )

                block = text[
                    block_start:block_end
                ]

                link_matches = re.findall(
                    r'<a[^>]+data-marker="item/link"[^>]*>',
                    block
                )

                for link in link_matches:

                    title_match = re.search(
                        r'title="([^"]+)"',
                        link
                    )

                    href_match = re.search(
                        r'href="([^"]+)"',
                        link
                    )

                    if not title_match:
                        continue

                    title = clean_text(
                        title_match.group(1)
                    )

                    if (
                        "Kia Rio" in title
                        or "Kia" in title
                        or "Rio" in title
                    ):

                        best_title = title

                        if href_match:
                            best_href = (
                                href_match.group(1)
                            )

                        best_block = block

                        break

                if best_title:
                    break

            if not best_title:
                continue

            # Цена

            price = None

            if best_block:

                price_matches = re.findall(
                    r'(\d[\d\xa0\s]{2,})\s*₽',
                    best_block
                )

                prices = []

                for value in price_matches:

                    value = (
                        value
                        .replace("\xa0", "")
                        .replace(" ", "")
                    )

                    if value.isdigit():

                        number = int(value)

                        if (
                            100000
                            <= number
                            <= 10000000
                        ):
                            prices.append(number)

                if prices:
                    price = prices[0]

            # Год

            year = None

            year_match = re.search(
                r'\b(20\d{2})\b',
                best_title
            )

            if year_match:
                year = int(
                    year_match.group(1)
                )

            # Пробег

            mileage = None

            mileage_match = re.search(
                r'([\d\s\xa0]+)\s*км',
                best_title,
                re.IGNORECASE
            )

            if mileage_match:

                mileage_text = (
                    mileage_match.group(1)
                    .replace("\xa0", "")
                    .replace(" ", "")
                )

                if mileage_text.isdigit():

                    mileage = int(
                        mileage_text
                    )

            # Город

            city = "Москва"

            if (
                best_href
                and
                "moskva_zelenograd"
                in best_href
            ):
                city = "Москва, Зеленоград"

            # URL

            if best_href:

                if best_href.startswith("http"):
                    url = best_href
                else:
                    url = (
                        "https://www.avito.ru"
                        + best_href
                    )

            else:

                url = (
                    "https://www.avito.ru/"
                    "moskva/avtomobili/"
                    + item_id
                )

            ads.append({
                "id": item_id,
                "title": best_title,
                "price": price,
                "year": year,
                "mileage": mileage,
                "city": city,
                "url": url,
            })

        print(
            "НАЙДЕНО ОБЪЯВЛЕНИЙ:",
            len(ads)
        )

        return ads

    except Exception as e:

        print(
            "❌ AVITO ERROR:",
            repr(e)
        )

        return []


# =========================================================
# ФИЛЬТР
# =========================================================

def matches_radar(ad):

    title = ad.get(
        "title",
        ""
    ).lower()

    # Битые пока исключаем

    if "битый" in title:
        return False

    price = ad.get("price")

    if price is None:
        return False

    if price > 700000:
        return False

    year = ad.get("year")

    if year is None:
        return False

    if year < 2016:
        return False

    mileage = ad.get("mileage")

    if mileage is None:
        return False

    if mileage > 200000:
        return False

    return True


# =========================================================
# СООБЩЕНИЕ
# =========================================================

def format_ad(ad):

    price = ad.get("price")

    if price:

        price_text = (
            f"{price:,}"
            .replace(",", " ")
            + " ₽"
        )

    else:

        price_text = "Цена не указана"

    year = ad.get(
        "year",
        "—"
    )

    mileage = ad.get(
        "mileage"
    )

    if mileage:

        mileage_text = (
            f"{mileage:,}"
            .replace(",", " ")
            + " км"
        )

    else:

        mileage_text = "—"

    city = ad.get(
        "city",
        "Москва"
    )

    title = ad.get(
        "title",
        "Kia Rio"
    )

    url = ad.get(
        "url",
        ""
    )

    return (
        "🚨 НОВОЕ ОБЪЯВЛЕНИЕ!\n\n"
        f"🚗 {title}\n"
        f"💰 Цена: {price_text}\n"
        f"📅 Год: {year}\n"
        f"📏 Пробег: {mileage_text}\n"
        f"📍 {city}\n\n"
        f"🔗 {url}"
    )


# =========================================================
# МОНИТОРИНГ
# =========================================================

async def monitor_job(context):

    print("")
    print("🔄 НАЧИНАЮ АВТОМАТИЧЕСКУЮ ПРОВЕРКУ")

    ads = get_avito_ads()

    if not ads:

        print(
            "⚠️ Объявления не получены"
        )

        return

    seen = load_seen()

    # Первый запуск

    first_run = len(seen) == 0

    new_ads = []

    for ad in ads:

        item_id = ad["id"]

        if item_id not in seen:

            seen.append(item_id)

            if not first_run:

                if matches_radar(ad):

                    new_ads.append(ad)

    save_seen(seen)

    if first_run:

        print(
            "✅ Первый запуск."
        )

        print(
            f"Запомнил {len(seen)} объявлений."
        )

        return

    print(
        f"🆕 Новых объявлений: "
        f"{len(new_ads)}"
    )

    if not new_ads:

        return

    users = load_users()

    print(
        f"👥 Получателей: {len(users)}"
    )

    for ad in new_ads:

        message = format_ad(ad)

        for chat_id in users:

            try:

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=message
                )

                print(
                    "📲 Уведомление отправлено:",
                    ad["id"]
                )

            except Exception as e:

                print(
                    "❌ Ошибка Telegram:",
                    repr(e)
                )


# =========================================================
# TELEGRAM
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id

    users = load_users()

    if chat_id not in users:

        users.append(chat_id)

        save_users(users)

        print(
            "👤 Новый пользователь:",
            chat_id
        )

    await update.message.reply_text(
        "🚗 AUTO RADAR\n\n"
        "Бот работает.\n\n"
        "🔔 Я могу автоматически "
        "отслеживать новые автомобили.\n\n"
        "/radar — создать радар\n"
        "/radars — мои радары\n"
        "/help — помощь"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🔎 AUTO RADAR\n\n"
        "Команды:\n\n"
        "/radar — создать радар\n"
        "/radars — показать мои радары\n"
        "/help — помощь\n\n"
        "Сейчас тестовый мониторинг:\n"
        "Kia Rio / Москва / до 700 000 ₽ / "
        "от 2016 года / до 200 000 км."
    )


async def radar(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data[
        "creating_radar"
    ] = True

    await update.message.reply_text(
        "🚨 СОЗДАНИЕ РАДАРА\n\n"
        "Отправь параметры одним сообщением.\n\n"
        "Например:\n\n"
        "Kia Rio, до 700 000 ₽, "
        "от 2016 года, "
        "пробег до 200 000 км, Москва"
    )


async def radars(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = str(
        update.effective_user.id
    )

    all_radars = load_radars()

    user_radars = all_radars.get(
        user_id,
        []
    )

    if not user_radars:

        await update.message.reply_text(
            "📭 У тебя пока нет активных радаров.\n\n"
            "Создай первый через /radar."
        )

        return

    message = (
        "🚨 ТВОИ РАДАРЫ\n\n"
    )

    for index, radar_data in enumerate(
        user_radars,
        start=1
    ):

        price = radar_data.get(
            "price"
        )

        mileage = radar_data.get(
            "mileage"
        )

        if price:

            price_text = (
                f"{price:,}"
                .replace(",", " ")
            )

        else:

            price_text = "—"

        if mileage:

            mileage_text = (
                f"{mileage:,}"
                .replace(",", " ")
            )

        else:

            mileage_text = "—"

        message += (
            f"🔎 Радар #{index}\n"
            f"🚗 {radar_data.get('car', '—')}\n"
            f"💰 до {price_text} ₽\n"
            f"📅 от {radar_data.get('year', '—')}\n"
            f"📏 до {mileage_text} км\n"
            f"📍 {radar_data.get('city', '—')}\n\n"
        )

    await update.message.reply_text(
        message
    )


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text.strip()

    if not context.user_data.get(
        "creating_radar"
    ):

        await update.message.reply_text(
            "🤔 Я не понял сообщение.\n\n"
            "Используй /radar."
        )

        return

    # Цена

    price = None

    price_match = re.search(
        r"до\s*([\d\s]+)",
        text,
        re.IGNORECASE
    )

    if price_match:

        price = int(
            price_match.group(1)
            .replace(" ", "")
        )

    # Год

    year = None

    year_match = re.search(
        r"от\s*(20\d{2})",
        text,
        re.IGNORECASE
    )

    if year_match:

        year = int(
            year_match.group(1)
        )

    # Пробег

    mileage = None

    mileage_match = re.search(
        r"пробег\s*до\s*([\d\s]+)",
        text,
        re.IGNORECASE
    )

    if mileage_match:

        mileage = int(
            mileage_match.group(1)
            .replace(" ", "")
        )

    # Город

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

    city = None

    for city_name in cities:

        if city_name.lower() in text.lower():

            city = city_name

            break

    parts = [
        part.strip()
        for part in text.split(",")
    ]

    car = (
        parts[0]
        if parts
        else text
    )

    radar_data = {
        "car": car,
        "price": price,
        "year": year,
        "mileage": mileage,
        "city": city,
    }

    user_id = str(
        update.effective_user.id
    )

    all_radars = load_radars()

    if user_id not in all_radars:

        all_radars[user_id] = []

    all_radars[user_id].append(
        radar_data
    )

    save_radars(
        all_radars
    )

    context.user_data[
        "creating_radar"
    ] = False

    price_text = (
        f"{price:,}"
        .replace(",", " ")
        if price
        else "—"
    )

    mileage_text = (
        f"{mileage:,}"
        .replace(",", " ")
        if mileage
        else "—"
    )

    await update.message.reply_text(
        "✅ РАДАР СОЗДАН!\n\n"
        f"🚗 {car}\n"
        f"💰 До {price_text} ₽\n"
        f"📅 От {year or '—'} года\n"
        f"📏 До {mileage_text} км\n"
        f"📍 {city or '—'}\n\n"
        "🔔 Радар сохранён."
    )


# =========================================================
# ЗАПУСК
# =========================================================

def main():

    if not TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN не задан"
        )

    # Render Web Service
    import threading

    def run_web():

        port = int(
            os.getenv(
                "PORT",
                10000
            )
        )

        app_web.run(
            host="0.0.0.0",
            port=port
        )

    threading.Thread(
        target=run_web,
        daemon=True
    ).start()

    # Telegram Application

    telegram_app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    telegram_app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    telegram_app.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    telegram_app.add_handler(
        CommandHandler(
            "radar",
            radar
        )
    )

    telegram_app.add_handler(
        CommandHandler(
            "radars",
            radars
        )
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            handle_message
        )
    )

    # Автоматическая проверка
    telegram_app.job_queue.run_repeating(
        monitor_job,
        interval=CHECK_INTERVAL,
        first=10
    )

    print("")
    print("====================================")
    print("🚗 AUTO RADAR BOT ЗАПУЩЕН")
    print("====================================")
    print("")
    print(
        "🚨 АВТОМАТИЧЕСКИЙ РАДАР ЗАПУЩЕН"
    )
    print(
        "⏱ Проверка каждые 10 минут"
    )

    telegram_app.run_polling()


if __name__ == "__main__":
    main()

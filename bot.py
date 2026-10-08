import os
import re
import json
import threading
import time
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


# =========================
# НАСТРОЙКИ
# =========================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

RADARS_FILE = "radars.json"
SEEN_FILE = "seen_ads.json"

CHECK_INTERVAL = 10 * 60  # 10 минут


# Пока работаем с твоим первым радаром:
# Kia Rio / Москва / до 700 000 / от 2016 / до 200 000 км

AVITO_URL = (
    "https://m.avito.ru/moskva/avtomobili/kia/rio-ASgBAgICAkTgtg3KmCjitg3Krig"
    "?context=H4sIAAAAAAAA_wGeAGH_YTo0OntzOjk6ImZyb21fcGFnZSI7czo3OiJmaWx0ZXJzIjtzOjY6InNvdXJjZSI7czo4OiJvcmRpbmFyeSI7czo1Mjoic291cmNlX3F1ZXJ5IjtzOjc6ImtpYSByaW8iO3M6NToieF9zZ3QiO3M6NDA6IjM4MDNiMzU2Mzk1ZDIwMDk4NjY3Y2IzMzliMGRhZjkzZTcxYzNlODMiO32uyOswngAAAA"
    "&f=ASgBAgECAkTgtg3KmCjitg3KrigDRf4pGXsiZnJvbSI6bnVsbCwidG8iOjIwMDAwMH3GmgwWeyJmcm9tIjowLCJ0byI6NzAwMDAwffqMFBd7ImZyb20iOjIwMTYsInRvIjpudWxsfQ"
    "&moreExpensive=0&presentationType=serp&radius=0"
)


app_web = Flask(__name__)


# =========================
# WEB SERVER ДЛЯ RENDER
# =========================

@app_web.route("/")
def home():
    return "AUTO RADAR BOT IS RUNNING", 200


def run_web():
    port = int(os.getenv("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)


# =========================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================

def clean_text(value):
    if not value:
        return ""

    value = unescape(value)
    value = value.replace("\xa0", " ")
    value = value.replace("\\/", "/")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


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
        json.dump(data, file, ensure_ascii=False, indent=2)


def load_radars():
    return load_json(RADARS_FILE, {})


def save_radars(radars):
    save_json(RADARS_FILE, radars)


def load_seen():
    return load_json(SEEN_FILE, [])


def save_seen(seen):
    save_json(SEEN_FILE, seen)


# =========================
# ПОЛУЧЕНИЕ ОБЪЯВЛЕНИЙ AVITO
# =========================

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

        print("AVITO STATUS:", response.status_code)
        print("AVITO HTML LENGTH:", len(text))

        # Находим ID объявлений
        item_ids = re.findall(
            r'itemId[=:]\\?["\']?(\d{8,})',
            text
        )

        unique_ids = []

        for item_id in item_ids:
            if item_id not in unique_ids:
                unique_ids.append(item_id)

        print("UNIQUE ITEM IDS:", len(unique_ids))

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

                # Ищем ссылку объявления
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

            # =========================
            # ЦЕНА
            # =========================

            price = None

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

                    if 100000 <= number <= 10000000:
                        prices.append(number)

            if prices:
                price = prices[0]

            # =========================
            # ГОД
            # =========================

            year_match = re.search(
                r'\b(20\d{2})\b',
                best_title
            )

            year = None

            if year_match:
                year = int(
                    year_match.group(1)
                )

            # =========================
            # ПРОБЕГ
            # =========================

            mileage_match = re.search(
                r'([\d\s\xa0]+)\s*км',
                best_title,
                re.IGNORECASE
            )

            mileage = None

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

            # =========================
            # ГОРОД
            # =========================

            city = "Москва"

            if (
                best_href
                and "moskva_zelenograd"
                in best_href
            ):
                city = "Москва, Зеленоград"

            # =========================
            # ССЫЛКА
            # =========================

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


# =========================
# ФИЛЬТР РАДАРА
# =========================

def matches_radar(ad):

    # Не берём битые машины
    title = ad.get(
        "title",
        ""
    ).lower()

    if "битый" in title:
        return False

    # Цена
    price = ad.get("price")

    if price is None:
        return False

    if price > 700000:
        return False

    # Год
    year = ad.get("year")

    if year is None:
        return False

    if year < 2016:
        return False

    # Пробег
    mileage = ad.get("mileage")

    if mileage is None:
        return False

    if mileage > 200000:
        return False

    return True


# =========================
# ФОРМАТ УВЕДОМЛЕНИЯ
# =========================

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


# =========================
# МОНИТОРИНГ AVITO
# =========================

def monitor_avito(telegram_app):

    print("")
    print("🚨 АВТОМАТИЧЕСКИЙ РАДАР ЗАПУЩЕН")
    print(
        f"⏱ Проверка каждые "
        f"{CHECK_INTERVAL // 60} минут"
    )

    # Получаем Telegram ID пользователей
    # из сохранённых данных
    users_file = "users.json"

    while True:

        try:

            print("")
            print("🔄 Начинаю новую проверку...")

            ads = get_avito_ads()

            if not ads:
                print(
                    "⚠️ Объявления не получены"
                )

                time.sleep(
                    CHECK_INTERVAL
                )

                continue

            seen = load_seen()

            # При первом запуске просто запоминаем
            # уже существующие объявления,
            # чтобы бот не отправил тебе сразу 30 сообщений.

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
                    f"✅ Первый запуск. "
                    f"Запомнил {len(seen)} объявлений."
                )

            else:

                print(
                    f"🆕 Новых объявлений: "
                    f"{len(new_ads)}"
                )

            # Получаем пользователей
            users = load_json(
                users_file,
                []
            )

            # Отправляем новые объявления
            for ad in new_ads:

                message = format_ad(ad)

                for chat_id in users:

                    try:

                        future = telegram_app.bot.send_message(
                            chat_id=chat_id,
                            text=message
                        )

                        # Для async метода используем event loop
                        import asyncio

                        try:
                            loop = asyncio.get_event_loop()
                        except RuntimeError:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)

                        loop.run_until_complete(
                            future
                        )

                        print(
                            "📲 Отправлено:",
                            ad["id"]
                        )

                    except Exception as e:

                        print(
                            "❌ Ошибка отправки:",
                            repr(e)
                        )

        except Exception as e:

            print(
                "❌ ОШИБКА МОНИТОРИНГА:",
                repr(e)
            )

        print(
            f"😴 Следующая проверка "
            f"через {CHECK_INTERVAL // 60} минут."
        )

        time.sleep(
            CHECK_INTERVAL
        )


# =========================
# TELEGRAM
# =========================

async def start(update, context):

    chat_id = update.effective_chat.id

    users_file = "users.json"

    users = load_json(
        users_file,
        []
    )

    if chat_id not in users:

        users.append(chat_id)

        save_json(
            users_file,
            users
        )

        print(
            "👤 Новый пользователь:",
            chat_id
        )

    await update.message.reply_text(
        "🚗 AUTO RADAR\n\n"
        "Я автоматически отслеживаю новые "
        "автомобили на Avito.\n\n"
        "🔔 Когда появляется новое подходящее "
        "объявление — я отправляю его тебе.\n\n"
        "Команды:\n"
        "/radar — создать радар\n"
        "/radars — мои радары\n"
        "/help — помощь"
    )


async def help_command(update, context):

    await update.message.reply_text(
        "🔎 AUTO RADAR\n\n"
        "Сейчас активен автоматический "
        "радар Kia Rio.\n\n"
        "Параметры:\n"
        "🚗 Kia Rio\n"
        "💰 до 700 000 ₽\n"
        "📅 от 2016 года\n"
        "📏 до 200 000 км\n"
        "📍 Москва\n\n"
        "Я буду проверять Avito автоматически."
    )


async def radar(update, context):

    context.user_data[
        "creating_radar"
    ] = True

    await update.message.reply_text(
        "🚨 СОЗДАНИЕ РАДАРА\n\n"
        "Отправь одним сообщением параметры.\n\n"
        "Например:\n\n"
        "Kia Rio, до 700 000 ₽, "
        "от 2016 года, "
        "пробег до 200 000 км, Москва"
    )


async def radars(update, context):

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
            "📭 У тебя пока нет активных радаров."
        )

        return

    message = "🚨 ТВОИ РАДАРЫ\n\n"

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

        price_text = (
            f"{price:,}".replace(",", " ")
            if price
            else "—"
        )

        mileage_text = (
            f"{mileage:,}".replace(",", " ")
            if mileage
            else "—"
        )

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
    update,
    context
):

    text = update.message.text.strip()

    if context.user_data.get(
        "creating_radar"
    ):

        # Сохраняем радар
        price = None
        year = None
        mileage = None
        city = None

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

        year_match = re.search(
            r"от\s*(20\d{2})",
            text,
            re.IGNORECASE
        )

        if year_match:
            year = int(
                year_match.group(1)
            )

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

        await update.message.reply_text(
            "✅ РАДАР СОЗДАН!\n\n"
            f"🚗 {car}\n"
            f"💰 До {price:,} ₽\n"
            f"📅 От {year} года\n"
            f"📏 До {mileage:,} км\n"
            f"📍 {city}\n\n"
            "🔔 Автоматический мониторинг включён."
        )

        return

    await update.message.reply_text(
        "🤔 Я не понял команду.\n\n"
        "Используй /radar."
    )


# =========================
# ЗАПУСК
# =========================

def main():

    if not TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN не задан"
        )

    # Web server для Render
    threading.Thread(
        target=run_web,
        daemon=True
    ).start()

    # Telegram
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

    print("")
    print("====================================")
    print("🚗 AUTO RADAR BOT ЗАПУЩЕН")
    print("====================================")

    # Запускаем Telegram
    # после этого запускаем мониторинг
    monitor_thread = threading.Thread(
        target=monitor_avito,
        args=(telegram_app,),
        daemon=True
    )

    monitor_thread.start()

    telegram_app.run_polling()


if __name__ == "__main__":
    main()

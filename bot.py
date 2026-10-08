import os
import re
import json
import time
import requests

from html import unescape
from datetime import datetime, timezone

from flask import Flask

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# ============================================================
# НАСТРОЙКИ
# ============================================================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

RADARS_FILE = "radars.json"
SEEN_FILE = "seen_ads.json"
USERS_FILE = "users.json"

# Проверка каждые 5 минут
CHECK_INTERVAL = 5 * 60

# Максимальный возраст объявления
MAX_NEW_AGE_SECONDS = 5 * 60


# ============================================================
# КЛЮЧЕВЫЕ ФРАЗЫ СРОЧНОЙ ПРОДАЖИ
# ============================================================

URGENT_PHRASES = [
    "срочно",
    "срочная продажа",
    "срочно продам",
    "продам срочно",
    "очень срочно",
    "нужно срочно продать",
    "нужно срочно",
    "срочно нужны деньги",
    "срочно нужны средства",
    "нужны деньги",
    "нужны средства",
    "срочно нужны деньги на",
    "в связи с переездом",
    "в связи с обстоятельствами",
    "срочно освобождаю",
    "срочно продаю",
    "срочно отдам",
    "цена снижена срочно",
]


# ============================================================
# WEB SERVER ДЛЯ RENDER
# ============================================================

app_web = Flask(__name__)


@app_web.route("/")
def home():
    return "AUTO RADAR BOT IS RUNNING", 200


# ============================================================
# JSON
# ============================================================

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
    return load_json(RADARS_FILE, {})


def save_radars(radars):
    save_json(RADARS_FILE, radars)


def load_seen():
    return load_json(SEEN_FILE, [])


def save_seen(seen):
    save_json(SEEN_FILE, seen)


def load_users():
    return load_json(USERS_FILE, [])


def save_users(users):
    save_json(USERS_FILE, users)


# ============================================================
# ТЕКСТ
# ============================================================

def clean_text(value):
    if not value:
        return ""

    value = unescape(value)
    value = value.replace("\xa0", " ")
    value = value.replace("\\/", "/")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


# ============================================================
# ЧИСЛА
# ============================================================

def parse_number(value):
    if value is None:
        return None

    value = str(value)

    value = (
        value
        .replace("\xa0", "")
        .replace(" ", "")
        .replace("₽", "")
        .replace(",", "")
    )

    digits = re.sub(r"[^\d]", "", value)

    if not digits:
        return None

    try:
        return int(digits)
    except Exception:
        return None


# ============================================================
# ДАТА ПУБЛИКАЦИИ
# ============================================================

def parse_datetime_value(value):

    if value is None:
        return None

    value = str(value).strip()

    if value.isdigit():

        number = int(value)

        if number > 10_000_000_000:
            number = number / 1000

        if 1_000_000_000 < number < 2_000_000_000:
            return float(number)

    try:

        normalized = value.replace(
            "Z",
            "+00:00"
        )

        dt = datetime.fromisoformat(
            normalized
        )

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.timestamp()

    except Exception:
        pass

    return None


def extract_publish_time(block):

    if not block:
        return None

    patterns = [

        r'"datePublished"\s*:\s*"([^"]+)"',
        r'"dateCreated"\s*:\s*"([^"]+)"',
        r'"publishedAt"\s*:\s*"([^"]+)"',
        r'"createdAt"\s*:\s*"([^"]+)"',
        r'"publicationDate"\s*:\s*"([^"]+)"',
        r'"itemDateCreated"\s*:\s*"([^"]+)"',

        r'"datePublished"\s*:\s*(\d{10,13})',
        r'"dateCreated"\s*:\s*(\d{10,13})',
        r'"publishedAt"\s*:\s*(\d{10,13})',
        r'"createdAt"\s*:\s*(\d{10,13})',
        r'"publicationDate"\s*:\s*(\d{10,13})',
        r'"itemDateCreated"\s*:\s*(\d{10,13})',
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            block,
            re.IGNORECASE
        )

        if not match:
            continue

        timestamp = parse_datetime_value(
            match.group(1)
        )

        if timestamp:
            return timestamp

    return None


# ============================================================
# ПОЛУЧЕНИЕ ОПИСАНИЯ ОБЪЯВЛЕНИЯ
# ============================================================

def extract_description_from_html(text):

    if not text:
        return ""

    descriptions = []

    # JSON-LD description
    patterns = [

        r'"description"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"description"\s*:\s*\'((?:\\.|[^\'\\])*)\'',
        r'<meta[^>]+name="description"[^>]+content="([^"]+)"',
        r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"',

    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            text,
            re.IGNORECASE
        )

        for value in matches:

            value = clean_text(value)

            if len(value) >= 20:
                descriptions.append(value)

    if not descriptions:
        return ""

    # Берём самое длинное найденное описание
    descriptions.sort(
        key=len,
        reverse=True
    )

    description = descriptions[0]

    # Иногда JSON содержит экранированные символы
    description = (
        description
        .replace('\\"', '"')
        .replace("\\n", " ")
        .replace("\\r", " ")
        .replace("\\t", " ")
    )

    return clean_text(description)


def get_ad_description(url):

    if not url:
        return ""

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 "
            "Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9"
    }

    try:

        response = requests.get(
            url,
            headers=headers,
            timeout=20
        )

        if response.status_code != 200:
            print(
                "⚠️ Не удалось получить описание:",
                response.status_code
            )
            return ""

        description = extract_description_from_html(
            response.text
        )

        return description

    except Exception as e:

        print(
            "⚠️ Ошибка получения описания:",
            repr(e)
        )

        return ""


# ============================================================
# ПОИСК СРОЧНОЙ ПРОДАЖИ
# ============================================================

def detect_urgent_sale(description):

    if not description:
        return None

    text = clean_text(
        description
    ).lower()

    # Защита от явной фразы "не срочно"
    text = re.sub(
        r"\bне\s+срочно\b",
        "",
        text
    )

    for phrase in URGENT_PHRASES:

        if phrase in text:

            return phrase

    return None


# ============================================================
# AVITO URL
# ============================================================

def build_avito_url(radar):

    car = radar.get(
        "car",
        ""
    ).strip()

    if not car:
        car = "автомобиль"

    query = requests.utils.quote(
        car
    )

    # Поиск по России
    base = (
        "https://m.avito.ru/"
        "rossiya/avtomobili"
    )

    return f"{base}?q={query}"


# ============================================================
# ГОРОД
# ============================================================

def extract_city(block, href):

    source = (
        (block or "")
        + " "
        + (href or "")
    ).lower()

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
        "Иркутск",
        "Новосибирск",
        "Красноярск",
        "Челябинск",
        "Владивосток",
        "Хабаровск",
        "Саратов",
        "Тюмень",
        "Калининград",
        "Ярославль",
        "Белгород",
        "Волгоград",
        "Мурманск",
        "Ставрополь",
        "Барнаул",
    ]

    for city in cities:

        if city.lower() in source:
            return city

    return "Россия"


# ============================================================
# ПОЛУЧЕНИЕ AVITO
# ============================================================

def get_avito_ads(radar):

    print("")
    print("====================================")
    print("🔎 ПРОВЕРКА AVITO")
    print("====================================")

    url = build_avito_url(
        radar
    )

    print(
        "AVITO URL:",
        url
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 "
            "Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9"
    }

    try:

        response = requests.get(
            url,
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

        if response.status_code != 200:

            print(
                "❌ AVITO HTTP ERROR"
            )

            return []

        item_ids = re.findall(
            r'itemId[=:]\\?["\']?(\d{8,})',
            text
        )

        unique_ids = []

        for item_id in item_ids:

            if item_id not in unique_ids:
                unique_ids.append(
                    item_id
                )

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
                    position - 7000
                )

                block_end = min(
                    len(text),
                    position + 7000
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

            # ------------------------------------------------
            # ЦЕНА
            # ------------------------------------------------

            price = None

            if best_block:

                price_matches = re.findall(
                    r'(\d[\d\xa0\s]{2,})\s*₽',
                    best_block
                )

                prices = []

                for value in price_matches:

                    number = parse_number(
                        value
                    )

                    if (
                        number
                        and 50_000 <= number <= 50_000_000
                    ):
                        prices.append(
                            number
                        )

                if prices:
                    price = prices[0]

            # ------------------------------------------------
            # ГОД
            # ------------------------------------------------

            year = None

            year_match = re.search(
                r'\b(20\d{2})\b',
                best_title
            )

            if year_match:

                year = int(
                    year_match.group(1)
                )

            # ------------------------------------------------
            # ПРОБЕГ
            # ------------------------------------------------

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

            # ------------------------------------------------
            # ГОРОД
            # ------------------------------------------------

            city = extract_city(
                best_block,
                best_href
            )

            # ------------------------------------------------
            # ССЫЛКА
            # ------------------------------------------------

            if best_href:

                if best_href.startswith(
                    "http"
                ):

                    ad_url = best_href

                else:

                    ad_url = (
                        "https://www.avito.ru"
                        + best_href
                    )

            else:

                ad_url = (
                    "https://www.avito.ru/"
                    "rossiya/avtomobili/"
                    + item_id
                )

            # ------------------------------------------------
            # ВРЕМЯ ПУБЛИКАЦИИ
            # ------------------------------------------------

            published_at = extract_publish_time(
                best_block or ""
            )

            ads.append({
                "id": item_id,
                "title": best_title,
                "price": price,
                "year": year,
                "mileage": mileage,
                "city": city,
                "url": ad_url,
                "published_at": published_at,
                "description": "",
                "urgent_phrase": None
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


# ============================================================
# СООТВЕТСТВИЕ РАДАРУ
# ============================================================

def matches_radar(ad, radar):

    title = (
        ad.get(
            "title",
            ""
        )
        .lower()
    )

    car = (
        radar.get(
            "car",
            ""
        )
        .lower()
        .strip()
    )

    # ------------------------------------------------
    # МОДЕЛЬ
    # ------------------------------------------------

    if car:

        words = car.split()

        for word in words:

            if len(word) < 2:
                continue

            if word not in title:
                return False

    # ------------------------------------------------
    # БИТЫЕ
    # ------------------------------------------------

    bad_words = [
        "битый",
        "битая",
        "битое",
        "после дтп",
        "дтп",
        "аварийный",
        "на запчасти"
    ]

    for word in bad_words:

        if word in title:
            return False

    # ------------------------------------------------
    # ЦЕНА
    # ------------------------------------------------

    price = ad.get(
        "price"
    )

    max_price = radar.get(
        "price"
    )

    if max_price is not None:

        if price is None:
            return False

        if price > max_price:
            return False

    # ------------------------------------------------
    # ГОД
    # ------------------------------------------------

    year = ad.get(
        "year"
    )

    min_year = radar.get(
        "year"
    )

    if min_year is not None:

        if year is None:
            return False

        if year < min_year:
            return False

    # ------------------------------------------------
    # ПРОБЕГ
    # ------------------------------------------------

    mileage = ad.get(
        "mileage"
    )

    max_mileage = radar.get(
        "mileage"
    )

    if max_mileage is not None:

        if mileage is None:
            return False

        if mileage > max_mileage:
            return False

    # ------------------------------------------------
    # ГОРОД
    # ------------------------------------------------

    radar_city = radar.get(
        "city"
    )

    if radar_city:

        if radar_city.lower() not in [
            "вся россия",
            "россия",
            "все регионы"
        ]:

            ad_city = (
                ad.get(
                    "city",
                    ""
                )
                .lower()
            )

            if radar_city.lower() not in ad_city:
                return False

    return True


# ============================================================
# ПРОВЕРКА СВЕЖЕСТИ
# ============================================================

def is_new_ad(ad):

    published_at = ad.get(
        "published_at"
    )

    if not published_at:
        return False

    age = time.time() - published_at

    # В будущем более чем на 2 минуты —
    # подозрительная дата
    if age < -120:
        return False

    # Старше 5 минут — не отправляем
    if age > MAX_NEW_AGE_SECONDS:
        return False

    # Отрицательный возраст в пределах
    # двух минут допускаем
    return True


# ============================================================
# ФОРМАТ СООБЩЕНИЯ
# ============================================================

def format_ad(ad):

    price = ad.get(
        "price"
    )

    if price:

        price_text = (
            f"{price:,}"
            .replace(",", " ")
            + " ₽"
        )

    else:

        price_text = (
            "Цена не указана"
        )

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
        "Россия"
    )

    title = ad.get(
        "title",
        "Автомобиль"
    )

    url = ad.get(
        "url",
        ""
    )

    urgent_phrase = ad.get(
        "urgent_phrase"
    )

    if urgent_phrase:

        urgent_block = (
            "\n🚨 СРОЧНАЯ ПРОДАЖА\n"
            f"⚠️ Найдено в описании: "
            f"«{urgent_phrase}»\n"
        )

    else:

        urgent_block = ""

    return (
        "🚨 НОВОЕ ОБЪЯВЛЕНИЕ!\n\n"
        f"🚗 {title}\n"
        f"💰 Цена: {price_text}\n"
        f"📅 Год: {year}\n"
        f"📏 Пробег: {mileage_text}\n"
        f"📍 {city}\n"
        f"{urgent_block}\n"
        f"🔗 {url}"
    )


# ============================================================
# МОНИТОРИНГ
# ============================================================

async def monitor_job(context):

    print("")
    print("====================================")
    print("🔄 АВТОМАТИЧЕСКАЯ ПРОВЕРКА")
    print("====================================")

    all_radars = load_radars()

    if not all_radars:

        print(
            "📭 Нет активных радаров"
        )

        return

    seen = load_seen()

    # ------------------------------------------------
    # Каждый пользователь
    # ------------------------------------------------

    for user_id, user_radars in all_radars.items():

        if not user_radars:
            continue

        print("")
        print(
            "👤 Пользователь:",
            user_id
        )

        # ------------------------------------------------
        # Каждый радар
        # ------------------------------------------------

        for radar_index, radar in enumerate(
            user_radars,
            start=1
        ):

            print("")
            print(
                f"🔎 Радар #{radar_index}:",
                radar.get("car")
            )

            ads = get_avito_ads(
                radar
            )

            if not ads:

                print(
                    "⚠️ Объявления не получены"
                )

                continue

            for ad in ads:

                item_id = ad.get(
                    "id"
                )

                if not item_id:
                    continue

                # Для каждого пользователя
                # своё состояние "уже отправлено"
                seen_key = (
                    f"{user_id}:{item_id}"
                )

                if seen_key in seen:
                    continue

                # Проверяем соответствие радара
                if not matches_radar(
                    ad,
                    radar
                ):
                    continue

                # Проверяем, что объявление
                # действительно свежее
                if not is_new_ad(
                    ad
                ):
                    continue

                # ------------------------------------------------
                # ПОЛУЧАЕМ ОПИСАНИЕ
                # ------------------------------------------------

                print(
                    "📖 Получаю описание:",
                    item_id
                )

                description = get_ad_description(
                    ad.get("url")
                )

                ad["description"] = (
                    description
                )

                # ------------------------------------------------
                # ИЩЕМ СРОЧНОСТЬ
                # ------------------------------------------------

                urgent_phrase = detect_urgent_sale(
                    description
                )

                ad["urgent_phrase"] = (
                    urgent_phrase
                )

                if urgent_phrase:

                    print(
                        "🚨 НАЙДЕНА СРОЧНОСТЬ:",
                        urgent_phrase
                    )

                # ------------------------------------------------
                # СОЗДАЁМ СООБЩЕНИЕ
                # ------------------------------------------------

                message = format_ad(
                    ad
                )

                try:

                    await context.bot.send_message(
                        chat_id=int(user_id),
                        text=message
                    )

                    print(
                        "📲 Уведомление отправлено:",
                        item_id
                    )

                    # Запоминаем только после
                    # успешной отправки
                    seen.append(
                        seen_key
                    )

                except Exception as e:

                    print(
                        "❌ Ошибка Telegram:",
                        repr(e)
                    )

    # Не даём файлу расти бесконечно
    if len(seen) > 20000:

        seen = seen[-10000:]

    save_seen(
        seen
    )

    print("")
    print(
        "✅ Проверка завершена."
    )

    print(
        "⏱ Следующая проверка через 5 минут."
    )


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = (
        update.effective_chat.id
    )

    users = load_users()

    if chat_id not in users:

        users.append(
            chat_id
        )

        save_users(
            users
        )

        print(
            "👤 Новый пользователь:",
            chat_id
        )

    await update.message.reply_text(
        "🚗 AUTO RADAR\n\n"
        "Бот работает.\n\n"
        "🔎 /radar — создать радар\n"
        "📋 /radars — мои радары\n"
        "🗑 /delete 2 — удалить радар №2\n"
        "❓ /help — помощь"
    )


# ============================================================
# HELP
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🔎 AUTO RADAR\n\n"
        "Команды:\n\n"
        "/radar — создать новый радар\n"
        "/radars — показать мои радары\n"
        "/delete 2 — удалить радар №2\n"
        "/help — помощь\n\n"
        "Пример:\n\n"
        "Kia Rio, до 700000 ₽, "
        "от 2016 года, "
        "пробег до 200000 км, "
        "вся Россия\n\n"
        "Если указать город, "
        "бот будет учитывать его.\n\n"
        "🚨 Бот также ищет признаки "
        "срочной продажи в описании."
    )


# ============================================================
# СОЗДАНИЕ РАДАРА
# ============================================================

async def radar(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data[
        "creating_radar"
    ] = True

    await update.message.reply_text(
        "🚨 СОЗДАНИЕ РАДАРА\n\n"
        "Отправь параметры одним сообщением.\n\n"
        "Например:\n\n"
        "Kia Rio, до 700000 ₽, "
        "от 2016 года, "
        "пробег до 200000 км, "
        "вся Россия\n\n"
        "Или для конкретного города:\n\n"
        "Kia Rio, до 700000 ₽, "
        "от 2016 года, "
        "пробег до 200000 км, "
        "Москва"
    )


# ============================================================
# СПИСОК РАДАРОВ
# ============================================================

async def radars(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

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

        city = radar_data.get(
            "city"
        )

        if not city:
            city = "Вся Россия"

        message += (
            f"🔎 Радар #{index}\n"
            f"🚗 {radar_data.get('car', '—')}\n"
            f"💰 до {price_text} ₽\n"
            f"📅 от {radar_data.get('year', '—')}\n"
            f"📏 до {mileage_text} км\n"
            f"📍 {city}\n\n"
        )

    message += (
        "🗑 Чтобы удалить радар:\n"
        "/delete 2"
    )

    await update.message.reply_text(
        message
    )


# ============================================================
# УДАЛЕНИЕ РАДАРА
# ============================================================

async def delete_radar(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = str(
        update.effective_user.id
    )

    if not context.args:

        await update.message.reply_text(
            "❌ Укажи номер радара.\n\n"
            "Например:\n"
            "/delete 2"
        )

        return

    try:

        radar_number = int(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ Номер радара должен быть числом.\n\n"
            "Например:\n"
            "/delete 2"
        )

        return

    all_radars = load_radars()

    user_radars = all_radars.get(
        user_id,
        []
    )

    if not user_radars:

        await update.message.reply_text(
            "📭 У тебя нет активных радаров."
        )

        return

    if (
        radar_number < 1
        or radar_number > len(user_radars)
    ):

        await update.message.reply_text(
            f"❌ Радара №{radar_number} нет.\n\n"
            f"У тебя сейчас радаров: "
            f"{len(user_radars)}."
        )

        return

    deleted_radar = user_radars.pop(
        radar_number - 1
    )

    all_radars[user_id] = user_radars

    save_radars(
        all_radars
    )

    city = deleted_radar.get(
        "city"
    )

    if not city:
        city = "Вся Россия"

    await update.message.reply_text(
        "🗑 РАДАР УДАЛЁН!\n\n"
        f"🚗 {deleted_radar.get('car', '—')}\n"
        f"💰 До {deleted_radar.get('price') or '—'} ₽\n"
        f"📅 От {deleted_radar.get('year') or '—'} года\n"
        f"📏 До {deleted_radar.get('mileage') or '—'} км\n"
        f"📍 {city}"
    )


# ============================================================
# ПОЛУЧЕНИЕ РАДАРА ИЗ СООБЩЕНИЯ
# ============================================================

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

    # ------------------------------------------------
    # ЦЕНА
    # ------------------------------------------------

    price = None

    price_match = re.search(
        r"до\s*([\d\s]+)",
        text,
        re.IGNORECASE
    )

    if price_match:

        price = parse_number(
            price_match.group(1)
        )

    # ------------------------------------------------
    # ГОД
    # ------------------------------------------------

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

    # ------------------------------------------------
    # ПРОБЕГ
    # ------------------------------------------------

    mileage = None

    mileage_match = re.search(
        r"пробег\s*до\s*([\d\s]+)",
        text,
        re.IGNORECASE
    )

    if mileage_match:

        mileage = parse_number(
            mileage_match.group(1)
        )

    # ------------------------------------------------
    # ГОРОД
    # ------------------------------------------------

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
        "Иркутск",
        "Новосибирск",
        "Красноярск",
        "Челябинск",
        "Владивосток",
        "Хабаровск",
        "Саратов",
        "Тюмень",
        "Калининград",
        "Ярославль",
        "Белгород",
        "Волгоград",
        "Мурманск",
        "Ставрополь",
        "Барнаул",
    ]

    city = None

    text_lower = text.lower()

    if (
        "вся россия" not in text_lower
        and "россия" not in text_lower
        and "все регионы" not in text_lower
    ):

        for city_name in cities:

            if city_name.lower() in text_lower:

                city = city_name

                break

    # ------------------------------------------------
    # АВТОМОБИЛЬ
    # ------------------------------------------------

    parts = [
        part.strip()
        for part in text.split(",")
    ]

    car = (
        parts[0]
        if parts
        else text
    )

    # ------------------------------------------------
    # РАДАР
    # ------------------------------------------------

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
        f"{price:,}".replace(",", " ")
        if price
        else "—"
    )

    mileage_text = (
        f"{mileage:,}".replace(",", " ")
        if mileage
        else "—"
    )

    city_text = (
        city
        if city
        else "Вся Россия"
    )

    await update.message.reply_text(
        "✅ РАДАР СОЗДАН!\n\n"
        f"🚗 {car}\n"
        f"💰 До {price_text} ₽\n"
        f"📅 От {year or '—'} года\n"
        f"📏 До {mileage_text} км\n"
        f"📍 {city_text}\n\n"
        "🔔 Радар сохранён.\n\n"
        "⏱ Проверка новых объявлений — каждые 5 минут.\n"
        "🚨 Также проверяется описание на признаки срочной продажи."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if not TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN не задан"
        )

    # ------------------------------------------------
    # Flask для Render
    # ------------------------------------------------

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

    # ------------------------------------------------
    # Telegram
    # ------------------------------------------------

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
        CommandHandler(
            "delete",
            delete_radar
        )
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            handle_message
        )
    )

    # ------------------------------------------------
    # АВТОМАТИЧЕСКАЯ ПРОВЕРКА
    # ------------------------------------------------

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
    print("🚨 АВТОМАТИЧЕСКИЙ РАДАР ЗАПУЩЕН")
    print("⏱ Проверка каждые 5 минут")
    print("🇷🇺 Режим поиска: Вся Россия")
    print("🆕 Отправка: только свежие объявления")
    print("🚨 Поиск срочной продажи в описании")
    print("====================================")

    telegram_app.run_polling()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()

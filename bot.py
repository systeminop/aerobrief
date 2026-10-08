import os
import json
import time
import re
import threading
from datetime import datetime, timezone

import requests
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
USERS_FILE = "users.json"
SEEN_FILE = "seen_ads.json"

CHECK_INTERVAL = 5 * 60
MAX_NEW_AGE_SECONDS = 5 * 60

# =========================================================
# СОСТОЯНИЕ БОТА
# =========================================================

STATUS = {
    "started_at": None,
    "last_check": None,
    "last_check_result": "Проверок ещё не было",
    "last_error": None,
    "last_found": 0,
    "last_sent": 0,
    "checks_count": 0,
}

STATUS_LOCK = threading.Lock()

# =========================================================
# СРОЧНАЯ ПРОДАЖА
# =========================================================

URGENT_PHRASES = [
    "срочно",
    "срочная продажа",
    "срочно продам",
    "продам срочно",
    "очень срочно",
    "нужно срочно продать",
    "нужно срочно",
    "срочно нужны деньги",
    "нужны деньги",
    "срочно освобождаю",
    "срочно продаю",
    "срочно отдам",
    "цена снижена срочно",
    "в связи с переездом",
    "в связи с обстоятельствами",
]

# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "AUTO RADAR BOT IS RUNNING"


def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


# =========================================================
# JSON
# =========================================================

def load_json(filename, default):
    try:
        if not os.path.exists(filename):
            return default

        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as e:
        print(f"JSON LOAD ERROR {filename}: {e}")
        return default


def save_json(filename, data):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )
    except Exception as e:
        print(f"JSON SAVE ERROR {filename}: {e}")


# =========================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================================================

def clean_text(value):
    if not value:
        return ""

    value = re.sub(r"<[^>]+>", " ", str(value))
    value = value.replace("&nbsp;", " ")
    value = value.replace("&quot;", '"')
    value = value.replace("&#39;", "'")
    value = value.replace("&amp;", "&")

    value = re.sub(r"\s+", " ", value)

    return value.strip()


def parse_number(value):
    if value is None:
        return None

    value = str(value)
    value = value.replace(" ", "")
    value = value.replace("\xa0", "")

    numbers = re.findall(r"\d+", value)

    if not numbers:
        return None

    try:
        return int("".join(numbers))
    except Exception:
        return None


def parse_datetime_value(value):
    if not value:
        return None

    try:
        if isinstance(value, (int, float)):
            timestamp = float(value)

            if timestamp > 10_000_000_000:
                timestamp /= 1000

            return timestamp

        value = str(value).strip()

        if value.isdigit():
            timestamp = float(value)

            if timestamp > 10_000_000_000:
                timestamp /= 1000

            return timestamp

        value = value.replace("Z", "+00:00")

        dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.timestamp()

    except Exception:
        return None


# =========================================================
# ПУБЛИКАЦИЯ ОБЪЯВЛЕНИЯ
# =========================================================

def extract_publish_time(html_block):
    patterns = [
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'"dateCreated"\s*:\s*"([^"]+)"',
        r'"createdAt"\s*:\s*"([^"]+)"',
        r'"publishDate"\s*:\s*"([^"]+)"',
        r'"publishedAt"\s*:\s*"([^"]+)"',
    ]

    for pattern in patterns:
        match = re.search(pattern, html_block, re.I)

        if match:
            timestamp = parse_datetime_value(match.group(1))

            if timestamp:
                return timestamp

    return None


# =========================================================
# ГОРОД
# =========================================================

def extract_city(text):
    if not text:
        return ""

    cities = [
        "Москва",
        "Санкт-Петербург",
        "Казань",
        "Самара",
        "Уфа",
        "Пермь",
        "Омск",
        "Тула",
        "Тверь",
        "Воронеж",
        "Ростов-на-Дону",
        "Краснодар",
        "Сочи",
        "Волгоград",
        "Нижний Новгород",
        "Екатеринбург",
        "Челябинск",
        "Новосибирск",
        "Красноярск",
        "Иркутск",
        "Владивосток",
        "Хабаровск",
        "Оренбург",
        "Пенза",
        "Рязань",
        "Калуга",
        "Тамбов",
        "Курск",
        "Белгород",
        "Брянск",
        "Смоленск",
        "Ярославль",
        "Тюмень",
        "Киров",
        "Саратов",
        "Астрахань",
        "Мурманск",
        "Архангельск",
        "Сургут",
        "Вологда",
        "Липецк",
        "Томск",
        "Барнаул",
        "Кемерово",
        "Ставрополь",
        "Саранск",
        "Ижевск",
        "Чебоксары",
        "Владимир",
    ]

    text_lower = text.lower()

    for city in cities:
        if city.lower() in text_lower:
            return city

    return ""


# =========================================================
# URL AVITO
# =========================================================

def build_avito_url(radar):
    car = radar.get("car", "")

    return (
        "https://m.avito.ru/rossiya/avtomobili"
        "?q=" + requests.utils.quote(car)
    )


# =========================================================
# AVITO
# =========================================================

def get_avito_ads(radar):
    url = build_avito_url(radar)

    print()
    print("====================================")
    print("🔎 ПРОВЕРКА AVITO")
    print("====================================")
    print("AVITO URL:", url)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=30
        )

        print("AVITO STATUS:", response.status_code)
        print("AVITO HTML LENGTH:", len(response.text))

        if response.status_code == 429:
            print("❌ AVITO 429 — СЕРВЕР AVITO ОГРАНИЧИЛ ЗАПРОСЫ")

            with STATUS_LOCK:
                STATUS["last_error"] = (
                    "Avito вернул HTTP 429 — запросы ограничены"
                )

            return []

        if response.status_code != 200:
            print("❌ AVITO HTTP ERROR")

            with STATUS_LOCK:
                STATUS["last_error"] = (
                    f"Avito HTTP {response.status_code}"
                )

            return []

        html = response.text

        ads = []

        # -------------------------------------------------
        # Ищем ID объявлений
        # -------------------------------------------------

        ids = re.findall(
            r'"(?:id|itemId)"\s*:\s*"?(\\?\d{7,12})"?',
            html
        )

        # Дополнительный поиск ID в ссылках
        ids += re.findall(
            r'/avito/[^"\']*_(\d{7,12})',
            html
        )

        ids = list(dict.fromkeys(ids))

        print("НАЙДЕНО ID:", len(ids))

        # -------------------------------------------------
        # Пытаемся найти карточки вокруг ID
        # -------------------------------------------------

        for item_id in ids[:100]:

            try:
                pos = html.find(item_id)

                if pos == -1:
                    continue

                start = max(0, pos - 12000)
                end = min(len(html), pos + 12000)

                block = html[start:end]

                title = ""

                title_patterns = [
                    r'"title"\s*:\s*"([^"]+)"',
                    r'"name"\s*:\s*"([^"]+)"',
                ]

                for pattern in title_patterns:
                    match = re.search(pattern, block, re.I)

                    if match:
                        title = clean_text(match.group(1))
                        break

                if not title:
                    continue

                year = None

                year_match = re.search(
                    r'\b(19[9]\d|20[0-2]\d)\b',
                    title
                )

                if year_match:
                    year = int(year_match.group(1))

                mileage = None

                mileage_match = re.search(
                    r'(\d[\d\s]{2,8})\s*км',
                    block,
                    re.I
                )

                if mileage_match:
                    mileage = parse_number(
                        mileage_match.group(1)
                    )

                price = None

                price_patterns = [
                    r'"price"\s*:\s*\{[^}]*?"value"\s*:\s*(\d+)',
                    r'"price"\s*:\s*(\d+)',
                    r'(\d[\d\s]{3,9})\s*₽',
                ]

                for pattern in price_patterns:

                    match = re.search(
                        pattern,
                        block,
                        re.I
                    )

                    if match:
                        price = parse_number(
                            match.group(1)
                        )
                        break

                city = extract_city(block)

                published_at = extract_publish_time(block)

                ad_url = (
                    f"https://www.avito.ru/rossiya/avtomobili/"
                    f"{item_id}"
                )

                ads.append({
                    "id": str(item_id),
                    "title": title,
                    "price": price,
                    "year": year,
                    "mileage": mileage,
                    "city": city,
                    "url": ad_url,
                    "published_at": published_at,
                    "description": "",
                    "urgent_phrase": None,
                })

            except Exception as e:
                print(
                    "Ошибка обработки объявления:",
                    item_id,
                    e
                )

        # Убираем дубли
        unique = {}

        for ad in ads:
            unique[ad["id"]] = ad

        ads = list(unique.values())

        print("📦 ОБЪЯВЛЕНИЙ ПОСЛЕ ПАРСИНГА:", len(ads))

        return ads

    except Exception as e:

        print("❌ AVITO REQUEST ERROR:", e)

        with STATUS_LOCK:
            STATUS["last_error"] = str(e)

        return []


# =========================================================
# ОПИСАНИЕ ОБЪЯВЛЕНИЯ
# =========================================================

def extract_description_from_html(html):
    patterns = [
        r'"description"\s*:\s*"([^"]+)"',
        r'"descriptionHtml"\s*:\s*"([^"]+)"',
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            html,
            re.I
        )

        if match:
            return clean_text(
                match.group(1)
            )

    return ""


def get_ad_description(ad):
    try:

        response = requests.get(
            ad["url"],
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"
                )
            },
            timeout=20
        )

        if response.status_code != 200:
            return ""

        return extract_description_from_html(
            response.text
        )

    except Exception:
        return ""


# =========================================================
# СРОЧНАЯ ПРОДАЖА
# =========================================================

def detect_urgent_sale(text):

    if not text:
        return None

    text = text.lower()

    for phrase in URGENT_PHRASES:

        if phrase in text:
            return phrase

    return None


# =========================================================
# ФИЛЬТР РАДАРА
# =========================================================

def matches_radar(ad, radar):

    # -----------------------------
    # Цена
    # -----------------------------

    price = ad.get("price")

    price_to = radar.get("price_to")

    if price_to is not None:

        if price is None:
            return False

        if price > price_to:
            return False

    price_from = radar.get("price_from")

    if price_from is not None:

        if price is None:
            return False

        if price < price_from:
            return False

    # -----------------------------
    # Год
    # -----------------------------

    year = ad.get("year")

    year_from = radar.get("year_from")

    if year_from is not None:

        if year is None:
            return False

        if year < year_from:
            return False

    year_to = radar.get("year_to")

    if year_to is not None:

        if year is None:
            return False

        if year > year_to:
            return False

    # -----------------------------
    # Пробег
    # -----------------------------

    mileage = ad.get("mileage")

    mileage_to = radar.get("mileage_to")

    if mileage_to is not None:

        if mileage is None:
            return False

        if mileage > mileage_to:
            return False

    # -----------------------------
    # Город
    # -----------------------------

    radar_city = radar.get("city")

    if radar_city:

        ad_city = (
            ad.get("city") or ""
        ).lower()

        if radar_city.lower() not in ad_city:
            return False

    return True


# =========================================================
# НОВОЕ ОБЪЯВЛЕНИЕ
# =========================================================

def is_new_ad(ad):

    published_at = ad.get("published_at")

    if not published_at:
        return False

    now = time.time()

    age = now - published_at

    # Будущее с небольшим запасом
    if age < -120:
        return False

    # Старше 5 минут
    if age > MAX_NEW_AGE_SECONDS:
        return False

    return True


# =========================================================
# ФОРМАТ СООБЩЕНИЯ
# =========================================================

def format_ad(ad):

    text = "🚗 НОВОЕ ОБЪЯВЛЕНИЕ\n\n"

    text += f"🚘 {ad.get('title') or 'Автомобиль'}\n"

    if ad.get("price"):
        text += (
            f"💰 Цена: "
            f"{ad['price']:,}".replace(",", " ")
            + " ₽\n"
        )

    if ad.get("year"):
        text += f"📅 Год: {ad['year']}\n"

    if ad.get("mileage"):
        text += (
            f"🛣 Пробег: "
            f"{ad['mileage']:,}".replace(",", " ")
            + " км\n"
        )

    if ad.get("city"):
        text += f"📍 Город: {ad['city']}\n"

    if ad.get("urgent_phrase"):
        text += "\n🚨 СРОЧНАЯ ПРОДАЖА\n"
        text += (
            f"Найдено: «{ad['urgent_phrase']}»\n"
        )

    text += "\n🔗 "
    text += ad.get("url", "")

    return text


# =========================================================
# РАДАРЫ
# =========================================================

def get_user_radars(user_id):

    radars = load_json(
        RADARS_FILE,
        {}
    )

    return radars.get(
        str(user_id),
        []
    )


def save_user_radars(user_id, user_radars):

    radars = load_json(
        RADARS_FILE,
        {}
    )

    radars[str(user_id)] = user_radars

    save_json(
        RADARS_FILE,
        radars
    )


# =========================================================
# /START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    users = load_json(
        USERS_FILE,
        []
    )

    if user_id not in users:
        users.append(user_id)

        save_json(
            USERS_FILE,
            users
        )

    await update.message.reply_text(
        "🚗 AUTO RADAR\n\n"
        "Бот работает.\n\n"
        "Команды:\n"
        "/radar — создать радар\n"
        "/radars — мои радары\n"
        "/delete 2 — удалить радар №2\n"
        "/test — тест уведомлений\n"
        "/status — состояние бота\n"
        "/help — помощь"
    )


# =========================================================
# /HELP
# =========================================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🚗 AUTO RADAR — команды\n\n"

        "/radar\n"
        "Создать новый радар.\n\n"

        "/radars\n"
        "Показать все мои радары.\n\n"

        "/delete 2\n"
        "Удалить радар №2.\n\n"

        "/test\n"
        "Проверить отправку уведомлений.\n\n"

        "/status\n"
        "Показать состояние автоматического радара.\n\n"

        "Пример радара:\n"
        "Kia Rio, до 700000, от 2016, "
        "пробег до 200000, Москва"
    )


# =========================================================
# /TEST
# =========================================================

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🧪 AUTO RADAR TEST\n\n"
        "✅ Telegram работает.\n"
        "✅ Бот может отправлять сообщения.\n\n"
        "Если ты видишь это сообщение — "
        "система уведомлений работает."
    )


# =========================================================
# /STATUS
# =========================================================

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    radars = get_user_radars(user_id)

    with STATUS_LOCK:
        last_check = STATUS["last_check"]
        last_result = STATUS["last_check_result"]
        last_error = STATUS["last_error"]
        last_found = STATUS["last_found"]
        last_sent = STATUS["last_sent"]
        checks_count = STATUS["checks_count"]

    if last_check:
        last_check_text = datetime.fromtimestamp(
            last_check
        ).strftime(
            "%d.%m.%Y %H:%M:%S"
        )
    else:
        last_check_text = "ещё не было"

    text = (
        "📊 AUTO RADAR STATUS\n\n"
        "🟢 Telegram: работает\n"
        "🟢 Render: работает\n"
        "⏱ Интервал: 5 минут\n"
        "🇷🇺 Режим: вся Россия\n\n"
        f"🔎 Твоих радаров: {len(radars)}\n"
        f"🔄 Проверок выполнено: {checks_count}\n"
        f"🕐 Последняя проверка: {last_check_text}\n"
        f"📦 Найдено объявлений: {last_found}\n"
        f"📨 Отправлено: {last_sent}\n\n"
        f"📌 Результат:\n{last_result}"
    )

    if last_error:
        text += (
            "\n\n⚠️ Последняя ошибка:\n"
            f"{last_error}"
        )

    await update.message.reply_text(text)


# =========================================================
# /RADARS
# =========================================================

async def radars_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    radars = get_user_radars(user_id)

    if not radars:

        await update.message.reply_text(
            "📭 У тебя пока нет активных радаров."
        )

        return

    text = "🔎 ТВОИ РАДАРЫ\n\n"

    for index, radar in enumerate(
        radars,
        start=1
    ):

        text += f"#{index} — {radar.get('car')}\n"

        if radar.get("price_from") is not None:
            text += (
                f"💰 от {radar['price_from']:,} ₽\n"
                .replace(",", " ")
            )

        if radar.get("price_to") is not None:
            text += (
                f"💰 до {radar['price_to']:,} ₽\n"
                .replace(",", " ")
            )

        if radar.get("year_from") is not None:
            text += (
                f"📅 от {radar['year_from']}\n"
            )

        if radar.get("year_to") is not None:
            text += (
                f"📅 до {radar['year_to']}\n"
            )

        if radar.get("mileage_to") is not None:
            text += (
                f"🛣 до {radar['mileage_to']:,} км\n"
                .replace(",", " ")
            )

        if radar.get("city"):
            text += (
                f"📍 {radar['city']}\n"
            )

        text += "\n"

    await update.message.reply_text(text)


# =========================================================
# /DELETE
# =========================================================

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if not context.args:

        await update.message.reply_text(
            "Напиши номер радара.\n\n"
            "Например:\n"
            "/delete 2"
        )

        return

    try:
        number = int(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ Номер радара должен быть числом."
        )

        return

    radars = get_user_radars(user_id)

    if number < 1 or number > len(radars):

        await update.message.reply_text(
            "❌ Такого радара нет."
        )

        return

    deleted = radars.pop(
        number - 1
    )

    save_user_radars(
        user_id,
        radars
    )

    await update.message.reply_text(
        f"🗑 Радар #{number} удалён.\n"
        f"Модель: {deleted.get('car')}"
    )


# =========================================================
# /RADAR
# =========================================================

async def radar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🔎 Создание радара\n\n"
        "Напиши одной строкой, например:\n\n"
        "Kia Rio, до 700000, от 2016, "
        "пробег до 200000, Москва\n\n"
        "Если город не указать — ищем по всей России."
    )


# =========================================================
# СОЗДАНИЕ РАДАРА ИЗ СООБЩЕНИЯ
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text.strip()

    if not text:
        return

    if text.startswith("/"):
        return

    user_id = update.effective_user.id

    # -----------------------------------------------------
    # Проверяем, похоже ли сообщение на создание радара
    # -----------------------------------------------------

    if "," not in text:
        return

    parts = [
        p.strip()
        for p in text.split(",")
    ]

    if not parts:
        return

    car = parts[0]

    radar = {
        "car": car,
        "price_from": None,
        "price_to": None,
        "year_from": None,
        "year_to": None,
        "mileage_to": None,
        "city": None,
    }

    for part in parts[1:]:

        low = part.lower()

        # Цена ДО
        if "до" in low and (
            "₽" in low
            or "руб" in low
            or re.search(r"\d", low)
        ):
            number = parse_number(part)

            if number:
                radar["price_to"] = number
                continue

        # Цена ОТ
        if "от" in low and (
            "₽" in low
            or "руб" in low
        ):
            number = parse_number(part)

            if number:
                radar["price_from"] = number
                continue

        # Год ОТ
        if "от" in low and "пробег" not in low:

            number = parse_number(part)

            if number and 1900 <= number <= 2030:
                radar["year_from"] = number
                continue

        # Год ДО
        if "до" in low and "пробег" not in low:

            number = parse_number(part)

            if number and 1900 <= number <= 2030:
                radar["year_to"] = number
                continue

        # Пробег
        if "пробег" in low:

            number = parse_number(part)

            if number:
                radar["mileage_to"] = number
                continue

        # Город
        if any(
            letter.isalpha()
            for letter in part
        ):

            if low not in [
                "до",
                "от",
                "руб",
                "₽",
            ]:

                radar["city"] = part

    # -----------------------------------------------------
    # Сохраняем
    # -----------------------------------------------------

    radars = get_user_radars(user_id)

    radars.append(radar)

    save_user_radars(
        user_id,
        radars
    )

    # -----------------------------------------------------
    # Показываем
    # -----------------------------------------------------

    text_reply = (
        "✅ РАДАР СОЗДАН\n\n"
        f"🚘 {radar['car']}\n"
    )

    if radar["price_from"] is not None:
        text_reply += (
            f"💰 Цена от: "
            f"{radar['price_from']:,} ₽\n"
            .replace(",", " ")
        )

    if radar["price_to"] is not None:
        text_reply += (
            f"💰 Цена до: "
            f"{radar['price_to']:,} ₽\n"
            .replace(",", " ")
        )

    if radar["year_from"] is not None:
        text_reply += (
            f"📅 Год от: "
            f"{radar['year_from']}\n"
        )

    if radar["year_to"] is not None:
        text_reply += (
            f"📅 Год до: "
            f"{radar['year_to']}\n"
        )

    if radar["mileage_to"] is not None:
        text_reply += (
            f"🛣 Пробег до: "
            f"{radar['mileage_to']:,} км\n"
            .replace(",", " ")
        )

    if radar["city"]:
        text_reply += (
            f"📍 Город: "
            f"{radar['city']}\n"
        )
    else:
        text_reply += (
            "🇷🇺 Регион: вся Россия\n"
        )

    text_reply += (
        "\n⏱ Проверка каждые 5 минут.\n"
        "🆕 Отправляются только объявления "
        "моложе 5 минут."
    )

    await update.message.reply_text(
        text_reply
    )


# =========================================================
# АВТОМАТИЧЕСКИЙ РАДАР
# =========================================================

async def monitor_job(
    context: ContextTypes.DEFAULT_TYPE
):

    print()
    print("====================================")
    print("🔄 АВТОМАТИЧЕСКАЯ ПРОВЕРКА")
    print("====================================")

    check_start = time.time()

    users = load_json(
        USERS_FILE,
        []
    )

    seen = load_json(
        SEEN_FILE,
        []
    )

    total_found = 0
    total_sent = 0
    had_error = False

    for user_id in users:

        print()
        print("👤 Пользователь:", user_id)

        radars = get_user_radars(
            user_id
        )

        if not radars:

            print("📭 Нет активных радаров")
            continue

        for index, radar in enumerate(
            radars,
            start=1
        ):

            print()
            print(
                f"🔎 Радар #{index}: "
                f"{radar.get('car')}"
            )

            ads = get_avito_ads(
                radar
            )

            if not ads:

                had_error = True

                print(
                    "⚠️ Объявления не получены"
                )

                continue

            for ad in ads:

                if not matches_radar(
                    ad,
                    radar
                ):
                    continue

                if not is_new_ad(ad):
                    continue

                total_found += 1

                seen_key = (
                    f"{user_id}:{ad['id']}"
                )

                if seen_key in seen:
                    continue

                # Получаем описание
                description = get_ad_description(
                    ad
                )

                ad["description"] = description

                combined_text = (
                    (ad.get("title") or "")
                    + " "
                    + (description or "")
                )

                urgent = detect_urgent_sale(
                    combined_text
                )

                ad["urgent_phrase"] = urgent

                message = format_ad(
                    ad
                )

                try:

                    await context.bot.send_message(
                        chat_id=user_id,
                        text=message
                    )

                    seen.append(
                        seen_key
                    )

                    total_sent += 1

                    print(
                        "📨 ОТПРАВЛЕНО:",
                        ad["id"]
                    )

                except Exception as e:

                    print(
                        "❌ TELEGRAM SEND ERROR:",
                        e
                    )

    # Ограничиваем размер seen
    if len(seen) > 10000:
        seen = seen[-10000:]

    save_json(
        SEEN_FILE,
        seen
    )

    # -----------------------------------------------------
    # STATUS
    # -----------------------------------------------------

    if had_error:

        result = (
            "Avito не вернул объявления. "
            "Проверь ошибку ниже."
        )

    elif total_found == 0:

        result = (
            "Подходящих свежих объявлений "
            "не найдено."
        )

    else:

        result = (
            f"Найдено свежих: {total_found}. "
            f"Отправлено: {total_sent}."
        )

    with STATUS_LOCK:

        STATUS["last_check"] = time.time()

        STATUS["last_check_result"] = result

        STATUS["last_found"] = total_found

        STATUS["last_sent"] = total_sent

        STATUS["checks_count"] += 1

        if not had_error:
            STATUS["last_error"] = None

    print()
    print("====================================")
    print("✅ ПРОВЕРКА ЗАВЕРШЕНА")
    print("📦 Найдено:", total_found)
    print("📨 Отправлено:", total_sent)
    print("⏱ Следующая проверка через 5 минут")
    print("====================================")


# =========================================================
# MAIN
# =========================================================

def main():

    if not TOKEN:

        print(
            "❌ TELEGRAM_BOT_TOKEN не найден"
        )

        return

    print()
    print("🚗 AUTO RADAR BOT ЗАПУЩЕН")
    print("====================================")
    print()
    print("🚨 АВТОМАТИЧЕСКИЙ РАДАР ЗАПУЩЕН")
    print("⏱ Проверка каждые 5 минут")
    print("🇷🇺 Режим поиска: Вся Россия")
    print("🆕 Отправка: только свежие объявления")
    print("====================================")

    with STATUS_LOCK:
        STATUS["started_at"] = time.time()

    # Flask
    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()

    # Telegram
    application = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    application.add_handler(
        CommandHandler(
            "radar",
            radar_command
        )
    )

    application.add_handler(
        CommandHandler(
            "radars",
            radars_command
        )
    )

    application.add_handler(
        CommandHandler(
            "delete",
            delete_command
        )
    )

    application.add_handler(
        CommandHandler(
            "test",
            test_command
        )
    )

    application.add_handler(
        CommandHandler(
            "status",
            status_command
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    # Автоматическая проверка
    job_queue = application.job_queue

    job_queue.run_repeating(
        monitor_job,
        interval=CHECK_INTERVAL,
        first=10
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()

import os
import logging
from datetime import time, datetime, date
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "").strip()
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None
TELEGRAM_API_IP = os.getenv("TELEGRAM_API_IP", "149.154.167.220").strip()
TELEGRAM_CONNECT_TIMEOUT = float(os.getenv("TELEGRAM_CONNECT_TIMEOUT", "3.0"))
TELEGRAM_READ_TIMEOUT = float(os.getenv("TELEGRAM_READ_TIMEOUT", "35.0"))
TELEGRAM_WRITE_TIMEOUT = float(os.getenv("TELEGRAM_WRITE_TIMEOUT", "8.0"))
TELEGRAM_POOL_TIMEOUT = float(os.getenv("TELEGRAM_POOL_TIMEOUT", "5.0"))
TELEGRAM_MAX_RETRIES = int(os.getenv("TELEGRAM_MAX_RETRIES", "3"))

# Университет и группа по умолчанию
GROUP_ID = int(os.getenv("GROUP_ID", "1671"))
GROUP_NAME = os.getenv("GROUP_NAME", "ИС231")
API_BASE_URL = os.getenv("API_BASE_URL", "https://cabinet.amursu.ru/public_api").rstrip("/")
API_URL = f"{API_BASE_URL}/group/{GROUP_ID}"

# Настройки таймаутов API АмГУ и оффлайн-режим
AMSU_CONNECT_TIMEOUT = float(os.getenv("AMSU_CONNECT_TIMEOUT", "1.5"))
AMSU_READ_TIMEOUT = float(os.getenv("AMSU_READ_TIMEOUT", "3.0"))
CIRCUIT_BREAKER_COOLDOWN = float(os.getenv("CIRCUIT_BREAKER_COOLDOWN", "300.0"))
OFFLINE_MODE = os.getenv("OFFLINE_MODE", "false").lower() in ("true", "1", "yes")

# Опорный понедельник начала семестра (для вычисления четности недели)
SEMESTER_ANCHOR_STR = os.getenv("SEMESTER_ANCHOR_MONDAY", "2026-08-31").strip()
try:
    SEMESTER_ANCHOR_MONDAY = datetime.strptime(SEMESTER_ANCHOR_STR, "%Y-%m-%d").date()
except Exception:
    SEMESTER_ANCHOR_MONDAY = date(2026, 8, 31)

# Интервал предварительного уведомления о паре (в минутах)
LESSON_REMINDER_MINUTES = int(os.getenv("LESSON_REMINDER_MINUTES", "15"))

# Хранилище и кэш
DB_PATH = os.getenv("DB_PATH", "bot_data.db")
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "1800"))

# Часовой пояс (Благовещенск / АмГУ — UTC+9)
TIMEZONE_NAME = os.getenv("TIMEZONE", "Asia/Yakutsk")
try:
    TIMEZONE = ZoneInfo(TIMEZONE_NAME)
except Exception:
    TIMEZONE = ZoneInfo("Asia/Yakutsk")

# Стандартное расписание звонков (актуальное для АмГУ, пары 1-7)
DEFAULT_BELL_SCHEDULE = {
    1: (time(8, 15), time(9, 45)),
    2: (time(9, 55), time(11, 25)),
    3: (time(11, 55), time(13, 25)),
    4: (time(13, 35), time(15, 5)),
    5: (time(15, 15), time(16, 45)),
    6: (time(16, 55), time(18, 25)),
    7: (time(18, 35), time(20, 5)),
}

# Дни недели
WEEKDAY_NAMES = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
]

WEEKDAY_SHORT_NAMES = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ"]

# Настройка логирования
def setup_logging():
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=logging.INFO,
    )
    # Подавляем излишний спам от httpx и apscheduler
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

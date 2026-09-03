import os
import logging
from datetime import time
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "").strip()
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None

# Университет и группа по умолчанию
GROUP_ID = int(os.getenv("GROUP_ID", "1671"))
GROUP_NAME = os.getenv("GROUP_NAME", "ИС231")
API_BASE_URL = os.getenv("API_BASE_URL", "https://cabinet.amursu.ru/public_api").rstrip("/")
API_URL = f"{API_BASE_URL}/group/{GROUP_ID}"

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

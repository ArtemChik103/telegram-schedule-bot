import os
import requests
import logging
import json
import locale
from dotenv import load_dotenv
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler
from telegram.constants import ParseMode

# --- Конфигурация ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")
GROUP_ID = 1671
API_URL = f"https://cabinet.amursu.ru/public_api/group/{GROUP_ID}"
CACHE_FILE = "schedule_cache.json"

# --- Новое расписание звонков ---
NEW_SCHEDULE_TIMES = {
    1: "08:15-09:45",
    2: "09:55-11:25",
    3: "11:35-13:05",
    4: "14:00-15:30",
    5: "15:40-17:10",
    6: "17:20-18:50",
}

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Функции для работы с API и данными ---

def get_schedule_data():
    """
    Получает данные о расписании. Сначала пытается получить свежие данные с API.
    Если не получается, пытается загрузить из локального кэша.
    Возвращает кортеж: (данные, флаг_что_данные_из_кэша)
    """
    try:
        response = requests.get(API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logger.info("Расписание успешно получено с API и кэш обновлен.")
        return data, False

    except requests.RequestException as e:
        logger.error(f"Ошибка при запросе к API: {e}. Пытаюсь загрузить из кэша...")
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
            logger.info("Успешно загружено расписание из кэша.")
            return cached_data, True
        except (FileNotFoundError, json.JSONDecodeError):
            logger.error("Файл кэша не найден или поврежден. Данных нет.")
            return None, False

def get_week_type(schedule_data, target_date):
    if not schedule_data or 'current_week' not in schedule_data:
        return 1
    current_week_type = schedule_data['current_week']
    today = datetime.now()
    start_week_num = today.isocalendar()[1]
    target_week_num = target_date.isocalendar()[1]
    week_diff = target_week_num - start_week_num
    if week_diff % 2 != 0:
        return 2 if current_week_type == 1 else 1
    return current_week_type

def format_day_schedule(schedule_data, day_of_week, day_name, week_type):
    week_name = f"Неделя {week_type}"
    header = f"**{day_name} ({week_name})**\n\n"
    
    lessons_for_day = [
        lesson for lesson in schedule_data.get('timetable_tamplate_lines', [])
        if lesson['weekday'] == day_of_week and (lesson['parity'] == 0 or lesson['parity'] == week_type) and lesson.get('discipline_str')
    ]
    if not lessons_for_day:
        return f"**{day_name} ({week_name})**\n\n✅ В этот день занятий нет."

    lessons_for_day.sort(key=lambda x: x['lesson'])
    time_slots = {slot['lesson']: slot for slot in schedule_data.get('schedule_lines', [])}
    
    schedule_parts = []
    # --- НАЧАЛО ИЗМЕНЕНИЯ ---
    # Убираем enumerate и используем настоящий номер пары из данных
    for lesson in lessons_for_day:
        lesson_number = lesson['lesson'] # <-- Берем реальный номер пары
        # --- КОНЕЦ ИЗМЕНЕНИЯ ---
        slot = time_slots.get(lesson_number)
        if not slot: continue

        time_string = NEW_SCHEDULE_TIMES.get(lesson_number)
        if not time_string:
            time_format = '%Y-%m-%dT%H:%M:%S.%fZ'
            start_time = datetime.strptime(slot['begin_time'], time_format).strftime('%H:%M')
            end_time = datetime.strptime(slot['end_time'], time_format).strftime('%H:%M')
            time_string = f"{start_time}-{end_time}"

        subject = lesson.get('discipline_str', 'Не указан')
        teacher = lesson.get('person_str', 'Не указан')
        classroom = lesson.get('classroom_str', 'Не указана')
        
        schedule_parts.append(
            # --- ИЗМЕНЕНИЕ: Используем настоящий номер пары ---
            f"🔔 **{lesson_number}. {time_string}**\n"
            # --- КОНЕЦ ИЗМЕНЕНИЯ ---
            f"📚 *Предмет:* {subject}\n"
            f"🧑‍🏫 *Преподаватель:* {teacher}\n"
            f"🚪 *Аудитория:* {classroom}\n"
        )
            
    return header + "\n".join(schedule_parts)

def get_schedule_for_date(target_date, schedule_data):
    if not schedule_data:
        return "Не удалось получить данные о расписании. Попробуйте позже."
    weekday = target_date.isoweekday()
    week_type = get_week_type(schedule_data, target_date)
    day_name = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"][weekday-1]
    return format_day_schedule(schedule_data, weekday, day_name, week_type)

# --- Обработчики команд Telegram ---

async def start(update: Update, context: CallbackContext) -> None:
    schedule_data, from_cache = get_schedule_data()
    group_name = "ИС231"
    
    if not schedule_data:
        await update.message.reply_text("Не удалось загрузить расписание, и локальная копия отсутствует. Пожалуйста, попробуйте позже.")
        return

    week_type = get_week_type(schedule_data, datetime.now())
    week_name = f"Неделя {week_type}"
    today_str = datetime.now().strftime('%d %B %Y')
    
    welcome_message = (
        f"Привет! Я бот с расписанием группы **{group_name}**.\n\n"
        f"📅 **Сегодня:** {today_str}\n"
        f"🗓️ **Текущая неделя:** {week_name}\n\n"
        "Выберите нужный пункт в меню:"
    )
    
    if from_cache:
        welcome_message = "⚠️ **Внимание! Сервер АмГУ недоступен.**\nДанные могут быть неактуальными.\n\n" + welcome_message

    reply_keyboard = [["На сегодня", "На завтра"], ["Эта неделя", "Следующая неделя"]]
    await update.message.reply_text(
        welcome_message,
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True),
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_message(update: Update, context: CallbackContext) -> None:
    if not update.message or not update.message.text:
        return

    text = update.message.text
    today = datetime.now()
    schedule_data, from_cache = get_schedule_data()

    if not schedule_data:
        await update.message.reply_text("Не удалось загрузить расписаниe, и локальная копия отсутствует. Пожалуйста, попробуйте позже.")
        return

    message = ""
    if text == "На сегодня":
        message = get_schedule_for_date(today, schedule_data)
    elif text == "На завтра":
        tomorrow = today + timedelta(days=1)
        message = get_schedule_for_date(tomorrow, schedule_data)
    elif text == "Эта неделя":
        await show_week_schedule(update, context, is_next_week=False)
        return
    elif text == "Следующая неделя":
        await show_week_schedule(update, context, is_next_week=True)
        return
    
    if from_cache:
        message = "⚠️ **Внимание! Сервер АмГУ недоступен.**\nПоказываю последнее сохраненное расписание. Оно может быть неактуальным.\n\n" + message
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

async def show_week_schedule(update: Update, context: CallbackContext, is_next_week: bool):
    week_days = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ"]
    prefix = "next_week" if is_next_week else "this_week"
    keyboard = [InlineKeyboardButton(day, callback_data=f"{prefix}_{i+1}") for i, day in enumerate(week_days)]
    reply_markup = InlineKeyboardMarkup([keyboard])
    week_name = "следующую" if is_next_week else "текущую"
    await update.message.reply_text(f"Выберите день на {week_name} неделю:", reply_markup=reply_markup)

async def button_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer() 
    
    query_data = query.data
    prefix, day_index_str = query_data.rsplit('_', 1)
    day_index = int(day_index_str)
    
    today = datetime.now()
    if prefix == "this_week":
        target_date = today - timedelta(days=today.isoweekday() - day_index)
    else: # next_week
        days_left_in_week = 7 - today.isoweekday()
        next_monday = today + timedelta(days=days_left_in_week + 1)
        target_date = next_monday + timedelta(days=day_index - 1)
        
    schedule_data, from_cache = get_schedule_data()
    
    if not schedule_data:
        await query.edit_message_text(text="Не удалось загрузить расписание, и локальная копия отсутствует. Пожалуйста, попробуйте позже.")
        return

    message = get_schedule_for_date(target_date, schedule_data)
    
    if from_cache:
        message = "⚠️ **Внимание! Сервер АмГУ недоступен.**\nПоказываю последнее сохраненное расписание. Оно может быть неактуальным.\n\n" + message

    if query.message.text != message:
        await query.edit_message_text(text=message, parse_mode=ParseMode.MARKDOWN)

# --- Основная функция запуска бота ---

def main() -> None:
    try:
        locale.setlocale(locale.LC_TIME, 'ru_RU.UTF-8')
    except locale.Error:
        try:
            locale.setlocale(locale.LC_TIME, 'Russian_Russia.1251')
        except locale.Error:
            logger.warning("Русская локаль не найдена. Даты будут в стандартном формате.")

    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "ВАШ_ТОКЕН_ЗДЕСЬ":
        print("Ошибка: Не указан токен Telegram-бота. Укажите его в файле .env")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).connect_timeout(10).read_timeout(10).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))

    print("Бот запущен...")
    application.run_polling()

if __name__ == '__main__':
    main()

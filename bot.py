import os
import requests
import logging
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

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Функции для работы с API и данными ---

def get_schedule_data():
    """Получает и возвращает данные о расписании из API."""
    try:
        # --- ИЗМЕНЕНИЕ: Увеличен тайм-аут для запроса к серверу АмГУ ---
        response = requests.get(API_URL, timeout=30)
        # --- КОНЕЦ ИЗМЕНЕНИЯ ---
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Ошибка получения данных: Статус {response.status_code}")
            return None
    except requests.RequestException as e:
        logger.error(f"Исключение при запросе к API: {e}")
        return None

def get_week_type(schedule_data, target_date):
    """Определяет тип недели (1 или 2) для указанной даты."""
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
    """Форматирует расписание на один день в читаемый вид."""
    week_name = f"Неделя {week_type}"
    header = f"**{day_name} ({week_name})**\n\n"
    
    time_slots = sorted(schedule_data.get('schedule_lines', []), key=lambda x: x['lesson'])
    
    lessons_for_day = [
        lesson for lesson in schedule_data.get('timetable_tamplate_lines', [])
        if lesson['weekday'] == day_of_week and (lesson['parity'] == 0 or lesson['parity'] == week_type)
    ]

    if not any(l.get('discipline_str') for l in lessons_for_day):
        return f"**{day_name}**\n\nВ этот день занятий нет."

    schedule_parts = []
    lesson_counter = 1

    for slot in time_slots:
        lesson_number = slot['lesson']
        
        current_lesson = next((l for l in lessons_for_day if l['lesson'] == lesson_number), None)
        
        if current_lesson and current_lesson.get('discipline_str'):
            time_format = '%Y-%m-%dT%H:%M:%S.%fZ'
            start_time = datetime.strptime(slot['begin_time'], time_format).strftime('%H:%M')
            end_time = datetime.strptime(slot['end_time'], time_format).strftime('%H:%M')
            
            subject = current_lesson.get('discipline_str', 'Не указан')
            teacher = current_lesson.get('person_str', 'Не указан')
            classroom = current_lesson.get('classroom_str', 'Не указана')
            
            schedule_parts.append(
                f"**{lesson_counter}. {start_time}-{end_time}**\n"
                f"*Предмет:* {subject}\n"
                f"*Преподаватель:* {teacher}\n"
                f"*Аудитория:* {classroom}\n"
            )
            lesson_counter += 1
            
    if not schedule_parts:
        return f"**{day_name}**\n\nВ этот день занятий нет."
        
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
    schedule_data = get_schedule_data()
    
    group_name = "ИС231" # Используем правильное имя группы
    
    week_type = get_week_type(schedule_data, datetime.now()) if schedule_data else 1
    week_name = f"Неделя {week_type}"
    
    today_str = datetime.now().strftime('%d.%m.%Y')
    
    welcome_message = (
        f"Привет! Я бот с расписанием группы **{group_name}**.\n\n"
        f"**Сегодня:** {today_str}\n"
        f"**Текущая неделя:** {week_name}\n\n"
        "Выберите нужный пункт в меню:"
    )
    
    reply_keyboard = [
        ["На сегодня", "На завтра"],
        ["Эта неделя", "Следующая неделя"],
    ]
    
    await update.message.reply_text(
        welcome_message,
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True),
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_message(update: Update, context: CallbackContext) -> None:
    text = update.message.text
    today = datetime.now()
    schedule_data = get_schedule_data()

    if not schedule_data:
        await update.message.reply_text("Не удалось загрузить расписание. Сервер АмГУ может быть недоступен.")
        return

    if text == "На сегодня":
        message = get_schedule_for_date(today, schedule_data)
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        
    elif text == "На завтра":
        tomorrow = today + timedelta(days=1)
        message = get_schedule_for_date(tomorrow, schedule_data)
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        
    elif text == "Эта неделя":
        await show_week_schedule(update, context, is_next_week=False)
        
    elif text == "Следующая неделя":
        await show_week_schedule(update, context, is_next_week=True)

async def show_week_schedule(update: Update, context: CallbackContext, is_next_week: bool):
    week_days = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ"]
    prefix = "next_week" if is_next_week else "this_week"
    
    keyboard = [
        InlineKeyboardButton(day, callback_data=f"{prefix}_{i+1}")
        for i, day in enumerate(week_days)
    ]
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
        days_until_next_week = 7 - today.isoweekday()
        next_monday = today + timedelta(days=days_until_next_week + (day_index - 1))
        target_date = next_monday
        
    schedule_data = get_schedule_data()
    message = get_schedule_for_date(target_date, schedule_data)
    
    if query.message.text != message:
        await query.edit_message_text(text=message, parse_mode=ParseMode.MARKDOWN)

# --- Основная функция запуска бота ---

def main() -> None:
    if TELEGRAM_TOKEN == "ВАШ_ТОКЕН_ЗДЕСЬ":
        print("Ошибка: Не указан токен Telegram-бота. Укажите его в переменной TELEGRAM_TOKEN.")
        return

    # --- ИЗМЕНЕНИЕ: Увеличены тайм-ауты для библиотеки telegram ---
    application = Application.builder().token(TELEGRAM_TOKEN).connect_timeout(30).read_timeout(30).build()
    # --- КОНЕЦ ИЗМЕНЕНИЯ ---

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))

    print("Бот запущен...")
    application.run_polling()

if __name__ == '__main__':
    main()
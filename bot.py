import os
import requests
import logging
import json
import sqlite3
import traceback
import locale
import asyncio
import time # <--- Добавили для работы с часовыми поясами
from datetime import datetime, timedelta, time as dt_time
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler

# --- УСТАНОВКА ЧАСОВОГО ПОЯСА (ВАЖНО!) ---
# Принудительно ставим время Благовещенска (UTC+9) для всего скрипта
os.environ['TZ'] = 'Asia/Yakutsk'
try:
    time.tzset()
except AttributeError:
    pass # На Windows это не сработает, но у вас Linux, так что все ок

# --- Конфигурация ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
GROUP_ID = 1671
API_URL = f"https://cabinet.amursu.ru/public_api/group/{GROUP_ID}"
DB_FILE = "bot_data.db"
UPDATE_INTERVAL_MINUTES = 20

# --- Тайминги ---
SCHEDULE_TIMES_PARSED = {
    1: (dt_time(8, 15), dt_time(9, 45)),
    2: (dt_time(9, 55), dt_time(11, 25)),
    3: (dt_time(11, 35), dt_time(13, 5)),
    4: (dt_time(14, 0), dt_time(15, 30)),
    5: (dt_time(15, 40), dt_time(17, 10)),
    6: (dt_time(17, 20), dt_time(18, 50)),
}

SCHEDULE_TIMES_STR = {
    1: "08:15-09:45",
    2: "09:55-11:25",
    3: "11:35-13:05",
    4: "14:00-15:30",
    5: "15:40-17:10",
    6: "17:20-18:50",
}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Работа с БД (SQLite) ---

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS schedule_cache
                 (id INTEGER PRIMARY KEY, json_data TEXT, updated_at TEXT)''')
    conn.commit()
    conn.close()

def save_cache_to_db(data):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        json_str = json.dumps(data, ensure_ascii=False)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute('INSERT OR REPLACE INTO schedule_cache (id, json_data, updated_at) VALUES (1, ?, ?)', (json_str, now_str))
        conn.commit()
        conn.close()
        logger.info("БД обновлена успешно.")
    except Exception as e:
        logger.error(f"Ошибка БД при сохранении: {e}")

def load_cache_from_db():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('SELECT json_data, updated_at FROM schedule_cache WHERE id=1')
        row = c.fetchone()
        conn.close()
        if row:
            data = json.loads(row[0])
            updated_at = datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")
            return data, updated_at
        return None, None
    except Exception as e:
        logger.error(f"Ошибка БД при чтении: {e}")
        return None, None

# --- Фоновая задача обновления ---

async def update_schedule_job(context: CallbackContext):
    logger.info("⏳ Запуск фонового обновления расписания...")
    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, lambda: requests.get(API_URL, timeout=30))
        
        if response.status_code == 200:
            data = response.json()
            await loop.run_in_executor(None, lambda: save_cache_to_db(data))
            logger.info("✅ Фоновое обновление завершено успешно.")
        else:
            logger.warning(f"⚠️ API вернул код {response.status_code}")
    except Exception as e:
        logger.error(f"❌ Ошибка при фоновом обновлении: {e}")

# --- Получение данных для ответа пользователю ---

def get_data_for_user():
    data, updated_at = load_cache_from_db()
    if not data:
        return None, True

    if updated_at:
        age = datetime.now() - updated_at
        if age > timedelta(hours=4):
            return data, True 
            
    return data, False

# --- Логика формирования ответов ---

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

def get_current_lesson_info(schedule_data):
    now = datetime.now().time()
    today_date = datetime.now()
    weekday = today_date.isoweekday()
    week_type = get_week_type(schedule_data, today_date)

    lessons_today = [
        l for l in schedule_data.get('timetable_tamplate_lines', [])
        if l['weekday'] == weekday and (l['parity'] == 0 or l['parity'] == week_type)
    ]
    
    if not lessons_today:
        return "✅ Сегодня занятий нет, отдыхай!"

    lessons_today.sort(key=lambda x: x['lesson'])
    lesson_map = {l['lesson']: l for l in lessons_today}
    sorted_slots = sorted(SCHEDULE_TIMES_PARSED.items())

    for num, (start, end) in sorted_slots:
        if start <= now <= end:
            lesson = lesson_map.get(num)
            if lesson:
                # Добавил проверку на пустые значения "or '...'"
                subj = lesson.get('discipline_str') or 'Не указан'
                aud = lesson.get('classroom_str') or '?'
                teach = lesson.get('person_str') or ''
                return (
                    f"🔴 **Сейчас идет {num}-я пара** ({SCHEDULE_TIMES_STR[num]})\n"
                    f"📚 {subj}\n"
                    f"🚪 Ауд. {aud}\n"
                    f"👨‍🏫 {teach}"
                )
            else:
                return f"🕒 Сейчас время {num}-й пары, но по расписанию у вас **окно**."

    for i in range(len(sorted_slots) - 1):
        current_num, (_, current_end) = sorted_slots[i]
        next_num, (next_start, _) = sorted_slots[i+1]
        
        if current_end < now < next_start:
            next_lesson = lesson_map.get(next_num)
            status = f"☕ **Сейчас перемена** (до {next_start.strftime('%H:%M')})"
            if next_lesson:
                subj = next_lesson.get('discipline_str') or 'Не указан'
                aud = next_lesson.get('classroom_str') or '?'
                status += (
                    f"\n\n🔜 **Следующая пара ({next_num}-я):**\n"
                    f"📚 {subj}\n"
                    f"🚪 {aud}"
                )
            else:
                status += f"\n\n🔜 Следующая пара ({next_num}-я) — **Окно**."
            return status

    first_start = sorted_slots[0][1][0]
    last_end = sorted_slots[-1][1][1]

    if now < first_start:
         first_lesson_num = lessons_today[0]['lesson']
         first_start_time = SCHEDULE_TIMES_STR.get(first_lesson_num, "??:??").split('-')[0]
         return f"💤 Пары еще не начались. Первая пара начинается в {first_start_time}."
    
    if now > last_end:
        return "🎉 На сегодня все пары закончились!"

    return "🔎 Не могу определить статус."

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
    
    schedule_parts = []
    for lesson in lessons_for_day:
        lesson_number = lesson['lesson']
        time_string = SCHEDULE_TIMES_STR.get(lesson_number, "Время не указано")
        # Исправление пустых полей
        subject = lesson.get('discipline_str') or 'Не указан'
        teacher = lesson.get('person_str') or 'Не указан'
        classroom = lesson.get('classroom_str') or 'Не указана'
        
        schedule_parts.append(
            f"🔔 **{lesson_number}. {time_string}**\n"
            f"📚 *Предмет:* {subject}\n"
            f"🧑‍🏫 *Преподаватель:* {teacher}\n"
            f"🚪 *Аудитория:* {classroom}\n"
        )
            
    return header + "\n".join(schedule_parts)

def get_schedule_for_date(target_date, schedule_data):
    weekday = target_date.isoweekday()
    week_type = get_week_type(schedule_data, target_date)
    day_name = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"][weekday-1]
    return format_day_schedule(schedule_data, weekday, day_name, week_type)

# --- Обработчики Telegram ---

async def start(update: Update, context: CallbackContext) -> None:
    data, _ = get_data_for_user()
    if not data:
        await update.message.reply_text("👋 Привет! Я настраиваюсь, подожди пару секунд...")
        await update_schedule_job(context) 
    
    group_name = "ИС231"
    welcome_message = f"Привет! Я бот группы **{group_name}**.\nМеню внизу 👇"
    
    reply_keyboard = [
        ["Сейчас", "На сегодня"], 
        ["На завтра", "Эта неделя"],
        ["Следующая неделя"]
    ]
    
    await update.message.reply_text(
        welcome_message,
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True),
        parse_mode=ParseMode.MARKDOWN
    )

async def reload_command(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("🔄 Пробую обновить расписание с сайта...")
    await update_schedule_job(context)
    await update.message.reply_text("✅ Готово (или сохранено в логах, если ошибка).")

async def handle_message(update: Update, context: CallbackContext) -> None:
    if not update.message or not update.message.text:
        return

    text = update.message.text
    valid_commands = ["На сегодня", "На завтра", "Эта неделя", "Следующая неделя", "Сейчас"]
    
    if text not in valid_commands:
        return

    schedule_data, is_old = get_data_for_user()
    
    if not schedule_data:
        await update.message.reply_text("😔 Данных о расписании пока нет. Бот пытается достучаться до сервера АмГУ...")
        return

    today = datetime.now()
    message = ""

    if text == "Сейчас":
        message = get_current_lesson_info(schedule_data)
    elif text == "На сегодня":
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
    
    if is_old and text != "Сейчас":
        message = "⚠️ **Внимание!** Нет связи с АмГУ более 4 часов.\nПоказываю сохраненную копию.\n\n" + message
    
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
    else:
        days_left_in_week = 7 - today.isoweekday()
        next_monday = today + timedelta(days=days_left_in_week + 1)
        target_date = next_monday + timedelta(days=day_index - 1)
        
    schedule_data, is_old = get_data_for_user()
    
    if not schedule_data:
        await query.edit_message_text("Данные недоступны.")
        return

    message = get_schedule_for_date(target_date, schedule_data)
    
    if is_old:
        message = "⚠️ **Нет связи с АмГУ.** (Старые данные)\n\n" + message

    if query.message.text != message:
        await query.edit_message_text(text=message, parse_mode=ParseMode.MARKDOWN)

async def error_handler(update: object, context: CallbackContext) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    if ADMIN_ID:
        try:
            tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
            tb_string = "".join(tb_list)
            message = (f"🚨 **Ошибка в боте!**\nError: `{context.error}`\nTraceback:\n`{tb_string[-1000:]}`")
            await context.bot.send_message(chat_id=ADMIN_ID, text=message, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass

def main() -> None:
    init_db()
    try:
        locale.setlocale(locale.LC_TIME, 'ru_RU.UTF-8')
    except:
        pass

    if not TELEGRAM_TOKEN:
        print("Ошибка: Токен не найден.")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reload", reload_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_error_handler(error_handler)

    job_queue = application.job_queue
    job_queue.run_once(update_schedule_job, 5)
    job_queue.run_repeating(update_schedule_job, interval=UPDATE_INTERVAL_MINUTES * 60, first=10)

    print("Бот запущен в режиме ФОНОВОГО ОБНОВЛЕНИЯ...")
    application.run_polling()

if __name__ == '__main__':
    main()

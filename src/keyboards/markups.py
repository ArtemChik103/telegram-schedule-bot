from telegram import (
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from src.config import WEEKDAY_SHORT_NAMES


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Главная постоянная клавиатура с быстрыми кнопками."""
    keyboard = [
        ["🔴 Сейчас", "📅 На сегодня"],
        ["➡️ На завтра", "🗓 Эта неделя"],
        ["⏭ След. неделя", "🔔 Звонки"],
        ["👨‍🏫 Преподаватели", "⚙️ Настройки"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_week_inline_keyboard(
    is_next_week: bool = False,
    active_day: int | None = None,
) -> InlineKeyboardMarkup:
    """
    Интерактивная инлайн-клавиатура для просмотра недели:
    - Дни недели с подсветкой текущего активного дня (• СР •)
    - Переключение между текущей и следующей неделей
    - Кнопка просмотра всей недели одним сообщением
    """
    prefix = "next" if is_next_week else "this"

    # Строка 1: Дни недели (ПН..СБ)
    day_buttons = []
    for i, short_name in enumerate(WEEKDAY_SHORT_NAMES):
        day_num = i + 1
        label = f"• {short_name} •" if active_day == day_num else short_name
        day_buttons.append(
            InlineKeyboardButton(
                label,
                callback_data=f"show_day_{prefix}_{day_num}",
            )
        )

    # Строка 2: Переключатель недель
    if is_next_week:
        switch_button = InlineKeyboardButton(
            "⬅️ Текущая неделя",
            callback_data="switch_week_this",
        )
    else:
        switch_button = InlineKeyboardButton(
            "➡️ Следующая неделя",
            callback_data="switch_week_next",
        )

    # Строка 3: Вся неделя и экспорт
    full_week_button = InlineKeyboardButton(
        "📜 Вся неделя целиком",
        callback_data=f"full_week_{prefix}",
    )

    return InlineKeyboardMarkup([day_buttons, [switch_button], [full_week_button]])


def get_settings_inline_keyboard(user: dict | None) -> InlineKeyboardMarkup:
    """Инлайн-клавиатура меню настроек пользователя."""
    subgroup = user.get("subgroup", 0) if user else 0
    subgroup_str = (
        "Вся группа" if subgroup == 0 else f"{subgroup}-я подгруппа"
    )

    morning_on = user.get("notify_morning", 0) if user else 0
    morning_icon = "🔔 ВКЛ (07:30)" if morning_on else "🔕 ВЫКЛ"

    evening_on = user.get("notify_evening", 0) if user else 0
    evening_icon = "🔔 ВКЛ (20:00)" if evening_on else "🔕 ВЫКЛ"

    only_lessons = user.get("notify_only_with_lessons", 1) if user else 1
    only_lessons_icon = "😴 ВКЛ (тишина)" if only_lessons else "🔔 Всегда"

    keyboard = [
        [
            InlineKeyboardButton(
                f"👥 Моя подгруппа: {subgroup_str}",
                callback_data="settings_subgroup",
            )
        ],
        [
            InlineKeyboardButton(
                f"🌅 Утренний дайджест: {morning_icon}",
                callback_data="toggle_notif_morning",
            )
        ],
        [
            InlineKeyboardButton(
                f"🌙 Вечерний дайджест: {evening_icon}",
                callback_data="toggle_notif_evening",
            )
        ],
        [
            InlineKeyboardButton(
                f"🔕 Без пар не будить: {only_lessons_icon}",
                callback_data="toggle_notif_only_lessons",
            )
        ],
        [
            InlineKeyboardButton(
                "📅 Экспорт в календарь (.ics)",
                callback_data="export_ics",
            )
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_subgroup_select_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора подгруппы."""
    keyboard = [
        [InlineKeyboardButton("👥 Вся группа (без фильтра)", callback_data="set_subgroup_0")],
        [InlineKeyboardButton("1️⃣ 1-я подгруппа", callback_data="set_subgroup_1")],
        [InlineKeyboardButton("2️⃣ 2-я подгруппа", callback_data="set_subgroup_2")],
        [InlineKeyboardButton("⬅️ Назад в настройки", callback_data="settings_back")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_teachers_inline_keyboard(teachers: list[dict]) -> InlineKeyboardMarkup:
    """Инлайн-кнопки со списком преподавателей группы (по 2 в ряд)."""
    keyboard = []
    row = []
    for t in teachers:
        name = t.get("name", "Преподаватель")
        parts = name.split()
        if len(parts) >= 3:
            short_name = f"{parts[0]} {parts[1][0]}.{parts[2][0]}."
        elif len(parts) == 2:
            short_name = f"{parts[0]} {parts[1][0]}."
        else:
            short_name = name

        row.append(
            InlineKeyboardButton(short_name, callback_data=f"teacher_select_{t['id']}")
        )
        if len(row) == 2:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    return InlineKeyboardMarkup(keyboard)


def get_teacher_schedule_keyboard(
    teacher_id: int, active_tab: str = "today"
) -> InlineKeyboardMarkup:
    """Кнопки навигации по расписанию выбранного преподавателя."""
    status_btn = "• Где сейчас? •" if active_tab == "status" else "🟢 Где сейчас?"
    today_btn = "• Сегодня •" if active_tab == "today" else "📅 Сегодня"
    tomorrow_btn = "• Завтра •" if active_tab == "tomorrow" else "➡️ Завтра"
    week_btn = "• Вся неделя •" if active_tab == "week" else "🗓 Вся неделя"

    keyboard = [
        [
            InlineKeyboardButton(status_btn, callback_data=f"teacher_status_{teacher_id}"),
            InlineKeyboardButton(today_btn, callback_data=f"teacher_today_{teacher_id}"),
        ],
        [
            InlineKeyboardButton(tomorrow_btn, callback_data=f"teacher_tomorrow_{teacher_id}"),
            InlineKeyboardButton(week_btn, callback_data=f"teacher_week_{teacher_id}"),
        ],
        [
            InlineKeyboardButton("⬅️ Все преподаватели", callback_data="teacher_list"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_teacher_week_keyboard(
    teacher_id: int, active_day: int | None = None
) -> InlineKeyboardMarkup:
    """Интерактивные кнопки по дням недели для расписания преподавателя."""
    day_row = []
    for day_num in range(1, 7):
        short = WEEKDAY_SHORT_NAMES[day_num - 1]
        label = f"• {short} •" if active_day == day_num else short
        day_row.append(
            InlineKeyboardButton(
                label, callback_data=f"teacher_day_{teacher_id}_{day_num}"
            )
        )

    keyboard = [
        day_row,
        [
            InlineKeyboardButton("🟢 Где сейчас?", callback_data=f"teacher_status_{teacher_id}"),
            InlineKeyboardButton("📅 Сегодня", callback_data=f"teacher_today_{teacher_id}"),
        ],
        [
            InlineKeyboardButton("⬅️ Все преподаватели", callback_data="teacher_list"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


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
        ["👨‍🏫 Преподаватель", "⚙️ Настройки"],
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
    """Инлайн-кнопки со списком найденных преподавателей."""
    keyboard = [
        [InlineKeyboardButton(t["name"], callback_data=f"teacher_select_{t['id']}")]
        for t in teachers
    ]
    return InlineKeyboardMarkup(keyboard)


def get_teacher_schedule_keyboard(teacher_id: int) -> InlineKeyboardMarkup:
    """Кнопки навигации по расписанию преподавателя."""
    keyboard = [
        [
            InlineKeyboardButton("🟢 Где сейчас?", callback_data=f"teacher_status_{teacher_id}"),
            InlineKeyboardButton("📅 На сегодня", callback_data=f"teacher_today_{teacher_id}"),
        ],
        [
            InlineKeyboardButton("➡️ На завтра", callback_data=f"teacher_tomorrow_{teacher_id}"),
            InlineKeyboardButton("🗓 Вся неделя", callback_data=f"teacher_week_{teacher_id}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


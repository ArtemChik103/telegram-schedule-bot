import html
import hashlib
from datetime import datetime, date, time, timedelta
from src.config import (
    TIMEZONE,
    DEFAULT_BELL_SCHEDULE,
    WEEKDAY_NAMES,
)


def parse_iso_time(time_str: str) -> time:
    """Парсит строку времени ISO (например '2000-01-01T08:15:00.000Z') в объект datetime.time."""
    try:
        # Извлекаем часть времени HH:MM
        t_part = time_str.split("T")[1][:5]
        h, m = map(int, t_part.split(":"))
        return time(h, m)
    except Exception:
        return time(0, 0)


def get_bell_schedule(schedule_data: dict | None) -> dict[int, tuple[time, time]]:
    """Извлекает актуальное расписание звонков из API или возвращает дефолтное."""
    if not schedule_data or "schedule_lines" not in schedule_data:
        return DEFAULT_BELL_SCHEDULE

    parsed = {}
    for line in schedule_data.get("schedule_lines", []):
        lesson_num = line.get("lesson")
        begin_str = line.get("begin_time")
        end_str = line.get("end_time")
        if lesson_num and begin_str and end_str:
            b_time = parse_iso_time(begin_str)
            e_time = parse_iso_time(end_str)
            parsed[lesson_num] = (b_time, e_time)

    return parsed if parsed else DEFAULT_BELL_SCHEDULE


def get_bell_schedule_str(schedule_data: dict | None) -> dict[int, str]:
    """Форматирует расписание звонков в словарь {номер: '08:15–09:45'}."""
    bells = get_bell_schedule(schedule_data)
    return {
        num: f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}"
        for num, (start, end) in bells.items()
    }


def get_week_type(
    schedule_data: dict | None,
    target_date: date,
    reference_date: date | None = None,
) -> int:
    """
    Вычисляет четность недели (1 = нечетная, 2 = четная) для целевой даты.
    Использует смещение недель относительно понедельников.
    Если данные получены из резервного кэша SQLite, учитывает дату фиксации кэша _cached_at_date.
    """
    if not schedule_data or "current_week" not in schedule_data:
        return 1

    current_week_type = schedule_data.get("current_week", 1)

    cached_date = None
    if isinstance(schedule_data, dict) and "_cached_at_date" in schedule_data:
        try:
            cached_date = datetime.strptime(
                str(schedule_data["_cached_at_date"])[:10], "%Y-%m-%d"
            ).date()
        except Exception:
            cached_date = None

    base_date = reference_date or cached_date or datetime.now(TIMEZONE).date()

    # Смещаем обе даты к их понедельникам
    base_monday = base_date - timedelta(days=base_date.weekday())
    target_monday = target_date - timedelta(days=target_date.weekday())

    week_diff = (target_monday - base_monday).days // 7
    if week_diff % 2 != 0:
        return 2 if current_week_type == 1 else 1
    return current_week_type


def get_lessons_for_day(
    schedule_data: dict | None,
    weekday: int,
    week_type: int,
    subgroup: int = 0,
) -> list[dict]:
    """
    Возвращает список непустых занятий для указанного дня недели и четности.
    Исключает пустые строки шаблона API и фильтрует по подгруппе.
    """
    if not schedule_data:
        return []

    all_lines = schedule_data.get("timetable_tamplate_lines", [])
    lessons = []

    for item in all_lines:
        if item.get("weekday") != weekday:
            continue
        if item.get("parity") not in (0, week_type):
            continue

        discipline = (item.get("discipline_str") or "").strip()
        if not discipline:
            continue

        item_subgroup = item.get("subgroup", 0)
        # 0 = для всей группы; если у пользователя задана подгруппа 1 или 2, показываем общие и его подгруппу
        if subgroup != 0 and item_subgroup not in (0, subgroup):
            continue

        lessons.append(item)

    # Сортировка по номеру пары и подгруппе
    lessons.sort(key=lambda x: (x.get("lesson", 0), x.get("subgroup", 0)))
    return lessons


def render_progress_bar(percent: int, length: int = 10) -> str:
    """Формирует текстовый прогресс-бар: [██████░░░░]."""
    filled = int(round(length * percent / 100))
    filled = max(0, min(length, filled))
    return "█" * filled + "░" * (length - filled)


def format_minutes_delta(total_minutes: int) -> str:
    """Форматирует минуты в человекочитаемый вид: '1 ч 25 мин' или '45 мин'."""
    hours = total_minutes // 60
    mins = total_minutes % 60
    if hours > 0:
        return f"{hours} ч {mins:02d} мин" if mins > 0 else f"{hours} ч"
    return f"{mins} мин"


def format_day_schedule(
    schedule_data: dict | None,
    target_date: date,
    subgroup: int = 0,
    show_header_date: bool = True,
) -> str:
    """Форматирует расписание на указанный день в красивый HTML."""
    if not schedule_data:
        return "⚠️ <b>Данные расписания временно недоступны.</b>"

    weekday = target_date.isoweekday()
    week_type = get_week_type(schedule_data, target_date)
    day_name = WEEKDAY_NAMES[weekday - 1]
    week_desc = "нечетная" if week_type == 1 else "четная"

    lessons = get_lessons_for_day(schedule_data, weekday, week_type, subgroup)
    bells_str = get_bell_schedule_str(schedule_data)

    date_str = target_date.strftime("%d.%m.%Y")
    header = (
        f"📅 <b>{day_name} ({date_str})</b>\n"
        f"<i>Неделя {week_type} ({week_desc})</i>\n\n"
        if show_header_date
        else f"📅 <b>{day_name}</b> (Неделя {week_type})\n\n"
    )

    if not lessons:
        return header + "✅ <b>В этот день занятий нет. Отдыхаем!</b>"

    parts = []
    for lesson in lessons:
        num = lesson.get("lesson", 1)
        time_str = bells_str.get(num, "??:??–??:??")
        subject = html.escape(lesson.get("discipline_str") or "Не указан")
        teacher = html.escape(lesson.get("person_str") or "Преподаватель не указан")
        classroom = html.escape(lesson.get("classroom_str") or "Аудитория не указана")
        lesson_sub = lesson.get("subgroup", 0)

        sub_tag = f" <i>[подгруппа {lesson_sub}]</i>" if lesson_sub > 0 else ""

        parts.append(
            f"🔔 <b>{num}-я пара</b> (<code>{time_str}</code>){sub_tag}\n"
            f"📚 <b>{subject}</b>\n"
            f"🚪 Ауд. <b>{classroom}</b>\n"
            f"🧑‍🏫 {teacher}\n"
        )

    return header + "\n".join(parts)


def format_full_week_schedule(
    schedule_data: dict | None,
    is_next_week: bool = False,
    subgroup: int = 0,
) -> str:
    """Форматирует сводное расписание на всю неделю."""
    if not schedule_data:
        return "⚠️ <b>Данные расписания временно недоступны.</b>"

    today_local = datetime.now(TIMEZONE).date()
    days_to_monday = today_local.weekday()
    current_monday = today_local - timedelta(days=days_to_monday)

    target_monday = (
        current_monday + timedelta(days=7) if is_next_week else current_monday
    )
    week_type = get_week_type(schedule_data, target_monday)
    week_desc = "следующая" if is_next_week else "текущая"
    week_parity_desc = "нечетная" if week_type == 1 else "четная"

    header = (
        f"🗓 <b>Расписание на {week_desc} неделю</b>\n"
        f"<i>Неделя {week_type} ({week_parity_desc})</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    day_blocks = []
    # Понедельник — Суббота (1..6)
    for day_idx in range(6):
        d = target_monday + timedelta(days=day_idx)
        block = format_day_schedule(
            schedule_data, d, subgroup=subgroup, show_header_date=True
        )
        day_blocks.append(block)

    return header + "\n\n━━━━━━━━━━━━━━━━━━━━━\n\n".join(day_blocks)


def find_next_lessons_day(
    schedule_data: dict | None,
    from_date: date,
    subgroup: int = 0,
    max_days_ahead: int = 7,
) -> tuple[date, list[dict]] | None:
    """Ищет ближайший следующий день с парами, начиная со следующего дня."""
    if not schedule_data:
        return None

    for offset in range(1, max_days_ahead + 1):
        check_date = from_date + timedelta(days=offset)
        weekday = check_date.isoweekday()
        week_type = get_week_type(schedule_data, check_date)
        lessons = get_lessons_for_day(schedule_data, weekday, week_type, subgroup)
        if lessons:
            return check_date, lessons
    return None


def get_current_status(
    schedule_data: dict | None,
    subgroup: int = 0,
) -> str:
    """
    Определяет детальный статус на текущую минуту:
    - Прогресс текущей пары с прогресс-баром и оставшимися минутами
    - Таймер перемены до следующей пары
    - Таймер до начала первой пары (если день еще не начался)
    - Окна между парами
    - Умный анонс следующей пары на завтра или понедельник, если занятия сегодня завершены
    """
    if not schedule_data:
        return "⚠️ <b>Не удалось получить расписание.</b>"

    now_dt = datetime.now(TIMEZONE)
    now_time = now_dt.time()
    today_date = now_dt.date()
    weekday = today_date.isoweekday()
    week_type = get_week_type(schedule_data, today_date)

    bells = get_bell_schedule(schedule_data)
    bells_str = get_bell_schedule_str(schedule_data)

    # Получаем реальные непустые пары на сегодня
    lessons_today = get_lessons_for_day(schedule_data, weekday, week_type, subgroup)
    if not lessons_today:
        next_info = find_next_lessons_day(schedule_data, today_date, subgroup)
        if next_info:
            next_date, next_lessons = next_info
            n_first = next_lessons[0]
            n_num = n_first.get("lesson", 1)
            n_time = bells_str.get(n_num, "08:15–09:45")
            n_subj = html.escape(n_first.get("discipline_str") or "Занятие")
            n_room = html.escape(n_first.get("classroom_str") or "—")
            day_diff = (next_date - today_date).days
            day_title = "завтра" if day_diff == 1 else f"в {WEEKDAY_NAMES[next_date.isoweekday() - 1].lower()} ({next_date.strftime('%d.%m')})"

            return (
                "✅ <b>Сегодня занятий нет, отдыхай!</b>\n"
                f"<i>{WEEKDAY_NAMES[weekday - 1]}, Неделя {week_type}</i>\n\n"
                f"🔜 <b>Ближайшие пары будут {day_title}:</b>\n"
                f"🔔 <b>{n_num}-я пара</b> (<code>{n_time}</code>): <b>{n_subj}</b> (ауд. <b>{n_room}</b>)"
            )
        return (
            "✅ <b>Сегодня занятий нет, отдыхай!</b>\n"
            f"<i>{WEEKDAY_NAMES[weekday - 1]}, Неделя {week_type}</i>"
        )

    # Карта пар: {lesson_num: lesson_dict}
    lesson_map = {item.get("lesson"): item for item in lessons_today}
    sorted_lesson_nums = sorted(lesson_map.keys())

    first_lesson_num = sorted_lesson_nums[0]
    last_lesson_num = sorted_lesson_nums[-1]

    first_start = bells.get(first_lesson_num, (time(8, 15), time(9, 45)))[0]
    last_end = bells.get(last_lesson_num, (time(18, 35), time(20, 5)))[1]

    # 1. Если пары сегодня еще не начались
    if now_time < first_start:
        first_lesson = lesson_map[first_lesson_num]
        first_dt = datetime.combine(today_date, first_start, tzinfo=TIMEZONE)
        diff_mins = max(1, int((first_dt - now_dt).total_seconds() // 60))
        time_left_str = format_minutes_delta(diff_mins)

        subj = html.escape(first_lesson.get("discipline_str") or "")
        room = html.escape(first_lesson.get("classroom_str") or "—")
        teacher = html.escape(first_lesson.get("person_str") or "—")

        return (
            f"💤 <b>Пары еще не начались</b>\n\n"
            f"⏳ До первой пары осталось: <b>{time_left_str}</b>\n\n"
            f"🔜 <b>1-я пара на сегодня ({first_lesson_num}-я по звонкам):</b>\n"
            f"⏰ Время: <code>{bells_str.get(first_lesson_num)}</code>\n"
            f"📚 <b>{subj}</b>\n"
            f"🚪 Ауд. <b>{room}</b>\n"
            f"🧑‍🏫 {teacher}"
        )

    # 2. Если все пары на сегодня закончились — умный анонс следующей пары
    if now_time > last_end:
        next_info = find_next_lessons_day(schedule_data, today_date, subgroup)
        if next_info:
            next_date, next_lessons = next_info
            n_first = next_lessons[0]
            n_num = n_first.get("lesson", 1)
            n_time = bells_str.get(n_num, "08:15–09:45")
            n_subj = html.escape(n_first.get("discipline_str") or "Занятие")
            n_room = html.escape(n_first.get("classroom_str") or "—")
            n_teacher = html.escape(n_first.get("person_str") or "—")

            day_diff = (next_date - today_date).days
            day_title = "Завтра" if day_diff == 1 else f"В {WEEKDAY_NAMES[next_date.isoweekday() - 1].lower()}"
            date_label = f"{day_title} ({next_date.strftime('%d.%m')})"

            return (
                "🎉 <b>На сегодня все пары закончились! Отличного отдыха!</b>\n\n"
                f"🔜 <b>Следующее занятие — {date_label}:</b>\n"
                f"🔔 <b>{n_num}-я пара</b> (<code>{n_time}</code>)\n"
                f"📚 <b>{n_subj}</b>\n"
                f"🚪 Ауд. <b>{n_room}</b>\n"
                f"🧑‍🏫 {n_teacher}"
            )
        return "🎉 <b>На сегодня все пары закончились! Отличного отдыха!</b>"

    # 3. Проверяем, идет ли пара сейчас
    for num in sorted_lesson_nums:
        if num not in bells:
            continue
        start_t, end_t = bells[num]
        if start_t <= now_time <= end_t:
            lesson = lesson_map[num]
            start_dt = datetime.combine(today_date, start_t, tzinfo=TIMEZONE)
            end_dt = datetime.combine(today_date, end_t, tzinfo=TIMEZONE)

            total_sec = max(1, (end_dt - start_dt).total_seconds())
            elapsed_sec = max(0, (now_dt - start_dt).total_seconds())
            percent = int(min(100, max(0, elapsed_sec / total_sec * 100)))
            progress = render_progress_bar(percent)

            mins_left = max(1, int((end_dt - now_dt).total_seconds() // 60))
            time_left_str = format_minutes_delta(mins_left)

            subj = html.escape(lesson.get("discipline_str") or "")
            room = html.escape(lesson.get("classroom_str") or "—")
            teacher = html.escape(lesson.get("person_str") or "—")

            text = (
                f"🔴 <b>Сейчас идет {num}-я пара</b> (<code>{bells_str.get(num)}</code>)\n\n"
                f"📊 Прогресс: <code>[{progress}]</code> <b>{percent}%</b>\n"
                f"⏳ До конца пары: <b>{time_left_str}</b>\n\n"
                f"📚 <b>{subj}</b>\n"
                f"🚪 Ауд. <b>{room}</b>\n"
                f"🧑‍🏫 {teacher}"
            )

            # Добавляем анонс следующей пары
            future_nums = [n for n in sorted_lesson_nums if n > num]
            if future_nums:
                next_num = future_nums[0]
                next_l = lesson_map[next_num]
                next_subj = html.escape(next_l.get("discipline_str") or "")
                next_room = html.escape(next_l.get("classroom_str") or "—")
                text += f"\n\n🔜 <i>Следующая ({next_num}-я): {next_subj} (ауд. {next_room})</i>"

            return text

    # 4. Проверяем перемены или окна между парами
    next_num = None
    for num in sorted_lesson_nums:
        if num in bells:
            start_t, _ = bells[num]
            if start_t > now_time:
                next_num = num
                break

    if next_num is not None:
        next_lesson = lesson_map[next_num]
        next_start = bells[next_num][0]
        next_dt = datetime.combine(today_date, next_start, tzinfo=TIMEZONE)
        mins_left = max(1, int((next_dt - now_dt).total_seconds() // 60))
        time_left_str = format_minutes_delta(mins_left)

        next_subj = html.escape(next_lesson.get("discipline_str") or "")
        next_room = html.escape(next_lesson.get("classroom_str") or "—")
        next_teacher = html.escape(next_lesson.get("person_str") or "—")

        # Если между парами больше 30 минут — это «окно»
        is_break = mins_left <= 30
        status_title = (
            f"☕ <b>Сейчас перемена</b> (до {next_start.strftime('%H:%M')})"
            if is_break
            else "🕒 <b>Сейчас окно в расписании</b>"
        )

        return (
            f"{status_title}\n\n"
            f"⏳ До начала следующей пары: <b>{time_left_str}</b>\n\n"
            f"🔜 <b>Следующая ({next_num}-я пара):</b>\n"
            f"⏰ Время: <code>{bells_str.get(next_num)}</code>\n"
            f"📚 <b>{next_subj}</b>\n"
            f"🚪 Ауд. <b>{next_room}</b>\n"
            f"🧑‍🏫 {next_teacher}"
        )

    return "🔎 <b>Не удалось точно определить статус.</b>"


def format_bell_schedule(schedule_data: dict | None) -> str:
    """Форматирует наглядное расписание звонков и перемен."""
    bells = get_bell_schedule(schedule_data)
    lines = [
        "🔔 <b>Расписание звонков и перемен (АмГУ):</b>\n",
        "━━━━━━━━━━━━━━━━━━━━━",
    ]
    sorted_nums = sorted(bells.keys())
    for i, num in enumerate(sorted_nums):
        start, end = bells[num]
        s_str = start.strftime("%H:%M")
        e_str = end.strftime("%H:%M")
        lines.append(f"<b>{num}-я пара:</b> <code>{s_str} – {e_str}</code>")
        if i < len(sorted_nums) - 1:
            next_num = sorted_nums[i + 1]
            next_start = bells[next_num][0]
            break_mins = (next_start.hour * 60 + next_start.minute) - (end.hour * 60 + end.minute)
            if break_mins > 0:
                break_desc = "🍽 Большая перемена (обед)" if break_mins >= 30 else "☕ Перемена"
                lines.append(f"   <i>{break_desc}: {break_mins} мин</i>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def calculate_schedule_hash(data: dict | None) -> str:
    """Вычисляет детерминированный SHA256-хеш расписания."""
    if not data:
        return ""
    lines = sorted(
        [
            (
                x.get("weekday"),
                x.get("parity"),
                x.get("lesson"),
                x.get("subgroup", 0),
                (x.get("discipline_str") or "").strip(),
                (x.get("classroom_str") or "").strip(),
                (x.get("person_str") or "").strip(),
            )
            for x in data.get("timetable_tamplate_lines", [])
            if (x.get("discipline_str") or "").strip()
        ]
    )
    raw = repr({"week": data.get("current_week"), "lines": lines}).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def compute_schedule_diff(
    old_data: dict | None,
    new_data: dict | None,
) -> list[str]:
    """
    Сравнивает два слепка расписания и возвращает список текстовых описаний изменений.
    """
    if not old_data or not new_data:
        return []

    old_lines = old_data.get("timetable_tamplate_lines", [])
    new_lines = new_data.get("timetable_tamplate_lines", [])

    def to_map(lines):
        res = {}
        for item in lines:
            subj = (item.get("discipline_str") or "").strip()
            if not subj:
                continue
            key = (
                item.get("weekday"),
                item.get("parity"),
                item.get("lesson"),
                item.get("subgroup", 0),
            )
            res[key] = item
        return res

    old_map = to_map(old_lines)
    new_map = to_map(new_lines)

    diffs = []
    all_keys = sorted(set(old_map.keys()) | set(new_map.keys()))

    for key in all_keys:
        weekday, parity, lesson, subgroup = key
        day_name = WEEKDAY_NAMES[weekday - 1] if 1 <= weekday <= 7 else f"День {weekday}"
        parity_str = "нечетная нед." if parity == 1 else ("четная нед." if parity == 2 else "все нед.")
        sub_str = f" [п/г {subgroup}]" if subgroup > 0 else ""
        prefix = f"📅 <b>{day_name}</b> ({parity_str}), {lesson}-я пара{sub_str}:"

        if key not in old_map and key in new_map:
            item = new_map[key]
            subj = html.escape(item.get("discipline_str", ""))
            room = html.escape(item.get("classroom_str", "—"))
            diffs.append(f"➕ {prefix} <b>Добавлена пара:</b> «{subj}» (ауд. <b>{room}</b>)")

        elif key in old_map and key not in new_map:
            item = old_map[key]
            subj = html.escape(item.get("discipline_str", ""))
            diffs.append(f"❌ {prefix} <b>Отменена пара:</b> «{subj}»")

        else:
            old_item = old_map[key]
            new_item = new_map[key]
            changes = []

            old_subj = (old_item.get("discipline_str") or "").strip()
            new_subj = (new_item.get("discipline_str") or "").strip()
            if old_subj != new_subj:
                changes.append(f"предмет изменен на «{html.escape(new_subj)}»")

            old_room = (old_item.get("classroom_str") or "").strip()
            new_room = (new_item.get("classroom_str") or "").strip()
            if old_room != new_room:
                changes.append(f"аудитория изменена на <b>{html.escape(new_room)}</b>")

            old_teacher = (old_item.get("person_str") or "").strip()
            new_teacher = (new_item.get("person_str") or "").strip()
            if old_teacher != new_teacher:
                changes.append(f"преподаватель изменен на {html.escape(new_teacher)}")

            if changes:
                diffs.append(f"✏️ {prefix} {'; '.join(changes)}")

    return diffs


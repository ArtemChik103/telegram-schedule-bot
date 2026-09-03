import uuid
from datetime import datetime, timedelta
from src.config import TIMEZONE, GROUP_NAME
from src.services.schedule_service import (
    get_week_type,
    get_bell_schedule,
)

# Дни недели для формата iCalendar (RRULE BYDAY)
ICAL_BYDAY = {
    1: "MO",
    2: "TU",
    3: "WE",
    4: "TH",
    5: "FR",
    6: "SA",
    7: "SU",
}


def generate_ics_calendar(
    schedule_data: dict,
    subgroup: int = 0,
    semester_weeks: int = 18,
) -> str:
    """
    Генерирует стандартный iCalendar (.ics) файл расписания для группы на семестр.
    Поддерживает:
    - Еженедельные пары (parity=0) через INTERVAL=1
    - Четные/нечетные недели (parity=1, 2) через INTERVAL=2
    - Напоминания (VALARM за 15 минут до начала пары)
    - Аудитории, преподаватели, предметы
    """
    now_utc_str = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    today_local = datetime.now(TIMEZONE).date()

    # Понедельник текущей недели
    current_monday = today_local - timedelta(days=today_local.weekday())
    current_week_type = get_week_type(schedule_data, current_monday)

    odd_monday = (
        current_monday if current_week_type == 1 else current_monday + timedelta(days=7)
    )
    even_monday = (
        current_monday if current_week_type == 2 else current_monday + timedelta(days=7)
    )

    bells = get_bell_schedule(schedule_data)

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//AmSU Schedule Bot//AmSU Schedule 2.0//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:Расписание {GROUP_NAME}",
        "X-WR-TIMEZONE:Asia/Yakutsk",
        "BEGIN:VTIMEZONE",
        "TZID:Asia/Yakutsk",
        "BEGIN:STANDARD",
        "DTSTART:19700101T000000",
        "TZOFFSETFROM:+0900",
        "TZOFFSETTO:+0900",
        "TZNAME:+09",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]

    all_lines = schedule_data.get("timetable_tamplate_lines", [])

    for item in all_lines:
        discipline = (item.get("discipline_str") or "").strip()
        if not discipline:
            continue

        item_subgroup = item.get("subgroup", 0)
        if subgroup != 0 and item_subgroup not in (0, subgroup):
            continue

        weekday = item.get("weekday", 1)
        if weekday < 1 or weekday > 6:
            continue

        parity = item.get("parity", 0)
        lesson_num = item.get("lesson", 1)
        start_t, end_t = bells.get(lesson_num, (None, None))
        if not start_t or not end_t:
            continue

        if parity == 0:
            first_monday = current_monday
            interval = 1
            rrule_count = semester_weeks
        elif parity == 1:
            first_monday = odd_monday
            interval = 2
            rrule_count = semester_weeks // 2
        else:
            first_monday = even_monday
            interval = 2
            rrule_count = semester_weeks // 2

        event_date = first_monday + timedelta(days=weekday - 1)
        byday = ICAL_BYDAY[weekday]

        subject = discipline
        classroom = item.get("classroom_str") or "АмГУ"
        teacher = item.get("person_str") or ""
        sub_info = (
            f"Подгруппа {item_subgroup}" if item_subgroup else ""
        )

        dtstart_str = (
            f"{event_date.strftime('%Y%m%d')}T{start_t.strftime('%H%M%S')}"
        )
        dtend_str = (
            f"{event_date.strftime('%Y%m%d')}T{end_t.strftime('%H%M%S')}"
        )
        uid = f"{uuid.uuid4()}@amursu-bot"

        description_parts = []
        if teacher:
            description_parts.append(f"Преподаватель: {teacher}")
        if sub_info:
            description_parts.append(sub_info)
        description_parts.append(f"Пара №{lesson_num}")
        description = "\\n".join(description_parts)

        location_str = f"АмГУ, ауд. {classroom}" if "АмГУ" not in classroom else classroom

        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{now_utc_str}",
                f"DTSTART;TZID=Asia/Yakutsk:{dtstart_str}",
                f"DTEND;TZID=Asia/Yakutsk:{dtend_str}",
                f"RRULE:FREQ=WEEKLY;INTERVAL={interval};COUNT={rrule_count};BYDAY={byday}",
                f"SUMMARY:{subject} (ауд. {classroom})",
                f"LOCATION:{location_str}",
                f"DESCRIPTION:{description}",
                "STATUS:CONFIRMED",
                "BEGIN:VALARM",
                "TRIGGER:-PT15M",
                "ACTION:DISPLAY",
                f"DESCRIPTION:Скоро пара: {subject}",
                "END:VALARM",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


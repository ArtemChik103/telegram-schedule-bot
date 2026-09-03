from datetime import datetime, date, time, timedelta
from src.services.schedule_service import (
    parse_iso_time,
    get_bell_schedule,
    get_bell_schedule_str,
    get_week_type,
    get_lessons_for_day,
    render_progress_bar,
    format_minutes_delta,
    format_day_schedule,
)


def test_parse_iso_time():
    t = parse_iso_time("2000-01-01T08:15:00.000Z")
    assert t == time(8, 15)
    t2 = parse_iso_time("2000-01-01T18:35:00.000Z")
    assert t2 == time(18, 35)


def test_get_bell_schedule_dynamic():
    sample_data = {
        "schedule_lines": [
            {
                "lesson": 1,
                "begin_time": "2000-01-01T08:15:00.000Z",
                "end_time": "2000-01-01T09:45:00.000Z",
            },
            {
                "lesson": 2,
                "begin_time": "2000-01-01T09:55:00.000Z",
                "end_time": "2000-01-01T11:25:00.000Z",
            },
            {
                "lesson": 7,
                "begin_time": "2000-01-01T18:35:00.000Z",
                "end_time": "2000-01-01T20:05:00.000Z",
            },
        ]
    }
    bells = get_bell_schedule(sample_data)
    assert 1 in bells
    assert bells[1] == (time(8, 15), time(9, 45))
    assert 7 in bells
    assert bells[7] == (time(18, 35), time(20, 5))

    bells_str = get_bell_schedule_str(sample_data)
    assert bells_str[1] == "08:15–09:45"
    assert bells_str[7] == "18:35–20:05"


def test_week_parity_calculation():
    schedule_data = {"current_week": 1}
    # Базовая дата: понедельник
    base_monday = date(2026, 9, 7)
    assert get_week_type(schedule_data, base_monday, reference_date=base_monday) == 1

    # Следующая неделя: понедельник (+7 дней)
    next_monday = date(2026, 9, 14)
    assert get_week_type(schedule_data, next_monday, reference_date=base_monday) == 2

    # Через 2 недели (+14 дней)
    in_two_weeks = date(2026, 9, 21)
    assert get_week_type(schedule_data, in_two_weeks, reference_date=base_monday) == 1


def test_get_lessons_for_day_filters_empty():
    sample_data = {
        "timetable_tamplate_lines": [
            {
                "weekday": 1,
                "parity": 1,
                "lesson": 1,
                "discipline_str": "",  # Пустой шаблон!
                "person_str": "",
                "classroom_str": "",
                "subgroup": 0,
            },
            {
                "weekday": 1,
                "parity": 1,
                "lesson": 2,
                "discipline_str": "Базы данных",
                "person_str": "Иванов И.И.",
                "classroom_str": "204 (8)",
                "subgroup": 0,
            },
            {
                "weekday": 1,
                "parity": 2,  # Другая четность!
                "lesson": 3,
                "discipline_str": "Математика",
                "person_str": "Петров П.П.",
                "classroom_str": "301",
                "subgroup": 0,
            },
        ]
    }

    # Для недели 1 (нечетной), день 1 (понедельник)
    lessons = get_lessons_for_day(sample_data, weekday=1, week_type=1)
    assert len(lessons) == 1
    assert lessons[0]["discipline_str"] == "Базы данных"
    assert lessons[0]["lesson"] == 2


def test_get_lessons_for_day_subgroups():
    sample_data = {
        "timetable_tamplate_lines": [
            {
                "weekday": 2,
                "parity": 0,
                "lesson": 1,
                "discipline_str": "Лекция Философия",
                "subgroup": 0,  # общая
            },
            {
                "weekday": 2,
                "parity": 0,
                "lesson": 2,
                "discipline_str": "Лаб. Английский (1 подгр)",
                "subgroup": 1,
            },
            {
                "weekday": 2,
                "parity": 0,
                "lesson": 2,
                "discipline_str": "Лаб. Английский (2 подгр)",
                "subgroup": 2,
            },
        ]
    }

    # Пользователь из 1-й подгруппы
    lessons_sub1 = get_lessons_for_day(sample_data, weekday=2, week_type=1, subgroup=1)
    assert len(lessons_sub1) == 2
    assert lessons_sub1[0]["discipline_str"] == "Лекция Философия"
    assert lessons_sub1[1]["discipline_str"] == "Лаб. Английский (1 подгр)"

    # Пользователь без фильтра подгрупп
    lessons_all = get_lessons_for_day(sample_data, weekday=2, week_type=1, subgroup=0)
    assert len(lessons_all) == 3


def test_render_progress_bar():
    assert render_progress_bar(0) == "░░░░░░░░░░"
    assert render_progress_bar(50) == "█████░░░░░"
    assert render_progress_bar(100) == "██████████"


def test_format_minutes_delta():
    assert format_minutes_delta(45) == "45 мин"
    assert format_minutes_delta(75) == "1 ч 15 мин"
    assert format_minutes_delta(120) == "2 ч"


def test_format_day_schedule():
    sample_data = {
        "current_week": 1,
        "schedule_lines": [
            {
                "lesson": 1,
                "begin_time": "2000-01-01T08:15:00.000Z",
                "end_time": "2000-01-01T09:45:00.000Z",
            }
        ],
        "timetable_tamplate_lines": [
            {
                "weekday": 1,
                "parity": 1,
                "lesson": 1,
                "discipline_str": "Теория информации",
                "person_str": "Сидоров С.С.",
                "classroom_str": "404",
                "subgroup": 0,
            }
        ],
    }

    # Понедельник текущей недели (Неделя 1)
    today = datetime.now().date()
    current_monday = today - timedelta(days=today.weekday())

    text = format_day_schedule(sample_data, target_date=current_monday)
    assert "Теория информации" in text
    assert "Сидоров С.С." in text
    assert "404" in text
    assert "08:15–09:45" in text


def test_format_bell_schedule():
    from src.services.schedule_service import format_bell_schedule
    sample_data = {
        "schedule_lines": [
            {
                "lesson": 1,
                "begin_time": "2000-01-01T08:15:00.000Z",
                "end_time": "2000-01-01T09:45:00.000Z",
            },
            {
                "lesson": 2,
                "begin_time": "2000-01-01T09:55:00.000Z",
                "end_time": "2000-01-01T11:25:00.000Z",
            },
        ]
    }
    bells_text = format_bell_schedule(sample_data)
    assert "Расписание звонков" in bells_text
    assert "1-я пара:" in bells_text
    assert "08:15" in bells_text
    assert "Перемена: 10 мин" in bells_text


def test_schedule_hash_and_diff():
    from src.services.schedule_service import calculate_schedule_hash, compute_schedule_diff

    old_data = {
        "current_week": 1,
        "timetable_tamplate_lines": [
            {
                "weekday": 1,
                "parity": 1,
                "lesson": 1,
                "discipline_str": "Физика",
                "classroom_str": "100",
                "person_str": "Иванов",
                "subgroup": 0,
            }
        ],
    }

    # Новое расписание: сменилась аудитория с 100 на 200 и добавлена пара
    new_data = {
        "current_week": 1,
        "timetable_tamplate_lines": [
            {
                "weekday": 1,
                "parity": 1,
                "lesson": 1,
                "discipline_str": "Физика",
                "classroom_str": "200",  # изменилась!
                "person_str": "Иванов",
                "subgroup": 0,
            },
            {
                "weekday": 1,
                "parity": 1,
                "lesson": 2,
                "discipline_str": "Математика",
                "classroom_str": "300",
                "person_str": "Петров",
                "subgroup": 0,
            },
        ],
    }

    old_hash = calculate_schedule_hash(old_data)
    new_hash = calculate_schedule_hash(new_data)
    assert old_hash != new_hash

    diffs = compute_schedule_diff(old_data, new_data)
    assert len(diffs) == 2
    diffs_joined = " ".join(diffs)
    assert "аудитория изменена" in diffs_joined
    assert "Добавлена пара" in diffs_joined
    assert "Математика" in diffs_joined


def test_week_parity_with_cached_date():
    from src.services.schedule_service import get_week_type
    # Если слепок сохранен 7 дней назад с current_week = 1, то через неделю (в следующий понедельник)
    # четность должна смениться на 2!
    base_monday = date(2026, 9, 7)
    next_monday = date(2026, 9, 14)

    cached_schedule = {
        "current_week": 1,
        "_cached_at_date": base_monday.strftime("%Y-%m-%d"),
    }
    # Для следующего понедельника
    parity = get_week_type(cached_schedule, target_date=next_monday)
    assert parity == 2

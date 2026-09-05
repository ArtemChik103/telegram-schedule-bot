import pytest
from datetime import date
from src.services.schedule_service import (
    search_teachers,
    format_teacher_day_schedule,
    get_teacher_current_status,
)


def test_search_teachers():
    sample_teachers = [
        {"id": 1, "name": "Иванов Иван Иванович"},
        {"id": 2, "name": "Петров Петр Петрович"},
        {"id": 3, "name": "Иванова Анна Сергеевна"},
        {"id": 4, "name": "Рябова Светлана Николаевна"},
    ]

    # Поиск по подстроке
    res = search_teachers("иван", sample_teachers)
    assert len(res) == 2
    assert res[0]["id"] == 1
    assert res[1]["id"] == 3

    # Поиск точной фамилии
    res_ryabova = search_teachers("рябова", sample_teachers)
    assert len(res_ryabova) == 1
    assert res_ryabova[0]["id"] == 4

    # Пустой запрос
    assert search_teachers("", sample_teachers) == []

    # Не найдено
    assert search_teachers("Сидоров", sample_teachers) == []


def test_format_teacher_day_schedule():
    sample_data = {
        "teacher": {"id": 100, "name": "Иванов И.И."},
        "current_week": 1,
        "_cached_at_date": "2026-09-07",
        "schedule_lines": [
            {
                "lesson": 1,
                "begin_time": "2000-01-01T08:15:00.000Z",
                "end_time": "2000-01-01T09:45:00.000Z",
            }
        ],
        "timetable_tamplate_lines": [
            {
                "weekday": 1,  # Понедельник
                "parity": 1,
                "lesson": 1,
                "discipline_str": "Программирование",
                "classroom_str": "204",
                "group_str": "ИС231",
            }
        ],
    }

    # Понедельник недели 1
    target_monday = date(2026, 9, 7)
    text = format_teacher_day_schedule(sample_data, target_monday)
    assert "Иванов И.И." in text
    assert "Программирование" in text
    assert "ИС231" in text
    assert "204" in text


def test_get_teacher_current_status():
    sample_data = {
        "teacher": {"id": 100, "name": "Иванов И.И."},
        "current_week": 1,
        "schedule_lines": [],
        "timetable_tamplate_lines": [],
    }
    status = get_teacher_current_status(sample_data)
    assert "Иванов И.И." in status


def test_get_group_teachers():
    from src.services.schedule_service import get_group_teachers

    sample_group_data = {
        "timetable_tamplate_lines": [
            {"person_id": 28293, "person_str": "Шульгина Н.Г."},
            {"person_id": 68508, "person_str": "Казакова Т.А."},
            {"person_id": 28293, "person_str": "Шульгина Н.Г."},  # дубликат
            {"person_id": None, "person_str": ""},
        ]
    }
    teachers = get_group_teachers(sample_group_data)
    assert len(teachers) == 2
    names = [t["name"] for t in teachers]
    assert "Шульгина Н.Г." in names
    assert "Казакова Т.А." in names


def test_get_teachers_inline_keyboard():
    from src.keyboards.markups import get_teachers_inline_keyboard

    teachers = [
        {"id": 1, "name": "Казакова Татьяна Анатольевна"},
        {"id": 2, "name": "Шульгина Наталья Геннадьевна"},
        {"id": 3, "name": "Михелкин Владимир Алексеевич"},
    ]
    markup = get_teachers_inline_keyboard(teachers)
    # Должно быть 2 строки: первая с 2 кнопками, вторая с 1
    assert len(markup.inline_keyboard) == 2
    assert len(markup.inline_keyboard[0]) == 2
    assert len(markup.inline_keyboard[1]) == 1
    assert markup.inline_keyboard[0][0].callback_data == "teacher_select_1"
    assert markup.inline_keyboard[0][0].text == "Казакова Т.А."


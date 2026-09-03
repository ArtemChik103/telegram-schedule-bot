from src.services.ics_generator import generate_ics_calendar


def test_generate_ics_calendar_structure():
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
                "discipline_str": "Информатика",
                "person_str": "Преподаватель П.П.",
                "classroom_str": "204",
                "subgroup": 0,
            }
        ],
    }

    ics = generate_ics_calendar(sample_data, subgroup=0, semester_weeks=18)

    # Проверяем обязательные поля RFC 5545
    assert "BEGIN:VCALENDAR" in ics
    assert "END:VCALENDAR" in ics
    assert "BEGIN:VTIMEZONE" in ics
    assert "TZID:Asia/Yakutsk" in ics
    assert "BEGIN:VEVENT" in ics
    assert "SUMMARY:Информатика (ауд. 204)" in ics
    assert "RRULE:FREQ=WEEKLY;INTERVAL=2" in ics
    assert "BEGIN:VALARM" in ics
    assert "TRIGGER:-PT15M" in ics


def test_generate_ics_calendar_every_week():
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
                "weekday": 2,
                "parity": 0,  # Каждую неделю!
                "lesson": 1,
                "discipline_str": "Высшая математика",
                "person_str": "Иванов И.И.",
                "classroom_str": "101",
                "subgroup": 0,
            }
        ],
    }

    ics = generate_ics_calendar(sample_data, subgroup=0, semester_weeks=18)
    assert "RRULE:FREQ=WEEKLY;INTERVAL=1;COUNT=18" in ics
    assert ics.count("BEGIN:VEVENT") == 1  # Ровно одно событие, без дубликатов!

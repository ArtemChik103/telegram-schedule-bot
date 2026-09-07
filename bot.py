"""
Главная точка входа для запуска Telegram-бота расписания АмГУ 2.0.
Запуск: python bot.py
"""
import sys
import os
import socket

# Патч DNS для Telegram API: принудительный маршрут на доступный IP 149.154.167.220 (обход блокировок хостинга/ТСПУ)
_orig_getaddrinfo = socket.getaddrinfo


def _telegram_dns_patch(host, port, family=0, type=0, proto=0, flags=0):
    if host == "api.telegram.org":
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("149.154.167.220", port))
        ]
    return _orig_getaddrinfo(host, port, family, type, proto, flags)


socket.getaddrinfo = _telegram_dns_patch

# Добавляем корневую директорию проекта в sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.bot import main

if __name__ == "__main__":
    main()
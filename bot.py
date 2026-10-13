"""
Главная точка входа для запуска Telegram-бота расписания АмГУ 2.0.
Запуск: python bot.py
"""
import sys
import os
import socket

# Патч DNS для Telegram API: принудительный маршрут на доступный IP (обход блокировок хостинга/ТСПУ)
TELEGRAM_API_IP = os.getenv("TELEGRAM_API_IP", "149.154.167.220").strip()
_orig_getaddrinfo = socket.getaddrinfo


def _telegram_dns_patch(host, port, family=0, type=0, proto=0, flags=0):
    host_str = (
        host.decode("utf-8", errors="ignore")
        if isinstance(host, bytes)
        else str(host or "")
    )
    if (
        TELEGRAM_API_IP
        and TELEGRAM_API_IP.lower() not in ("none", "off", "disabled", "false", "")
        and host_str.rstrip(".").lower() == "api.telegram.org"
    ):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (TELEGRAM_API_IP, port))
        ]
    return _orig_getaddrinfo(host, port, family, type, proto, flags)


if TELEGRAM_API_IP and TELEGRAM_API_IP.lower() not in ("none", "off", "disabled", "false", ""):
    socket.getaddrinfo = _telegram_dns_patch

# Добавляем корневую директорию проекта в sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.bot import main

if __name__ == "__main__":
    main()
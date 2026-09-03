"""
Главная точка входа для запуска Telegram-бота расписания АмГУ 2.0.
Запуск: python bot.py
"""
import sys
import os

# Добавляем корневую директорию проекта в sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.bot import main

if __name__ == "__main__":
    main()
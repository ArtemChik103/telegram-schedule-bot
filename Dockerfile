FROM python:3.11-slim

# Устанавливаем часовой пояс и системные утилиты
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Yakutsk

WORKDIR /app

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY . .

# Создаем непривилегированного пользователя для безопасности
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Точка входа
CMD ["python", "bot.py"]

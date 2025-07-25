FROM python:3.12-slim-bullseye

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копирование файлов
COPY requirements.txt .
COPY apt-packages .
COPY main.py .

# Установка зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Запуск приложения
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]

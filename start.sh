#!/bin/bash

# Скрипт запуску Generator Bot
# Використання: ./start.sh

set -e

# Кольори для виводу
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Шлях до проекту (директорія, де знаходиться скрипт)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# Файли
PID_FILE="$PROJECT_DIR/bot.pid"
# LOG_FILE використовується тільки для інформації користувачу, bash в нього писати не буде
LOG_FILE="$PROJECT_DIR/bot.log"
VENV_DIR="$PROJECT_DIR/venv"

echo -e "${BLUE}🚀 Generator Bot - Запуск${NC}"
echo "================================"

# Перевірка, чи бот вже запущений
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  Бот вже запущений (PID: $OLD_PID)${NC}"
        echo -e "${YELLOW}Використайте ./stop.sh для зупинки або ./restart.sh для перезапуску${NC}"
        exit 1
    else
        echo -e "${YELLOW}⚠️  Знайдено застарілий PID файл, видаляю...${NC}"
        rm -f "$PID_FILE"
    fi
fi

# Перевірка наявності віртуального середовища
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${RED}❌ Віртуальне середовище не знайдено!${NC}"
    echo -e "${BLUE}Запустіть ./setup.sh для налаштування${NC}"
    exit 1
fi

# Перевірка .env файлу
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo -e "${RED}❌ Файл .env не знайдено!${NC}"
    echo -e "${YELLOW}Створіть .env файл з налаштуваннями${NC}"
    exit 1
fi

# Перевірка service_account.json
if [ ! -f "$PROJECT_DIR/service_account.json" ]; then
    echo -e "${YELLOW}⚠️  Файл service_account.json не знайдено!${NC}"
    echo -e "${YELLOW}Google Sheets синхронізація може не працювати${NC}"
fi

# Активація віртуального середовища
echo -e "${BLUE}🔧 Активація віртуального середовища...${NC}"
source "$VENV_DIR/bin/activate"

# Перевірка залежностей
echo -e "${BLUE}📦 Перевірка залежностей...${NC}"
if ! python -c "import aiogram" 2>/dev/null; then
    echo -e "${YELLOW}⚠️  Залежності не встановлені, встановлюю...${NC}"
    pip install -r requirements.txt --quiet
fi

# Створення резервної копії бази даних (якщо існує)
if [ -f "$PROJECT_DIR/generator.db" ]; then
    BACKUP_DIR="$PROJECT_DIR/backups"
    mkdir -p "$BACKUP_DIR"
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    cp "$PROJECT_DIR/generator.db" "$BACKUP_DIR/generator_backup_$TIMESTAMP.db"
    echo -e "${GREEN}✅ Створено резервну копію БД${NC}"
    
    # Видалення старих бекапів (залишаємо останні 10)
    cd "$BACKUP_DIR"
    ls -t generator_backup_*.db | tail -n +11 | xargs -r rm
    cd "$PROJECT_DIR"
fi

# Запуск бота в фоновому режимі
echo -e "${BLUE}🚀 Запуск бота...${NC}"

# ВИПРАВЛЕНО: перенаправлення в /dev/null, бо Python сам пише в лог-файл
nohup python main.py > /dev/null 2>&1 &
BOT_PID=$!

# Збереження PID
echo "$BOT_PID" > "$PID_FILE"

# Перевірка, чи процес запустився
sleep 2
if ps -p "$BOT_PID" > /dev/null; then
    echo -e "${GREEN}✅ Бот успішно запущено!${NC}"
    echo -e "${GREEN}PID: $BOT_PID${NC}"
    echo ""
    echo -e "${BLUE}📋 Корисні команди:${NC}"
    echo -e "  ./stop.sh      - Зупинити бота"
    echo -e "  ./restart.sh   - Перезапустити бота"
    echo -e "  ./logs.sh      - Переглянути логи"
    echo -e "  tail -f bot.log - Переглянути логи в реальному часі"
    echo ""
    echo -e "${BLUE}📂 Файли:${NC}"
    echo -e "  PID файл: $PID_FILE"
    echo -e "  Лог файл: $LOG_FILE (ротація активна)"
else
    echo -e "${RED}❌ Помилка запуску бота!${NC}"
    # Якщо бот впав одразу, дивимся в bot.log, бо Python встиг би щось туди написати
    echo -e "${YELLOW}Перевірте логи: tail -f $LOG_FILE${NC}"
    rm -f "$PID_FILE"
    exit 1
fi
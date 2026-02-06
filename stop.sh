#!/bin/bash

# Скрипт зупинки Generator Bot
# Використання: ./stop.sh

set -e

# Кольори для виводу
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Шлях до проекту
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

PID_FILE="$PROJECT_DIR/bot.pid"

echo -e "${BLUE}🛑 Generator Bot - Зупинка${NC}"
echo "================================"

# Перевірка наявності PID файлу
if [ ! -f "$PID_FILE" ]; then
    echo -e "${YELLOW}⚠️  Бот не запущений (PID файл не знайдено)${NC}"
    exit 0
fi

# Читання PID
BOT_PID=$(cat "$PID_FILE")

# Перевірка, чи процес існує
if ! ps -p "$BOT_PID" > /dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  Процес з PID $BOT_PID не знайдено${NC}"
    echo -e "${YELLOW}Видаляю застарілий PID файл...${NC}"
    rm -f "$PID_FILE"
    exit 0
fi

# Зупинка процесу
echo -e "${BLUE}🔄 Зупиняю бота (PID: $BOT_PID)...${NC}"
kill "$BOT_PID"

# Очікування завершення процесу (максимум 10 секунд)
COUNTER=0
while ps -p "$BOT_PID" > /dev/null 2>&1; do
    if [ $COUNTER -ge 10 ]; then
        echo -e "${YELLOW}⚠️  Процес не відповідає, примусова зупинка...${NC}"
        kill -9 "$BOT_PID" 2>/dev/null || true
        break
    fi
    sleep 1
    COUNTER=$((COUNTER + 1))
    echo -n "."
done
echo ""

# Видалення PID файлу
rm -f "$PID_FILE"

echo -e "${GREEN}✅ Бот успішно зупинено!${NC}"

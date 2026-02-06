#!/bin/bash

# Скрипт перевірки статусу Generator Bot
# Використання: ./status.sh

set -e

# Кольори для виводу
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Шлях до проекту
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

PID_FILE="$PROJECT_DIR/bot.pid"
LOG_FILE="$PROJECT_DIR/bot.log"

clear
echo -e "${CYAN}"
echo "╔════════════════════════════════════════╗"
echo "║    Generator Bot - Статус              ║"
echo "╚════════════════════════════════════════╝"
echo -e "${NC}"

# Статус процесу
echo -e "${BLUE}🔄 Статус процесу:${NC}"
if [ -f "$PID_FILE" ]; then
    BOT_PID=$(cat "$PID_FILE")
    if ps -p "$BOT_PID" > /dev/null 2>&1; then
        echo -e "${GREEN}  ✅ Бот запущено (PID: $BOT_PID)${NC}"
        
        # Час роботи
        START_TIME=$(ps -p "$BOT_PID" -o lstart= 2>/dev/null || echo "Невідомо")
        echo -e "${BLUE}  ⏰ Запущено: ${NC}$START_TIME"
        
        # Використання CPU та пам'яті
        if command -v ps &> /dev/null; then
            CPU=$(ps -p "$BOT_PID" -o %cpu= 2>/dev/null | tr -d ' ' || echo "N/A")
            MEM=$(ps -p "$BOT_PID" -o %mem= 2>/dev/null | tr -d ' ' || echo "N/A")
            echo -e "${BLUE}  💻 CPU: ${NC}${CPU}%"
            echo -e "${BLUE}  🧠 RAM: ${NC}${MEM}%"
        fi
    else
        echo -e "${RED}  ❌ Бот не запущено (застарілий PID)${NC}"
    fi
else
    echo -e "${RED}  ❌ Бот не запущено${NC}"
fi

echo ""

# Перевірка файлів
echo -e "${BLUE}📂 Перевірка файлів:${NC}"

# .env
if [ -f ".env" ]; then
    echo -e "${GREEN}  ✅ .env${NC}"
else
    echo -e "${RED}  ❌ .env${NC}"
fi

# service_account.json
if [ -f "service_account.json" ]; then
    echo -e "${GREEN}  ✅ service_account.json${NC}"
else
    echo -e "${YELLOW}  ⚠️  service_account.json${NC}"
fi

# База даних
if [ -f "generator.db" ]; then
    DB_SIZE=$(du -h generator.db | cut -f1)
    echo -e "${GREEN}  ✅ generator.db (${DB_SIZE})${NC}"
else
    echo -e "${YELLOW}  ⚠️  generator.db${NC}"
fi

# Логи
if [ -f "$LOG_FILE" ]; then
    LOG_SIZE=$(du -h "$LOG_FILE" | cut -f1)
    LOG_LINES=$(wc -l < "$LOG_FILE")
    echo -e "${GREEN}  ✅ bot.log (${LOG_SIZE}, ${LOG_LINES} рядків)${NC}"
else
    echo -e "${YELLOW}  ⚠️  bot.log${NC}"
fi

# Віртуальне середовище
if [ -d "venv" ]; then
    echo -e "${GREEN}  ✅ venv${NC}"
else
    echo -e "${RED}  ❌ venv${NC}"
fi

echo ""

# Останні події з логу
echo -e "${BLUE}📋 Останні події (5 рядків):${NC}"
if [ -f "$LOG_FILE" ]; then
    tail -n 5 "$LOG_FILE" | while IFS= read -r line; do
        if echo "$line" | grep -q "ERROR"; then
            echo -e "${RED}  $line${NC}"
        elif echo "$line" | grep -q "WARNING"; then
            echo -e "${YELLOW}  $line${NC}"
        else
            echo -e "  $line"
        fi
    done
else
    echo -e "${YELLOW}  Лог файл відсутній${NC}"
fi

echo ""

# Підрахунок помилок
if [ -f "$LOG_FILE" ]; then
    ERROR_COUNT=$(grep -c "ERROR" "$LOG_FILE" 2>/dev/null || echo "0")
    WARNING_COUNT=$(grep -c "WARNING" "$LOG_FILE" 2>/dev/null || echo "0")
    
    echo -e "${BLUE}⚠️  Статистика логів:${NC}"
    if [ "$ERROR_COUNT" -gt 0 ]; then
        echo -e "${RED}  ❌ Помилок: $ERROR_COUNT${NC}"
    else
        echo -e "${GREEN}  ✅ Помилок: 0${NC}"
    fi
    
    if [ "$WARNING_COUNT" -gt 0 ]; then
        echo -e "${YELLOW}  ⚠️  Попереджень: $WARNING_COUNT${NC}"
    else
        echo -e "${GREEN}  ✅ Попереджень: 0${NC}"
    fi
fi

echo ""

# Використання диску
echo -e "${BLUE}💾 Використання диску:${NC}"
DISK_USAGE=$(df -h "$PROJECT_DIR" | tail -1 | awk '{print $5}')
echo -e "  Диск зайнято: ${DISK_USAGE}"

echo ""
echo -e "${CYAN}╚════════════════════════════════════════╝${NC}"

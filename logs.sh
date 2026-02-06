#!/bin/bash

# Скрипт перегляду логів Generator Bot
# Використання: 
#   ./logs.sh           - останні 50 рядків
#   ./logs.sh 100       - останні 100 рядків
#   ./logs.sh follow    - слідкувати за логами в реальному часі

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

LOG_FILE="$PROJECT_DIR/bot.log"

echo -e "${BLUE}📋 Generator Bot - Перегляд логів${NC}"
echo "================================"

# Перевірка наявності лог файлу
if [ ! -f "$LOG_FILE" ]; then
    echo -e "${YELLOW}⚠️  Лог файл не знайдено: $LOG_FILE${NC}"
    echo -e "${YELLOW}Бот, можливо, ще не запускався${NC}"
    exit 0
fi

# Визначення режиму
MODE="${1:-50}"

if [ "$MODE" = "follow" ] || [ "$MODE" = "f" ]; then
    echo -e "${BLUE}📡 Слідкування за логами (Ctrl+C для виходу)${NC}"
    echo ""
    tail -f "$LOG_FILE" | while IFS= read -r line; do
        # Кольорове виділення
        if echo "$line" | grep -q "ERROR"; then
            echo -e "${RED}$line${NC}"
        elif echo "$line" | grep -q "WARNING"; then
            echo -e "${YELLOW}$line${NC}"
        elif echo "$line" | grep -q "INFO"; then
            echo -e "${GREEN}$line${NC}"
        else
            echo "$line"
        fi
    done
elif [ "$MODE" = "clear" ] || [ "$MODE" = "c" ]; then
    echo -e "${YELLOW}⚠️  Видалити лог файл? (y/n)${NC}"
    read -r CONFIRM
    if [ "$CONFIRM" = "y" ] || [ "$CONFIRM" = "Y" ]; then
        rm -f "$LOG_FILE"
        echo -e "${GREEN}✅ Лог файл видалено${NC}"
    else
        echo -e "${BLUE}❌ Скасовано${NC}"
    fi
elif [ "$MODE" = "errors" ] || [ "$MODE" = "e" ]; then
    echo -e "${BLUE}🔴 Показую тільки помилки:${NC}"
    echo ""
    grep -i "error" "$LOG_FILE" | tail -n 50 | while IFS= read -r line; do
        echo -e "${RED}$line${NC}"
    done
else
    # Показати останні N рядків
    LINES="$MODE"
    echo -e "${BLUE}📄 Останні $LINES рядків:${NC}"
    echo ""
    tail -n "$LINES" "$LOG_FILE" | while IFS= read -r line; do
        # Кольорове виділення
        if echo "$line" | grep -q "ERROR"; then
            echo -e "${RED}$line${NC}"
        elif echo "$line" | grep -q "WARNING"; then
            echo -e "${YELLOW}$line${NC}"
        elif echo "$line" | grep -q "INFO"; then
            echo -e "${GREEN}$line${NC}"
        else
            echo "$line"
        fi
    done
fi

echo ""
echo -e "${BLUE}💡 Підказка:${NC}"
echo -e "  ./logs.sh follow   - слідкувати за логами"
echo -e "  ./logs.sh errors   - показати тільки помилки"
echo -e "  ./logs.sh 200      - показати 200 рядків"
echo -e "  ./logs.sh clear    - очистити лог файл"

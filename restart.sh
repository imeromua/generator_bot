#!/bin/bash

# Скрипт перезапуску Generator Bot
# Використання: ./restart.sh

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

echo -e "${BLUE}🔄 Generator Bot - Перезапуск${NC}"
echo "================================"

# Зупинка бота
if [ -f "$PROJECT_DIR/bot.pid" ]; then
    echo -e "${BLUE}1️⃣ Зупинка бота...${NC}"
    bash "$PROJECT_DIR/stop.sh"
    sleep 2
else
    echo -e "${YELLOW}⚠️  Бот не запущений, пропускаю зупинку${NC}"
fi

# Запуск бота
echo -e "${BLUE}2️⃣ Запуск бота...${NC}"
bash "$PROJECT_DIR/start.sh"

echo ""
echo -e "${GREEN}✅ Перезапуск завершено!${NC}"

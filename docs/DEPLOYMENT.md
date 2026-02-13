# 🚀 Deployment Guide

Посібник з розгортання generator_bot в різних середовищах.

## 📋 Зміст

- [Локальна розробка](#локальна-розробка)
- [Docker Compose](#docker-compose)
- [Production Deployment](#production-deployment)
- [Cloud Platforms](#cloud-platforms)
- [Моніторинг та логи](#моніторинг-та-логи)

---

## 🏠 Локальна розробка

### Встановлення залежностей

```bash
# Створити віртуальне середовище
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Встановити залежності
pip install -e ".[dev]"

# Встановити pre-commit hooks
pre-commit install
```

### Налаштування середовища

```bash
# Скопіювати приклад конфігурації
cp .env.example .env

# Відредагувати .env
nano .env
```

### Запуск

```bash
# Запустити бота
python main.py

# Запустити тести
pytest

# Запустити з coverage
pytest --cov --cov-report=html

# Перевірити код
ruff check .
black --check .
mypy .
```

---

## 🐳 Docker Compose

### Швидкий старт

```bash
# Створити .env файл
cp .env.example .env

# Додати service_account.json для Google Sheets
# (завантажити з Google Cloud Console)

# Запустити всі сервіси
docker-compose up -d

# Переглянути логи
docker-compose logs -f bot

# Зупинити
docker-compose down
```

### Структура сервісів

- **bot** - Основний Telegram бот
- **postgres** - База даних PostgreSQL 15
- **redis** - Кеш Redis 7
- **adminer** - Web UI для PostgreSQL (dev тільки)

### Доступ до сервісів

- Adminer: http://localhost:8080
  - System: PostgreSQL
  - Server: postgres
  - Username: botuser
  - Password: botpass
  - Database: generator_bot

### Backup бази даних

```bash
# Створити backup
docker-compose exec postgres pg_dump -U botuser generator_bot > backups/backup_$(date +%Y%m%d_%H%M%S).sql

# Відновити з backup
docker-compose exec -T postgres psql -U botuser generator_bot < backups/backup_20260213_210000.sql
```

---

## 🏭 Production Deployment

### Підготовка

1. **Оновити .env для production**

```env
MODE=PROD
DB_BACKEND=postgres
POSTGRES_DSN=postgresql://user:password@host:5432/generator_bot
REDIS_ENABLED=1
REDIS_URL=redis://host:6379/0
LOG_LEVEL=INFO
```

2. **Налаштувати PostgreSQL**

```sql
-- Створити користувача та БД
CREATE USER botuser WITH PASSWORD 'secure_password';
CREATE DATABASE generator_bot OWNER botuser;
GRANT ALL PRIVILEGES ON DATABASE generator_bot TO botuser;
```

3. **Налаштувати systemd сервіс**

```bash
# Створити /etc/systemd/system/generator-bot.service
sudo nano /etc/systemd/system/generator-bot.service
```

```ini
[Unit]
Description=Generator Bot
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=botuser
Group=botuser
WorkingDirectory=/opt/generator_bot
Environment="PATH=/opt/generator_bot/venv/bin"
ExecStart=/opt/generator_bot/venv/bin/python main.py
Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=generator-bot

# Security
PrivateTmp=yes
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/opt/generator_bot/logs

[Install]
WantedBy=multi-user.target
```

```bash
# Активувати та запустити
sudo systemctl daemon-reload
sudo systemctl enable generator-bot
sudo systemctl start generator-bot

# Переглянути статус
sudo systemctl status generator-bot

# Переглянути логи
sudo journalctl -u generator-bot -f
```

### Docker Production

```bash
# Build production image
docker build -t generator-bot:latest .

# Run with production compose
docker-compose -f docker-compose.prod.yml up -d
```

---

## ☁️ Cloud Platforms

### AWS (Elastic Beanstalk + RDS)

1. **Створити RDS PostgreSQL instance**
2. **Створити ElastiCache Redis cluster**
3. **Створити Elastic Beanstalk application**

```bash
# Install EB CLI
pip install awsebcli

# Initialize
eb init -p docker generator-bot

# Create environment
eb create generator-bot-prod \
  --instance-type t3.micro \
  --database.engine postgres \
  --database.size 20 \
  --envvars BOT_TOKEN=xxx,MODE=PROD

# Deploy
eb deploy

# View logs
eb logs
```

### Google Cloud Platform (Cloud Run + Cloud SQL)

```bash
# Build and push image
gcloud builds submit --tag gcr.io/PROJECT_ID/generator-bot

# Deploy to Cloud Run
gcloud run deploy generator-bot \
  --image gcr.io/PROJECT_ID/generator-bot \
  --platform managed \
  --region europe-west1 \
  --add-cloudsql-instances PROJECT_ID:europe-west1:generator-db \
  --set-env-vars MODE=PROD,BOT_TOKEN=xxx

# View logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=generator-bot" --limit 50
```

### Azure (Container Instances + PostgreSQL)

```bash
# Create resource group
az group create --name generator-bot-rg --location westeurope

# Create PostgreSQL
az postgres server create \
  --resource-group generator-bot-rg \
  --name generator-bot-db \
  --location westeurope \
  --admin-user botuser \
  --admin-password SecurePassword123 \
  --sku-name B_Gen5_1

# Deploy container
az container create \
  --resource-group generator-bot-rg \
  --name generator-bot \
  --image YOUR_REGISTRY/generator-bot:latest \
  --environment-variables \
    MODE=PROD \
    BOT_TOKEN=xxx \
    POSTGRES_DSN=postgresql://...

# View logs
az container logs --resource-group generator-bot-rg --name generator-bot --follow
```

---

## 📊 Моніторинг та логи

### Логування

Бот підтримує кілька рівнів логування:

```env
LOG_LEVEL=DEBUG  # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FILE=bot.log
LOG_MAX_BYTES=10485760  # 10MB
LOG_BACKUP_COUNT=5
```

### Структура логів

```
logs/
├── bot.log         # Поточний лог
├── bot.log.1       # Ротований лог
├── bot.log.2
└── ...
```

### Systemd журнал

```bash
# Всі логи
journalctl -u generator-bot

# Останні 100 рядків
journalctl -u generator-bot -n 100

# Follow режим
journalctl -u generator-bot -f

# За період
journalctl -u generator-bot --since "2026-02-13 20:00" --until "2026-02-13 21:00"

# Тільки помилки
journalctl -u generator-bot -p err
```

### Metrics та Health Checks

```bash
# Check bot process
ps aux | grep "python main.py"

# Check database connection
psql -h localhost -U botuser -d generator_bot -c "SELECT version();"

# Check Redis
redis-cli ping

# Check system resources
top -p $(pgrep -f "python main.py")
```

### Alerting

Рекомендовані інтеграції:

- **Sentry** - Error tracking
- **Prometheus + Grafana** - Metrics
- **ELK Stack** - Log aggregation
- **UptimeRobot** - Uptime monitoring

---

## 🔒 Security Checklist

- [ ] Не комітити `.env` та `service_account.json`
- [ ] Використовувати strong passwords для БД
- [ ] Обмежити доступ до БД по IP
- [ ] Регулярні backups
- [ ] Оновлювати залежності (`pip list --outdated`)
- [ ] Моніторити security alerts (Dependabot)
- [ ] HTTPS для всіх з'єднань
- [ ] Firewall rules для production
- [ ] Regular security audits (`bandit`, `safety`)

---

## 📞 Підтримка

Якщо виникли проблеми:

1. Перевірте логи: `docker-compose logs -f` або `journalctl -u generator-bot -f`
2. Перевірте статус сервісів: `docker-compose ps` або `systemctl status generator-bot`
3. Перегляньте [Issues](https://github.com/imeromua/generator_bot/issues)
4. Створіть новий issue з описом проблеми та логами

# Паралельний запуск test-інстансу (Docker)

Цей документ описує, як запустити **другий** інстанс `generator_bot` паралельно з продом (який крутиться з `main`), але на гілці `feature/modernization`.

## Ключові правила безпеки

1) **Потрібен інший BOT_TOKEN** (окремий тестовий бот у BotFather).
2) Якщо хочете "той самий Google Spreadsheet" — найкраще робити **ту саму таблицю (ID), але іншу вкладку (worksheet)**:
   - створіть вкладку-копію (наприклад `ЛЮТИЙ_TEST`),
   - в `.env` для тесту поставте `SHEET_ID_TEST=<той самий id>` і `SHEET_NAME=ЛЮТИЙ_TEST`.

> Авто-синхронізації з Sheets у планувальнику немає; синхронізація запускається вручну через адмінку.

## Кроки (на сервері)

### 1) Окрема директорія + checkout гілки

```bash
mkdir -p /opt/generator_bot_test
cd /opt/generator_bot_test

git clone -b feature/modernization --single-branch https://github.com/imeromua/generator_bot.git .
```

### 2) .env + service_account.json

```bash
cp .env.example .env
nano .env
# заповніть BOT_TOKEN (інший!), MODE=TEST, SHEET_ID_TEST, SHEET_NAME, ADMINS

# додайте google creds
ls -la service_account.json
```

### 3) Паралельний compose (без конфліктів імен/портів)

В репозиторії є `docker-compose.test.yml` — він змінює `container_name` і прибирає публічні порти для PostgreSQL/Redis.

```bash
# перевірка конфігу
docker compose -p genbot_test -f docker-compose.yml -f docker-compose.test.yml config

# перевірка збірки образу
docker compose -p genbot_test -f docker-compose.yml -f docker-compose.test.yml build --pull bot

# старт
docker compose -p genbot_test -f docker-compose.yml -f docker-compose.test.yml up -d

# логи
docker compose -p genbot_test -f docker-compose.yml -f docker-compose.test.yml logs -f bot
```

### 4) Зупинка test-інстансу

```bash
docker compose -p genbot_test -f docker-compose.yml -f docker-compose.test.yml down
```

Якщо треба прибрати і дані (volumes):

```bash
docker compose -p genbot_test -f docker-compose.yml -f docker-compose.test.yml down -v
```

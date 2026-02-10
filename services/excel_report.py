import logging
import os
from datetime import datetime, timedelta

import aiohttp
import gspread
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.service_account import Credentials

import config

logger = logging.getLogger(__name__)


_UA_MONTHS = {
    1: "СІЧЕНЬ",
    2: "ЛЮТИЙ",
    3: "БЕРЕЗЕНЬ",
    4: "КВІТЕНЬ",
    5: "ТРАВЕНЬ",
    6: "ЧЕРВЕНЬ",
    7: "ЛИПЕНЬ",
    8: "СЕРПЕНЬ",
    9: "ВЕРЕСЕНЬ",
    10: "ЖОВТЕНЬ",
    11: "ЛИСТОПАД",
    12: "ГРУДЕНЬ",
}


def _period_sheet_name(period: str) -> str:
    """Повертає назву вкладки (worksheet) для звіту."""
    now = datetime.now(config.KYIV)

    if period == "current":
        return (config.SHEET_NAME or _UA_MONTHS.get(now.month, "")).strip()

    # prev
    first_day_current = now.replace(day=1)
    last_day_prev = first_day_current - timedelta(days=1)
    return _UA_MONTHS.get(last_day_prev.month, (config.SHEET_NAME or "").strip())


def _build_creds() -> Credentials:
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    return Credentials.from_service_account_file("service_account.json", scopes=scopes)


async def _export_spreadsheet_xlsx(file_id: str, out_path: str, creds: Credentials) -> None:
    """Експортує Google Spreadsheet як .xlsx (з усіма вкладками) з оригінальним форматуванням."""
    creds.refresh(GoogleRequest())

    url = f"https://www.googleapis.com/drive/v3/files/{file_id}/export"
    params = {
        "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    headers = {
        "Authorization": f"Bearer {creds.token}",
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, headers=headers, timeout=120) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Drive export failed: status={resp.status}, body={text[:500]}")

            data = await resp.read()
            with open(out_path, "wb") as f:
                f.write(data)


async def generate_report(period: str):
    """Генерує Excel-звіт.

    Поточна реалізація: якщо інтеграція з Google Sheets увімкнена, звіт — це експорт
    Google Spreadsheet в .xlsx (зберігає форматування/шапки/заливки як у Google Sheets).

    Примітка: Якщо бот має працювати виключно від БД — цю функцію потрібно замінити
    на генератор, який будує .xlsx з даних БД (logs/state) без звернень до Google APIs.

    period: 'current' або 'prev'
    """
    try:
        if not config.SHEET_ID:
            return None, "❌ SHEET_ID не знайдено"

        if not os.path.exists("service_account.json"):
            return None, "❌ Файл service_account.json не знайдено"

        sheet_name = _period_sheet_name(period)

        creds = _build_creds()

        # Перевіримо, що потрібна вкладка існує (щоб дати нормальну підказку в caption)
        try:
            client = gspread.authorize(creds)
            ss = client.open_by_key(config.SHEET_ID)
            ws_names = [w.title for w in ss.worksheets()]
            if sheet_name and sheet_name not in ws_names:
                logger.warning(f"⚠️ Вкладка '{sheet_name}' не знайдена. Доступні: {ws_names}")
                # fallback
                sheet_name = config.SHEET_NAME if config.SHEET_NAME in ws_names else (ws_names[0] if ws_names else sheet_name)
        except Exception as e:
            logger.warning(f"⚠️ Не вдалося перевірити вкладки: {e}")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"report_{period}_{ts}.xlsx"

        await _export_spreadsheet_xlsx(config.SHEET_ID, filename, creds)

        caption = (
            f"📊 <b>Звіт (експорт оригінальної таблиці)</b>\n"
            f"📁 Файл: <code>{filename}</code>\n"
            f"📌 Відкрийте вкладку: <b>{sheet_name}</b>"
        )

        return filename, caption

    except Exception as e:
        logger.error(f"❌ Помилка генерації звіту: {e}", exc_info=True)
        return None, f"❌ Помилка генерації звіту: {str(e)}"

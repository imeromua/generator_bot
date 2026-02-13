"""Google Sheets client initialization."""

import os

import gspread
from google.oauth2.service_account import Credentials

import config

SERVICE_ACCOUNT_FILE = "service_account.json"


def validate_sync_prereqs() -> bool:
    """Перевіряє наявність необхідних даних для синхронізації.

    Returns:
        True if SHEET_ID configured and service account file exists
    """
    if not config.SHEET_ID:
        return False
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        return False
    return True


def make_client() -> gspread.Client:
    """Створює Google Sheets client.

    Returns:
        Authorized gspread client
    """
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    return gspread.authorize(creds)


def open_spreadsheet(client: gspread.Client) -> gspread.Spreadsheet:
    """Відкриває spreadsheet за ID.

    Args:
        client: Authorized gspread client

    Returns:
        Spreadsheet object
    """
    return client.open_by_key(config.SHEET_ID)


def open_main_worksheet(ss: gspread.Spreadsheet) -> gspread.Worksheet:
    """Відкриває основну вкладку.

    Args:
        ss: Spreadsheet object

    Returns:
        Main worksheet
    """
    return ss.worksheet(config.SHEET_NAME)

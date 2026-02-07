import os

import gspread
from google.oauth2.service_account import Credentials

import config

SERVICE_ACCOUNT_FILE = "service_account.json"


def validate_sync_prereqs() -> bool:
    if not config.SHEET_ID:
        return False
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        return False
    return True


def make_client():
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    return gspread.authorize(creds)


def open_spreadsheet(client):
    return client.open_by_key(config.SHEET_ID)


def open_main_worksheet(ss):
    return ss.worksheet(config.SHEET_NAME)

"""Google Sheets integration abstraction.

Isolates all ``gspread`` usage behind a clean interface so that the
service layer never imports gspread directly.
"""

import logging
import os
from typing import Any

import config

logger = logging.getLogger(__name__)


class GoogleSheetsClient:
    """Thin wrapper around gspread that services interact with.

    Raises ``RuntimeError`` when the required credentials file is missing
    or the ``SHEET_ID`` is not configured, instead of letting gspread
    raise a cryptic error.
    """

    def __init__(self, service_account_path: str | None = None, sheet_id: str | None = None) -> None:
        self._service_account_path: str = service_account_path or str(
            getattr(config, "SERVICE_ACCOUNT_PATH", "service_account.json")
        )
        self._sheet_id: str | None = sheet_id or getattr(config, "SHEET_ID", None)

    # ------------------------------------------------------------------
    # Prerequisite checks
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True when credentials file exists and SHEET_ID is set."""
        if not self._sheet_id:
            return False
        if not os.path.exists(self._service_account_path):
            return False
        return True

    # ------------------------------------------------------------------
    # Client / spreadsheet access
    # ------------------------------------------------------------------

    def get_client(self) -> Any:
        """Return an authorised gspread client."""
        try:
            import gspread
            from google.oauth2.service_account import Credentials
        except ImportError as exc:
            raise RuntimeError("gspread / google-auth packages are not installed") from exc

        if not os.path.exists(self._service_account_path):
            raise RuntimeError(f"Service account file not found: {self._service_account_path}")

        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(self._service_account_path, scopes=scopes)
        return gspread.authorize(creds)

    def get_spreadsheet(self) -> Any:
        """Return the spreadsheet object for the configured SHEET_ID."""
        if not self._sheet_id:
            raise RuntimeError("SHEET_ID is not configured")
        client = self.get_client()
        return client.open_by_key(self._sheet_id)

    def get_worksheet(self, sheet_name: str | None = None) -> Any:
        """Return a specific worksheet (defaults to ``config.SHEET_NAME``)."""
        name = sheet_name or getattr(config, "SHEET_NAME", "Sheet1")
        ss = self.get_spreadsheet()
        return ss.worksheet(name)

"""Utilities for generating iOS-friendly HTTP download headers."""

import re
import urllib.parse

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Транслітерація кирилиць -> ASCII для filename= (legacy clients)
_TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'h', 'д': 'd', 'е': 'e', 'є': 'ye',
    'ж': 'zh', 'з': 'z', 'и': 'y', 'і': 'i', 'ї': 'yi', 'й': 'y',
    'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
    'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts',
    'ч': 'ch', 'ш': 'sh', 'щ': 'shch', 'ь': '', 'ю': 'yu', 'я': 'ya',
    'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'H', 'Д': 'D', 'Е': 'E', 'Є': 'Ye',
    'Ж': 'Zh', 'З': 'Z', 'И': 'Y', 'І': 'I', 'Ї': 'Yi', 'Й': 'Y',
    'К': 'K', 'Л': 'L', 'М': 'M', 'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R',
    'С': 'S', 'Т': 'T', 'У': 'U', 'Ф': 'F', 'Х': 'Kh', 'Ц': 'Ts',
    'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Shch', 'Ь': '', 'Ю': 'Yu', 'Я': 'Ya',
    # Російські додаткові символи
    'ы': 'y', 'ъ': '', 'э': 'e', 'Щ': 'Shch',
}


def _to_ascii_filename(name: str) -> str:
    """Transliterate Ukrainian/Russian to ASCII, keep safe ASCII chars."""
    result = []
    for ch in name:
        if ch in _TRANSLIT:
            result.append(_TRANSLIT[ch])
        elif ord(ch) < 128:
            result.append(ch)
        else:
            result.append('_')
    ascii_name = ''.join(result)
    # Прибрати зайві підряд підкреслень
    ascii_name = re.sub(r'_+', '_', ascii_name).strip('_')
    return ascii_name


def build_xlsx_headers(filename: str, *, allow_cors: bool = False) -> dict:
    """Return HTTP headers for an XLSX file download compatible with iOS Safari.

    - ``filename=`` — ASCII transliteration (legacy clients, HTTP spec)
    - ``filename*=`` — RFC 5987 UTF-8 encoded (iOS 16+ Safari, modern browsers)
    """
    safe_filename = _sanitize_filename(filename)
    # ASCII fallback для filename= (HTTP header не приймає не-ASCII)
    ascii_filename = _to_ascii_filename(safe_filename)
    # RFC 5987 UTF-8 для filename*= (повна українська назва для iOS)
    encoded_name = urllib.parse.quote(safe_filename.encode('utf-8'), safe='')

    headers: dict = {
        "Content-Type": XLSX_CONTENT_TYPE,
        "Content-Disposition": (
            f'attachment; filename="{ascii_filename}"; '
            f"filename*=UTF-8''{encoded_name}"
        ),
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "X-Content-Type-Options": "nosniff",
    }
    if allow_cors:
        headers["Access-Control-Allow-Origin"] = "*"
    return headers


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_UNSAFE_CHARS = str.maketrans({c: '_' for c in ':/?*[]\\|"<>'})


def _sanitize_filename(name: str) -> str:
    """Replace filesystem-unsafe characters in *name* with underscores."""
    return name.translate(_UNSAFE_CHARS)

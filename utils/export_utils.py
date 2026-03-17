"""Utilities for generating iOS-friendly HTTP download headers."""

import urllib.parse

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def build_xlsx_headers(filename: str, *, allow_cors: bool = False) -> dict:
    """Return HTTP headers for an XLSX file download compatible with iOS Safari.

    Produces a ``Content-Disposition`` value that carries both the plain ASCII
    ``filename`` parameter (for legacy clients) and the RFC 5987 encoded
    ``filename*`` parameter (required by iOS 16+ Safari to save the file with
    a correct Ukrainian name in the Files app).

    Args:
        filename: The desired download filename, e.g.
            ``"Звіт_main_20260317.xlsx"``.  Characters that are illegal in
            file-system names (``:``, ``/``, ``\\``, ``?``, ``*``, ``[``,
            ``]``, ``|``, ``"``, ``<``, ``>``) are automatically replaced with
            underscores.
        allow_cors: When ``True``, adds ``Access-Control-Allow-Origin: *`` to
            support cross-origin downloads (e.g. WebView scenarios).

    Returns:
        A ``dict`` ready to be passed as the ``headers`` kwarg of a FastAPI
        ``Response`` object.
    """
    safe_filename = _sanitize_filename(filename)
    encoded_name = urllib.parse.quote(safe_filename, safe="")

    headers: dict = {
        "Content-Type": XLSX_CONTENT_TYPE,
        "Content-Disposition": (
            f'attachment; filename="{safe_filename}"; '
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

_UNSAFE_CHARS = str.maketrans({c: "_" for c in r':/?*[]\\|"<>'})


def _sanitize_filename(name: str) -> str:
    """Replace filesystem-unsafe characters in *name* with underscores."""
    return name.translate(_UNSAFE_CHARS)

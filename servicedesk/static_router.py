"""FastAPI static-files router for the ServiceDesk SPA.

Mounts the ``servicedesk/static/`` directory at the ``/sd`` prefix so that
the SPA (login, dashboard, CSS, JS, PWA manifest, …) is served directly
from the FastAPI process without a separate web server.

Usage (in ``webapp/app.py``)::

    from servicedesk.static_router import mount_sd_static
    mount_sd_static(app)
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

_SD_STATIC_DIR = Path(__file__).resolve().parent / "static"


def mount_sd_static(app: FastAPI) -> None:
    """Mount the ServiceDesk static directory at ``/sd``.

    The ``html=True`` flag enables automatic ``index.html`` serving for
    directory requests, which allows ``/sd/`` to redirect to the SPA entry
    point without an explicit route handler.
    """
    if _SD_STATIC_DIR.is_dir():
        app.mount(
            "/sd",
            StaticFiles(directory=str(_SD_STATIC_DIR), html=True),
            name="sd-static",
        )

"""FastAPI static-files router for the ServiceDesk SPA.

Mounts the ``servicedesk/static/`` directory at the ``/sd`` prefix so that
the SPA (login, dashboard, CSS, JS, PWA manifest, …) is served directly
from the FastAPI process without a separate web server.

Also exposes ``/.well-known/assetlinks.json`` required for Android TWA
(Trusted Web Activity) domain verification via Digital Asset Links.

Usage (in ``webapp/app.py``)::

    from servicedesk.static_router import mount_sd_static, router as sd_static_router
    app.include_router(sd_static_router)
    mount_sd_static(app)
"""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles

_SD_STATIC_DIR = Path(__file__).resolve().parent / "static"

router = APIRouter()

# Placeholder SHA-256 fingerprint – replace with the real signing-key
# fingerprint after generating a release keystore.
_PLACEHOLDER_SHA256 = "PLACEHOLDER_SHA256"


@router.get("/.well-known/assetlinks.json", include_in_schema=False)
async def assetlinks() -> list[dict[str, Any]]:
    """Digital Asset Links endpoint required for Android TWA verification.

    Place the actual SHA-256 certificate fingerprint of your release keystore
    (obtained via ``keytool -list -v -keystore release.jks``) in place of the
    placeholder value before publishing the app.
    """
    return [
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": "ua.imero.servicedesk",
                "sha256_cert_fingerprints": [_PLACEHOLDER_SHA256],
            },
        }
    ]


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

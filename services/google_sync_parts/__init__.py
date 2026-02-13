"""Google Sheets sync utilities.

Internal submodules for services.google_sync:
- client: Google Sheets client initialization
- parsers: Data parsing utilities
- canonical: Canonical state sync (Sheet -> DB)
- offline: Offline detection and throttling
- initial_import: Initial state import

Public API remains in services.google_sync.
"""

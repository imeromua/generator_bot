#!/usr/bin/env python3
"""Database backup script.

Creates compressed SQL dumps of the database and manages backup retention:
  - Last 7 days: all backups
  - Last 4 weeks: weekly backups
  - Last 12 months: monthly backups

Usage:
    python backup.py [--dir /path/to/backups]

Cron (daily at 03:00):
    0 3 * * * cd /app && python backup.py >> /var/log/backup.log 2>&1
"""

import argparse
import gzip
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_BACKUP_DIR = _PROJECT_ROOT / "backups"


def _backup_postgres(backup_path: Path) -> None:
    """Create a gzip-compressed pg_dump of the PostgreSQL database."""
    dsn = getattr(config, "POSTGRES_DSN", "") or ""
    if not dsn:
        raise RuntimeError("POSTGRES_DSN is not set")

    dump_cmd = ["pg_dump", "--no-password", dsn]
    logger.info(f"Running pg_dump → {backup_path}")

    with gzip.open(backup_path, "wb") as gz_file:
        proc = subprocess.Popen(
            dump_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"pg_dump failed (exit {proc.returncode}): {stderr.decode()}"
            )
        gz_file.write(stdout)


def _backup_sqlite(backup_path: Path) -> None:
    """Create a gzip-compressed copy of the SQLite database file."""
    db_path = (getattr(config, "SQLITE_PATH", "generator.db") or "generator.db").strip()
    src = Path(db_path)
    if not src.exists():
        raise RuntimeError(f"SQLite database not found: {src}")

    logger.info(f"Copying SQLite {src} → {backup_path}")
    with open(src, "rb") as f_in:
        with gzip.open(backup_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)


def create_backup(backup_dir: Path | None = None) -> Path:
    """Create a new database backup.

    Returns the path to the created backup file.
    """
    if backup_dir is None:
        backup_dir = DEFAULT_BACKUP_DIR

    backup_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    filename = f"backup_{now.strftime('%Y-%m-%d_%H-%M')}.sql.gz"
    backup_path = backup_dir / filename

    db_backend = (getattr(config, "DB_BACKEND", "sqlite") or "sqlite").strip().lower()

    if db_backend == "postgres":
        _backup_postgres(backup_path)
    else:
        _backup_sqlite(backup_path)

    size_bytes = backup_path.stat().st_size
    logger.info(f"✅ Backup created: {backup_path} ({size_bytes / 1024:.1f} KB)")
    return backup_path


def apply_retention_policy(backup_dir: Path | None = None) -> list[Path]:
    """Remove backups that fall outside the retention policy.

    Policy:
      - All backups from the last 7 days are kept.
      - For older backups: keep one per week for the last 4 weeks.
      - For even older backups: keep one per month for the last 12 months.
      - Anything older than 12 months is deleted.

    Returns list of deleted paths.
    """
    if backup_dir is None:
        backup_dir = DEFAULT_BACKUP_DIR

    if not backup_dir.exists():
        return []

    now = datetime.now()
    cutoff_daily = now - timedelta(days=7)
    cutoff_weekly = now - timedelta(weeks=4)
    cutoff_monthly = now - timedelta(days=365)

    # Collect all backups with their parsed dates
    backups: list[tuple[datetime, Path]] = []
    for f in backup_dir.glob("backup_*.sql.gz"):
        try:
            # filename: backup_YYYY-MM-DD_HH-MM.sql.gz
            stem = f.stem  # backup_YYYY-MM-DD_HH-MM.sql (before second .gz)
            # actually stem of "backup_2024-01-01_03-00.sql.gz" → "backup_2024-01-01_03-00.sql"
            date_part = f.name[len("backup_"):].replace(".sql.gz", "")
            dt = datetime.strptime(date_part, "%Y-%m-%d_%H-%M")
            backups.append((dt, f))
        except Exception:
            continue

    backups.sort(key=lambda x: x[0])

    # Buckets: daily, weekly, monthly
    kept_weeks: dict[str, Path] = {}   # "YYYY-WW" → file
    kept_months: dict[str, Path] = {}  # "YYYY-MM" → file
    deleted: list[Path] = []

    for dt, path in backups:
        if dt >= cutoff_daily:
            # Within 7 days: keep all
            continue

        if dt >= cutoff_weekly:
            # 7-28 days: keep one per ISO week
            week_key = f"{dt.isocalendar().year}-{dt.isocalendar().week:02d}"
            if week_key not in kept_weeks:
                kept_weeks[week_key] = path
            else:
                # Delete older duplicate in same week
                path.unlink(missing_ok=True)
                deleted.append(path)
            continue

        if dt >= cutoff_monthly:
            # 28 days – 12 months: keep one per month
            month_key = dt.strftime("%Y-%m")
            if month_key not in kept_months:
                kept_months[month_key] = path
            else:
                path.unlink(missing_ok=True)
                deleted.append(path)
            continue

        # Older than 12 months: delete
        path.unlink(missing_ok=True)
        deleted.append(path)

    if deleted:
        logger.info(f"🗑️  Retention policy removed {len(deleted)} old backups")

    return deleted


def list_backups(backup_dir: Path | None = None) -> list[dict]:
    """Return a list of backup info dicts sorted by date descending."""
    if backup_dir is None:
        backup_dir = DEFAULT_BACKUP_DIR

    if not backup_dir.exists():
        return []

    result = []
    for f in backup_dir.glob("backup_*.sql.gz"):
        try:
            date_part = f.name[len("backup_"):].replace(".sql.gz", "")
            dt = datetime.strptime(date_part, "%Y-%m-%d_%H-%M")
        except Exception:
            dt = datetime.fromtimestamp(f.stat().st_mtime)

        size_bytes = f.stat().st_size
        result.append({
            "filename": f.name,
            "timestamp": dt.strftime("%Y-%m-%d %H:%M"),
            "size_bytes": size_bytes,
            "size_kb": round(size_bytes / 1024, 1),
        })

    result.sort(key=lambda x: x["timestamp"], reverse=True)
    return result


def main():
    parser = argparse.ArgumentParser(description="Database backup tool")
    parser.add_argument("--dir", default=None, help="Backup directory (default: ./backups)")
    parser.add_argument("--list", action="store_true", help="List existing backups")
    parser.add_argument("--no-retention", action="store_true", help="Skip retention policy")
    args = parser.parse_args()

    backup_dir = Path(args.dir) if args.dir else None

    if args.list:
        for b in list_backups(backup_dir):
            print(f"{b['timestamp']}  {b['size_kb']:>8.1f} KB  {b['filename']}")
        return

    try:
        path = create_backup(backup_dir)
        print(f"✅ Backup: {path}")
    except Exception as e:
        logger.error(f"❌ Backup failed: {e}")
        sys.exit(1)

    if not args.no_retention:
        apply_retention_policy(backup_dir)


if __name__ == "__main__":
    main()

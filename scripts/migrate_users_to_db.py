"""Migration script: move users from .env USERS variable to the database.

Usage:
    python scripts/migrate_users_to_db.py

Reads the USERS environment variable (comma-separated Telegram user IDs),
creates admin-role users in the database, and prints a summary.

After running this script you can remove the USERS variable from your .env file.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is importable
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv()

import database.models as db_models
import database.db_api as db


def main():
    print("🔧 Ініціалізація бази даних...")
    db_models.init_db()

    users_env = os.getenv("USERS", "").strip()
    if not users_env:
        print("ℹ️  Змінна USERS порожня або відсутня. Немає користувачів для міграції.")
        return

    user_ids = [x.strip() for x in users_env.split(",") if x.strip()]
    if not user_ids:
        print("ℹ️  Не знайдено жодного ID у змінній USERS.")
        return

    print(f"📋 Знайдено {len(user_ids)} користувачів у USERS: {', '.join(user_ids)}")

    migrated = 0
    skipped = 0

    for uid_str in user_ids:
        try:
            user_id = int(uid_str)
        except ValueError:
            print(f"⚠️  Некоректний ID: '{uid_str}', пропускаємо")
            skipped += 1
            continue

        existing = db.get_user(user_id)
        if existing:
            print(f"⏭️  Користувач {user_id} вже існує в БД, пропускаємо")
            skipped += 1
            continue

        db.create_user(
            user_id=user_id,
            username=None,
            first_name=None,
            last_name=None,
            role="admin",
            is_active=True,
            registered_at=datetime.now(),
        )
        print(f"✅ Мігровано користувача {user_id} з роллю 'admin'")
        migrated += 1

    print(f"\n✅ Міграція завершена: {migrated} перенесено, {skipped} пропущено.")
    print("💡 Ви можете видалити змінну USERS з .env файлу.")


if __name__ == "__main__":
    main()

import logging
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)


async def migrate_from_txt(db_path: Path, config_dir: Path) -> None:
    """Migrate data from legacy txt files to SQLite database.

    Reads first_visit_ids.txt and bot_usage.txt, imports into users and usage_log tables.
    Renames source files to .txt.migrated after success.
    Idempotent: skips if .txt files don't exist or .txt.migrated already exists.
    Uses a migrations table to track completion atomically with data inserts.
    """
    first_visit_file = config_dir / "first_visit_ids.txt"
    bot_usage_file = config_dir / "bot_usage.txt"

    migration_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    async with aiosqlite.connect(str(db_path)) as db:
        # Create migrations tracking table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # Check if already completed (handles crash between commit and file rename)
        async with db.execute(
            "SELECT 1 FROM migrations WHERE name = 'txt_to_sqlite'"
        ) as cursor:
            if await cursor.fetchone():
                logger.info("migration_already_applied", extra={"migration": "txt_to_sqlite"})
                # Still rename files if they exist (idempotent cleanup)
                _rename_if_exists(first_visit_file)
                _rename_if_exists(bot_usage_file)
                return

        await _migrate_first_visit(db, first_visit_file, migration_timestamp)
        await _migrate_bot_usage(db, bot_usage_file)
        await db.execute(
            "INSERT INTO migrations (name) VALUES ('txt_to_sqlite')"
        )
        await db.commit()

    # Rename files after successful migration
    _rename_if_exists(first_visit_file)
    _rename_if_exists(bot_usage_file)


async def _migrate_first_visit(
    db: aiosqlite.Connection, file_path: Path, migration_timestamp: str
) -> None:
    """Import user IDs from first_visit_ids.txt into users table."""
    if not _should_migrate(file_path):
        return

    user_ids = _read_int_lines(file_path)
    if not user_ids:
        logger.info("no_users_to_migrate", extra={"file": str(file_path)})
        return

    await db.executemany(
        "INSERT OR IGNORE INTO users (user_id, username, first_seen_at) VALUES (?, NULL, ?)",
        [(uid, migration_timestamp) for uid in user_ids],
    )
    logger.info(
        "users_migrated",
        extra={"count": len(user_ids), "file": str(file_path)},
    )


async def _migrate_bot_usage(db: aiosqlite.Connection, file_path: Path) -> None:
    """Import usage records from bot_usage.txt into usage_log table."""
    if not _should_migrate(file_path):
        return

    user_ids = _read_int_lines(file_path)
    if not user_ids:
        logger.info("no_usage_to_migrate", extra={"file": str(file_path)})
        return

    # Ensure all referenced users exist (they may not be in first_visit_ids.txt)
    await db.executemany(
        "INSERT OR IGNORE INTO users (user_id, username, first_seen_at) VALUES (?, NULL, datetime('now'))",
        [(uid,) for uid in set(user_ids)],
    )
    await db.executemany(
        "INSERT INTO usage_log (user_id, video_id) VALUES (?, NULL)",
        [(uid,) for uid in user_ids],
    )
    logger.info(
        "usage_migrated",
        extra={"count": len(user_ids), "file": str(file_path)},
    )


def _should_migrate(file_path: Path) -> bool:
    """Check if file should be migrated: exists and not already migrated."""
    migrated_path = file_path.parent / (file_path.name + ".migrated")
    if migrated_path.exists():
        logger.info("already_migrated", extra={"file": str(file_path)})
        return False
    if not file_path.exists():
        logger.info("file_not_found", extra={"file": str(file_path)})
        return False
    return True


def _read_int_lines(file_path: Path) -> list[int]:
    """Read a file and return list of integers, one per line."""
    result = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                try:
                    result.append(int(stripped))
                except ValueError:
                    logger.warning(
                        "invalid_line_skipped",
                        extra={"file": str(file_path), "line": stripped},
                    )
    return result


def _rename_if_exists(file_path: Path) -> None:
    """Rename file to .migrated if it exists."""
    if file_path.exists():
        migrated_path = file_path.parent / (file_path.name + ".migrated")
        file_path.rename(migrated_path)
        logger.info("file_renamed", extra={"from": str(file_path), "to": str(migrated_path)})

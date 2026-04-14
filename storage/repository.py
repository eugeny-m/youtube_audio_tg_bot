import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)


class UserRepository:
    """Async SQLite repository with connection-per-call pattern."""

    def __init__(self, db_path: Path):
        self.db_path = str(db_path)

    async def add_user(self, user_id: int, username: str | None = None) -> None:
        """Add a user, or update username if already exists."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO users (user_id, username) VALUES (?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET username = excluded.username
                   WHERE excluded.username IS NOT NULL""",
                (user_id, username),
            )
            await db.commit()

    async def log_usage(self, user_id: int, video_id: str | None = None) -> None:
        """Log a download usage event."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO usage_log (user_id, video_id) VALUES (?, ?)",
                (user_id, video_id),
            )
            await db.commit()

    async def get_users_count(self) -> int:
        """Return total number of users."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                row = await cursor.fetchone()
                return row[0]

    async def get_stats(self) -> dict[str, Any]:
        """Return analytics: total users, active users (with usage), total downloads."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                total_users = (await cursor.fetchone())[0]

            async with db.execute(
                "SELECT COUNT(DISTINCT user_id) FROM usage_log"
            ) as cursor:
                active_users = (await cursor.fetchone())[0]

            async with db.execute("SELECT COUNT(*) FROM usage_log") as cursor:
                total_downloads = (await cursor.fetchone())[0]

            return {
                "total_users": total_users,
                "active_users": active_users,
                "total_downloads": total_downloads,
            }

    async def get_top_users(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return top users by usage count."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT u.user_id, u.username, COUNT(ul.id) as usage_count
                FROM users u
                LEFT JOIN usage_log ul ON u.user_id = ul.user_id
                GROUP BY u.user_id
                ORDER BY usage_count DESC
                LIMIT ?
                """,
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [
                    {
                        "user_id": row["user_id"],
                        "username": row["username"],
                        "usage_count": row["usage_count"],
                    }
                    for row in rows
                ]

    async def get_weekly_stats(self) -> dict[str, Any]:
        """Return usage stats for the last 7 days."""
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM usage_log WHERE created_at >= ?",
                (week_ago,),
            ) as cursor:
                weekly_downloads = (await cursor.fetchone())[0]

            async with db.execute(
                "SELECT COUNT(DISTINCT user_id) FROM usage_log WHERE created_at >= ?",
                (week_ago,),
            ) as cursor:
                weekly_active_users = (await cursor.fetchone())[0]

            async with db.execute(
                """
                SELECT COUNT(DISTINCT user_id) FROM users
                WHERE first_seen_at >= ?
                """,
                (week_ago,),
            ) as cursor:
                new_users = (await cursor.fetchone())[0]

            return {
                "weekly_downloads": weekly_downloads,
                "weekly_active_users": weekly_active_users,
                "new_users": new_users,
            }

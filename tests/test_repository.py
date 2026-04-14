import pytest
import pytest_asyncio
from pathlib import Path

from storage.database import init_db
from storage.repository import UserRepository


@pytest_asyncio.fixture
async def db_path(tmp_path):
    """Create a temporary database and return its path."""
    path = tmp_path / "test.db"
    await init_db(path)
    return path


@pytest_asyncio.fixture
async def repo(db_path):
    """Return a UserRepository connected to the test database."""
    return UserRepository(db_path)


class TestInitDb:
    @pytest.mark.asyncio
    async def test_tables_created(self, db_path):
        """init_db creates users and usage_log tables."""
        import aiosqlite

        async with aiosqlite.connect(str(db_path)) as db:
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ) as cursor:
                tables = [row[0] for row in await cursor.fetchall()]
        assert "usage_log" in tables
        assert "users" in tables

    @pytest.mark.asyncio
    async def test_idempotent(self, db_path):
        """Running init_db twice does not raise errors."""
        await init_db(db_path)  # second call
        import aiosqlite

        async with aiosqlite.connect(str(db_path)) as db:
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ) as cursor:
                tables = [row[0] for row in await cursor.fetchall()]
        assert "users" in tables


class TestAddUser:
    @pytest.mark.asyncio
    async def test_add_user(self, repo):
        await repo.add_user(123, "alice")
        count = await repo.get_users_count()
        assert count == 1

    @pytest.mark.asyncio
    async def test_add_user_without_username(self, repo):
        await repo.add_user(123)
        count = await repo.get_users_count()
        assert count == 1

    @pytest.mark.asyncio
    async def test_duplicate_user_updates_username(self, repo):
        """Adding same user_id twice updates the username."""
        await repo.add_user(123, "alice")
        await repo.add_user(123, "alice_updated")
        count = await repo.get_users_count()
        assert count == 1
        top = await repo.get_top_users(1)
        assert top[0]["username"] == "alice_updated"

    @pytest.mark.asyncio
    async def test_add_user_null_username_does_not_overwrite(self, repo):
        """Adding user with None username does not overwrite existing username."""
        await repo.add_user(123, "alice")
        await repo.add_user(123, None)
        top = await repo.get_top_users(1)
        assert top[0]["username"] == "alice"


class TestLogUsage:
    @pytest.mark.asyncio
    async def test_log_usage(self, repo):
        await repo.add_user(1, "bob")
        await repo.log_usage(1, "vid_abc")
        stats = await repo.get_stats()
        assert stats["total_downloads"] == 1

    @pytest.mark.asyncio
    async def test_log_usage_no_video_id(self, repo):
        await repo.add_user(1, "bob")
        await repo.log_usage(1)
        stats = await repo.get_stats()
        assert stats["total_downloads"] == 1


class TestGetStats:
    @pytest.mark.asyncio
    async def test_empty_db_stats(self, repo):
        """Empty database returns zeroes."""
        stats = await repo.get_stats()
        assert stats["total_users"] == 0
        assert stats["active_users"] == 0
        assert stats["total_downloads"] == 0

    @pytest.mark.asyncio
    async def test_stats_with_data(self, repo):
        await repo.add_user(1, "alice")
        await repo.add_user(2, "bob")
        await repo.log_usage(1, "vid1")
        await repo.log_usage(1, "vid2")
        await repo.log_usage(2, "vid3")
        stats = await repo.get_stats()
        assert stats["total_users"] == 2
        assert stats["active_users"] == 2
        assert stats["total_downloads"] == 3

    @pytest.mark.asyncio
    async def test_stats_inactive_user(self, repo):
        """User with no usage is not counted as active."""
        await repo.add_user(1, "alice")
        await repo.add_user(2, "bob")
        await repo.log_usage(1, "vid1")
        stats = await repo.get_stats()
        assert stats["total_users"] == 2
        assert stats["active_users"] == 1


class TestGetTopUsers:
    @pytest.mark.asyncio
    async def test_top_users_empty(self, repo):
        result = await repo.get_top_users()
        assert result == []

    @pytest.mark.asyncio
    async def test_top_users_ordering(self, repo):
        await repo.add_user(1, "alice")
        await repo.add_user(2, "bob")
        await repo.log_usage(1, "v1")
        await repo.log_usage(2, "v2")
        await repo.log_usage(2, "v3")
        result = await repo.get_top_users(limit=2)
        assert len(result) == 2
        assert result[0]["user_id"] == 2
        assert result[0]["usage_count"] == 2
        assert result[1]["user_id"] == 1
        assert result[1]["usage_count"] == 1

    @pytest.mark.asyncio
    async def test_top_users_limit(self, repo):
        for i in range(5):
            await repo.add_user(i, f"user_{i}")
        result = await repo.get_top_users(limit=3)
        assert len(result) == 3


class TestGetWeeklyStats:
    @pytest.mark.asyncio
    async def test_weekly_stats_empty(self, repo):
        stats = await repo.get_weekly_stats()
        assert stats["weekly_downloads"] == 0
        assert stats["weekly_active_users"] == 0
        assert stats["new_users"] == 0

    @pytest.mark.asyncio
    async def test_weekly_stats_with_recent_data(self, repo):
        await repo.add_user(1, "alice")
        await repo.log_usage(1, "vid1")
        await repo.log_usage(1, "vid2")
        stats = await repo.get_weekly_stats()
        assert stats["weekly_downloads"] == 2
        assert stats["weekly_active_users"] == 1
        assert stats["new_users"] == 1

    @pytest.mark.asyncio
    async def test_weekly_stats_excludes_old_data(self, repo):
        """Data older than 7 days should not be included."""
        import aiosqlite

        await repo.add_user(1, "alice")
        # Insert old usage record directly
        async with aiosqlite.connect(repo.db_path) as db:
            await db.execute(
                "INSERT INTO usage_log (user_id, video_id, created_at) VALUES (?, ?, datetime('now', '-10 days'))",
                (1, "old_vid"),
            )
            # Insert old user directly
            await db.execute(
                "UPDATE users SET first_seen_at = datetime('now', '-10 days') WHERE user_id = ?",
                (1,),
            )
            await db.commit()

        stats = await repo.get_weekly_stats()
        assert stats["weekly_downloads"] == 0
        assert stats["weekly_active_users"] == 0
        assert stats["new_users"] == 0

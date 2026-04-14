import pytest
import pytest_asyncio
from pathlib import Path

import aiosqlite

from storage.database import init_db
from storage.migration import migrate_from_txt


@pytest_asyncio.fixture
async def db_path(tmp_path):
    """Create a temporary database and return its path."""
    path = tmp_path / "test.db"
    await init_db(path)
    return path


@pytest.fixture
def config_dir(tmp_path):
    """Return a temporary config directory."""
    d = tmp_path / "config"
    d.mkdir()
    return d


def write_txt(path: Path, lines: list[str]):
    """Helper to write lines to a txt file."""
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestMigrateFromTxt:
    @pytest.mark.asyncio
    async def test_migrate_users(self, db_path, config_dir):
        """Users from first_visit_ids.txt are inserted into users table."""
        write_txt(config_dir / "first_visit_ids.txt", ["111", "222", "333"])

        await migrate_from_txt(db_path, config_dir)

        async with aiosqlite.connect(str(db_path)) as db:
            async with db.execute("SELECT user_id FROM users ORDER BY user_id") as cur:
                rows = await cur.fetchall()
        assert [r[0] for r in rows] == [111, 222, 333]

    @pytest.mark.asyncio
    async def test_migrate_users_have_null_username(self, db_path, config_dir):
        """Migrated users have username=NULL."""
        write_txt(config_dir / "first_visit_ids.txt", ["111"])

        await migrate_from_txt(db_path, config_dir)

        async with aiosqlite.connect(str(db_path)) as db:
            async with db.execute("SELECT username FROM users WHERE user_id = 111") as cur:
                row = await cur.fetchone()
        assert row[0] is None

    @pytest.mark.asyncio
    async def test_migrate_users_have_migration_timestamp(self, db_path, config_dir):
        """Migrated users have first_seen_at set to migration timestamp."""
        write_txt(config_dir / "first_visit_ids.txt", ["111"])

        await migrate_from_txt(db_path, config_dir)

        async with aiosqlite.connect(str(db_path)) as db:
            async with db.execute("SELECT first_seen_at FROM users WHERE user_id = 111") as cur:
                row = await cur.fetchone()
        assert row[0] is not None
        # Should be a valid datetime string
        assert len(row[0]) == 19  # "YYYY-MM-DD HH:MM:SS"

    @pytest.mark.asyncio
    async def test_migrate_usage(self, db_path, config_dir):
        """Usage records from bot_usage.txt are inserted into usage_log table."""
        write_txt(config_dir / "bot_usage.txt", ["111", "222", "111"])

        await migrate_from_txt(db_path, config_dir)

        async with aiosqlite.connect(str(db_path)) as db:
            async with db.execute("SELECT COUNT(*) FROM usage_log") as cur:
                count = (await cur.fetchone())[0]
            async with db.execute("SELECT user_id, video_id FROM usage_log ORDER BY id") as cur:
                rows = await cur.fetchall()
        assert count == 3
        assert rows[0][0] == 111
        assert rows[0][1] is None  # video_id is NULL for migrated data
        assert rows[2][0] == 111

    @pytest.mark.asyncio
    async def test_files_renamed_after_migration(self, db_path, config_dir):
        """Source files are renamed to .txt.migrated after success."""
        first_visit = config_dir / "first_visit_ids.txt"
        bot_usage = config_dir / "bot_usage.txt"
        write_txt(first_visit, ["111"])
        write_txt(bot_usage, ["111"])

        await migrate_from_txt(db_path, config_dir)

        assert not first_visit.exists()
        assert not bot_usage.exists()
        assert (config_dir / "first_visit_ids.txt.migrated").exists()
        assert (config_dir / "bot_usage.txt.migrated").exists()

    @pytest.mark.asyncio
    async def test_both_files_migrated_together(self, db_path, config_dir):
        """Both users and usage are migrated in a single call."""
        write_txt(config_dir / "first_visit_ids.txt", ["111", "222"])
        write_txt(config_dir / "bot_usage.txt", ["111", "222", "111"])

        await migrate_from_txt(db_path, config_dir)

        async with aiosqlite.connect(str(db_path)) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cur:
                users_count = (await cur.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM usage_log") as cur:
                usage_count = (await cur.fetchone())[0]
        assert users_count == 2
        assert usage_count == 3


class TestIdempotentRerun:
    @pytest.mark.asyncio
    async def test_no_errors_on_rerun(self, db_path, config_dir):
        """Running migration twice does not raise errors."""
        write_txt(config_dir / "first_visit_ids.txt", ["111"])
        write_txt(config_dir / "bot_usage.txt", ["111"])

        await migrate_from_txt(db_path, config_dir)
        # Second run: .txt files are gone, .migrated exists
        await migrate_from_txt(db_path, config_dir)

    @pytest.mark.asyncio
    async def test_no_duplicates_on_rerun(self, db_path, config_dir):
        """Second migration does not duplicate data."""
        write_txt(config_dir / "first_visit_ids.txt", ["111", "222"])
        write_txt(config_dir / "bot_usage.txt", ["111"])

        await migrate_from_txt(db_path, config_dir)
        await migrate_from_txt(db_path, config_dir)

        async with aiosqlite.connect(str(db_path)) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cur:
                users_count = (await cur.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM usage_log") as cur:
                usage_count = (await cur.fetchone())[0]
        assert users_count == 2
        assert usage_count == 1

    @pytest.mark.asyncio
    async def test_migrated_file_prevents_rerun(self, db_path, config_dir):
        """If .txt.migrated exists, migration is skipped even if .txt also exists."""
        write_txt(config_dir / "first_visit_ids.txt", ["111"])
        (config_dir / "first_visit_ids.txt.migrated").touch()

        await migrate_from_txt(db_path, config_dir)

        async with aiosqlite.connect(str(db_path)) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cur:
                count = (await cur.fetchone())[0]
        assert count == 0


class TestMissingFiles:
    @pytest.mark.asyncio
    async def test_no_files_no_error(self, db_path, config_dir):
        """Migration with no txt files completes without error."""
        await migrate_from_txt(db_path, config_dir)

    @pytest.mark.asyncio
    async def test_only_first_visit_exists(self, db_path, config_dir):
        """Migration works with only first_visit_ids.txt present."""
        write_txt(config_dir / "first_visit_ids.txt", ["111", "222"])

        await migrate_from_txt(db_path, config_dir)

        async with aiosqlite.connect(str(db_path)) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cur:
                users_count = (await cur.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM usage_log") as cur:
                usage_count = (await cur.fetchone())[0]
        assert users_count == 2
        assert usage_count == 0

    @pytest.mark.asyncio
    async def test_only_bot_usage_exists(self, db_path, config_dir):
        """Migration works with only bot_usage.txt present."""
        write_txt(config_dir / "bot_usage.txt", ["111"])

        await migrate_from_txt(db_path, config_dir)

        async with aiosqlite.connect(str(db_path)) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cur:
                users_count = (await cur.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM usage_log") as cur:
                usage_count = (await cur.fetchone())[0]
        assert users_count == 0
        assert usage_count == 1

    @pytest.mark.asyncio
    async def test_empty_files_handled(self, db_path, config_dir):
        """Empty txt files are handled gracefully."""
        (config_dir / "first_visit_ids.txt").touch()
        (config_dir / "bot_usage.txt").touch()

        await migrate_from_txt(db_path, config_dir)

        async with aiosqlite.connect(str(db_path)) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cur:
                assert (await cur.fetchone())[0] == 0

    @pytest.mark.asyncio
    async def test_invalid_lines_skipped(self, db_path, config_dir):
        """Non-integer lines are skipped without error."""
        write_txt(config_dir / "first_visit_ids.txt", ["111", "not_a_number", "222", ""])

        await migrate_from_txt(db_path, config_dir)

        async with aiosqlite.connect(str(db_path)) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cur:
                assert (await cur.fetchone())[0] == 2

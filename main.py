import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers import download, start
from bot.handlers.admin import create_admin_router
from bot.middlewares.fsm_timeout import FSMTimeoutMiddleware
from bot.middlewares.logging import LoggingMiddleware
from core.config import Settings
from core.logging import setup_logging
from storage.database import init_db
from storage.migration import migrate_from_txt
from storage.repository import UserRepository

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = Settings()
    setup_logging(settings)

    logger.info("starting_bot", extra={"debug": settings.debug})

    await init_db(settings.db_path)

    config_dir = settings.db_path.parent
    await migrate_from_txt(settings.db_path, config_dir)

    bot_kwargs = {}
    if settings.bot_proxy:
        from aiogram.client.session.aiohttp import AiohttpSession

        session = AiohttpSession(proxy=settings.bot_proxy)
        bot_kwargs["session"] = session

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
        **bot_kwargs,
    )

    dp = Dispatcher(storage=MemoryStorage())

    repo = UserRepository(settings.db_path)
    dp["repo"] = repo
    dp["settings"] = settings

    dp.message.middleware(LoggingMiddleware())
    dp.callback_query.middleware(LoggingMiddleware())
    dp.message.middleware(FSMTimeoutMiddleware(timeout_minutes=10))
    dp.callback_query.middleware(FSMTimeoutMiddleware(timeout_minutes=10))

    dp.include_router(start.router)
    dp.include_router(create_admin_router(settings))
    dp.include_router(download.router)

    logger.info("bot_started", extra={"username": settings.bot_username})

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

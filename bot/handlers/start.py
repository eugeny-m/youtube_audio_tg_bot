import logging

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from storage.repository import UserRepository

logger = logging.getLogger(__name__)

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, repo: UserRepository) -> None:
    """Handle /start command: register user and send welcome."""
    user = message.from_user
    if user is None:
        return

    await repo.add_user(user.id, user.username)
    logger.info("user_started", extra={"user_id": user.id, "username": user.username})

    await message.answer(
        "Welcome! Send me a YouTube link and I'll extract the audio for you."
    )

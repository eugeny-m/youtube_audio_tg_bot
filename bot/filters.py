from aiogram.filters import BaseFilter
from aiogram.types import Message

from core.config import Settings


class AdminFilter(BaseFilter):
    """Filter that passes only for the configured superuser."""

    def __init__(self, settings: Settings) -> None:
        self.superuser_id = settings.tg_superuser

    async def __call__(self, message: Message) -> bool:
        return message.from_user is not None and message.from_user.id == self.superuser_id

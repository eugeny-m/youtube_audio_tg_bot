from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from core.config import Settings


class AdminFilter(BaseFilter):
    """Filter that passes only for the configured superuser."""

    def __init__(self, settings: Settings) -> None:
        self.superuser_id = settings.tg_superuser

    async def __call__(self, event: TelegramObject) -> bool:
        from_user = getattr(event, "from_user", None)
        return from_user is not None and from_user.id == self.superuser_id

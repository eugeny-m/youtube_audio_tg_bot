import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update


logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseMiddleware):
    """Adds user_id and chat_id to log context for every update."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        extra: Dict[str, Any] = {}

        if isinstance(event, Update):
            update_event = (
                event.message
                or event.callback_query
                or event.edited_message
                or event.inline_query
            )
            if update_event and hasattr(update_event, "from_user") and update_event.from_user:
                extra["user_id"] = update_event.from_user.id
            if hasattr(update_event, "chat") and update_event and update_event.chat:
                extra["chat_id"] = update_event.chat.id

        if extra:
            logger.info("update_received", extra=extra)

        return await handler(event, data)

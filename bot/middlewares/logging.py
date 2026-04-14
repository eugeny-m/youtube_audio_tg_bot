import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


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

        if isinstance(event, Message):
            if event.from_user:
                extra["user_id"] = event.from_user.id
            if event.chat:
                extra["chat_id"] = event.chat.id
        elif isinstance(event, CallbackQuery):
            if event.from_user:
                extra["user_id"] = event.from_user.id
            if event.message and event.message.chat:
                extra["chat_id"] = event.message.chat.id

        if extra:
            logger.info("update_received", extra=extra)

        return await handler(event, data)

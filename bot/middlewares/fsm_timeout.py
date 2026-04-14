import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject


logger = logging.getLogger(__name__)


class FSMTimeoutMiddleware(BaseMiddleware):
    """Lazy FSM state cleanup: clears state if older than timeout_minutes.

    Only checks on the user's next interaction, not proactively.
    """

    def __init__(self, timeout_minutes: int = 10) -> None:
        self.timeout_seconds = timeout_minutes * 60

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        state: FSMContext | None = data.get("state")

        if state is not None:
            current_state = await state.get_state()
            if current_state is not None:
                state_data = await state.get_data()
                created_at = state_data.get("created_at")

                if created_at is not None:
                    now = datetime.now(timezone.utc).timestamp()
                    if now - created_at > self.timeout_seconds:
                        logger.info(
                            "fsm_state_expired",
                            extra={
                                "state": current_state,
                                "age_seconds": now - created_at,
                            },
                        )
                        await state.clear()
                        # Skip the handler — state filters already matched
                        # the now-cleared state, so the handler would fail.
                        if isinstance(event, CallbackQuery):
                            await event.answer()
                            if event.message and isinstance(event.message, Message):
                                await event.message.edit_text(
                                    "Session expired. Please send the link again."
                                )
                        elif hasattr(event, "answer"):
                            await event.answer("Session expired. Please send the link again.")
                        return None

        return await handler(event, data)

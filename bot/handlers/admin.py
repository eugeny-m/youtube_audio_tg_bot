import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.filters import AdminFilter
from core.config import Settings
from storage.repository import UserRepository

logger = logging.getLogger(__name__)


async def cmd_admin(message: Message) -> None:
    """Show admin panel with inline keyboard."""
    kb = InlineKeyboardBuilder()
    kb.button(text="Overall Stats", callback_data="admin:stats")
    kb.button(text="Top 20 Users", callback_data="admin:top_users")
    kb.button(text="Weekly Stats", callback_data="admin:weekly")
    kb.adjust(1)

    await message.answer("Admin Panel", reply_markup=kb.as_markup())


async def on_stats(callback: CallbackQuery, repo: UserRepository) -> None:
    """Show overall stats."""
    stats = await repo.get_stats()
    text = (
        "Overall Stats\n"
        f"Total users: {stats['total_users']}\n"
        f"Active users: {stats['active_users']}\n"
        f"Total downloads: {stats['total_downloads']}"
    )
    await callback.message.edit_text(text)
    await callback.answer()


async def on_top_users(callback: CallbackQuery, repo: UserRepository) -> None:
    """Show top 20 users by usage."""
    users = await repo.get_top_users(limit=20)
    if not users:
        await callback.message.edit_text("No users yet.")
        await callback.answer()
        return

    lines = ["Top Users"]
    for i, u in enumerate(users, 1):
        name = u["username"] or str(u["user_id"])
        lines.append(f"{i}. {name} - {u['usage_count']} downloads")

    await callback.message.edit_text("\n".join(lines))
    await callback.answer()


async def on_weekly(callback: CallbackQuery, repo: UserRepository) -> None:
    """Show weekly stats."""
    stats = await repo.get_weekly_stats()
    text = (
        "Weekly Stats (last 7 days)\n"
        f"Downloads: {stats['weekly_downloads']}\n"
        f"Active users: {stats['weekly_active_users']}\n"
        f"New users: {stats['new_users']}"
    )
    await callback.message.edit_text(text)
    await callback.answer()


def create_admin_router(settings: Settings) -> Router:
    """Create admin router with AdminFilter bound to settings."""
    router = Router(name="admin")
    admin_filter = AdminFilter(settings)
    router.message.filter(admin_filter)
    router.callback_query.filter(admin_filter)

    router.message.register(cmd_admin, Command("admin"))
    router.callback_query.register(on_stats, F.data == "admin:stats")
    router.callback_query.register(on_top_users, F.data == "admin:top_users")
    router.callback_query.register(on_weekly, F.data == "admin:weekly")

    return router

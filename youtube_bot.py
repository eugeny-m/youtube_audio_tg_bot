import asyncio
import os

import pytubefix
import pytubefix.extract
from pytubefix.cli import on_progress
from slugify import slugify

from aiogram.client.default import DefaultBotProperties

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    FSInputFile
)

from log import get_logger


def get_bot() -> Bot:
    return Bot(
        token=os.environ.get("TELEGRAM_BOT_TOKEN"),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


class YoutubeService:
    @staticmethod
    def validate_video_url(url_: str) -> bool:
        # Check if message contains a valid YouTube link
        try:
            pytubefix.extract.video_id(url_)
        except Exception:
            return False
        return True
    
    @staticmethod
    def download_audio(url_: str) -> str:
        logger.info("Trying to download the audio file.")
        try:
            yt = pytubefix.YouTube(url_, on_progress_callback=on_progress)
            audio_stream = yt.streams.get_audio_only()
            audio_filename = audio_stream.default_filename[:-4]
            # slugify name
            audio_filename = f'{slugify(audio_filename, max_length=46)}.mp3'
            audio_stream.download(output_path=".", filename=audio_filename)
        except Exception as e:
            logger.exception(e)
            raise e
        return audio_filename


logger = get_logger()
bot = get_bot()
dp = Dispatcher()


@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    logger.info(
        f'Start command called: '
        f'tg_id: {message.from_user.id}, '
        f'chat_id: {message.chat.id} '
        f'username: {message.from_user.full_name}'
    )
    await message.answer(
        'Hi! Send me a YouTube video link and I will send you the audio file.'
    )


@dp.message()
async def echo_handler(message: Message) -> None:
    """
    Handler will forward receive a message back to the sender
    By default, message handler will handle all message types (like a text, photo, sticker etc.)

    IMPORTANT! Place any commands handlers above this handler.!!!
    Any command handlers below this handler will be processed by this one.
    """
    if not message.text:
        logger.error(message)
        raise ValueError(f'Unhandled message type with empty text!')
    
    if message.text.startswith('/'):
        await message.answer('No such command!')
        return
    
    valid_url = YoutubeService.validate_video_url(message.text)
    if not valid_url:
        await message.reply('Please send me a valid YouTube video link.')
        return
    
    await message.answer('Trying to download the audio file.')
    try:
        audio_filename = YoutubeService.download_audio(message.text)
    except:
        await message.answer(
            "An error occurred while downloading the audio file."
        )
        return
    
    logger.info("Download completed, Sending the audio file.")
    await message.reply(
        f"Download completed, Sending the audio file. {audio_filename}",
    )
    try:
        await message.reply_audio(FSInputFile(audio_filename))
    except Exception as e:
        logger.exception(e)
        await message.reply("An error occurred while sending the audio file.")
    finally:
        # Delete audio file from server
        os.remove(audio_filename)
        logger.info(f"File {audio_filename} deleted.")


async def _main() -> None:
    logger.info(f'Start polling bot')
    await dp.start_polling(bot)


async def main() -> None:
    task = asyncio.create_task(_main())
    try:
        await task
    except Exception as e:
        logger.exception(e)
    finally:
        await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())

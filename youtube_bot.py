import asyncio
import os
import shutil

import pytubefix
import pytubefix.extract

from pathlib import Path

from pydub import AudioSegment
from pytubefix import Stream
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


logger = get_logger()
bot = get_bot()
dp = Dispatcher()
TEMP_DOWNLOAD_DIR = Path('temp_download').resolve()


def split_audio_by_size(input_path: Path, max_size_mb: float) -> [Path]:
    logger.info(f'Start splitting audio file {input_path} to chunks {max_size_mb}Mb')
    temp_dir = input_path.parent
    name_no_extension = input_path.stem
    extension = Path(input_path).suffix
    
    audio = AudioSegment.from_file(input_path)
    max_size_bytes = max_size_mb * 1024 * 1024
    
    chunk_duration = 1000 * 10  # Start chunk time duration, 10 seconds
    chunks = []
    
    start = 0
    current_chunk = audio[:chunk_duration]
    for end in range(0, len(audio), chunk_duration):
        if len(current_chunk.raw_data) >= max_size_bytes * 10:
            chunks.append(current_chunk)
            start = end
        
        current_chunk = audio[start:end]
    
    if len(current_chunk) > 0:
        chunks.append(current_chunk)
    
    output_files = []
    for idx, chunk in enumerate(chunks, start=1):
        output_filename = f"{name_no_extension}_{idx}{extension}"
        output_filepath = temp_dir / output_filename
        chunk.export(output_filepath, format="mp3")
        logger.info(f"File saved: {output_filename} (size: {os.path.getsize(output_filepath) / (1024 * 1024):.2f} MB)")
        output_files.append(output_filepath)
        if os.path.getsize(output_filepath) > max_size_bytes:
            raise ValueError(
                f'Generated chunk with size {os.path.getsize(output_filepath)}b > '
                f'{max_size_bytes}b'
            )
    logger.info('Splitting completed')
    return output_files


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
    def get_audio_stream(url_: str, max_size_mb: float) -> tuple[Stream, float]:
        logger.info(f'Choosing audio stream for video {url_}')
        yt = pytubefix.YouTube(url_, on_progress_callback=on_progress)
        streams = yt.streams.filter(only_audio=True, subtype='mp4').order_by("abr")
        if not streams:
            raise ValueError(f'No audio streams for this url!')

        for s in streams:
            audio_stream = s
            if s.filesize_mb < max_size_mb:
                break

        logger.info(
            f'File to download have been chosen. '
            f'Name {audio_stream.default_filename}, '
            f'bitrate: {audio_stream.abr}, '
            f'size: {audio_stream.filesize_mb}MB'
        )
        return audio_stream, audio_stream.filesize_mb

    @staticmethod
    def prepare_temp_dir(audio_filename: str) -> Path:
        """
        Create temp directory for audio file
        :param audio_filename: name of the audio file
        :return: path to the temp directory
        """
        if not TEMP_DOWNLOAD_DIR.exists():
            os.makedirs(TEMP_DOWNLOAD_DIR)

        name_no_extension = Path(audio_filename).stem

        # create temp_dir
        temp_dir = TEMP_DOWNLOAD_DIR / name_no_extension

        if temp_dir.exists():
            logger.info(f'Temp dir {temp_dir} already exists.')

        if not temp_dir.exists():
            os.makedirs(temp_dir)
        return temp_dir

    @classmethod
    def download_audio(cls, url_: str, max_size_mb: float) -> tuple[Path, Path, float]:
        logger.info("Trying to download the audio file.")
        try:
            audio_stream, filesize_mb = cls.get_audio_stream(url_, max_size_mb)
            audio_filename = slugify(audio_stream.default_filename, max_length=46, separator='_')
            temp_dir = cls.prepare_temp_dir(audio_filename)
            audio_stream.download(output_path=str(temp_dir), filename=audio_filename)
        except Exception as e:
            logger.exception(e)
            raise e
        logger.info("Download completed, Sending the audio file.")
        return temp_dir / audio_filename, temp_dir, filesize_mb

    @staticmethod
    def prepare_files_to_send(temp_file: Path, filesize_mb: float, max_size_mb: float) -> [Path]:
        if filesize_mb <= max_size_mb:
            return [temp_file]
        return split_audio_by_size(temp_file, max_size_mb)

    @staticmethod
    def clear_temp_dir(temp_dir: Path):
        # remove directory recursive
        shutil.rmtree(temp_dir)


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

    # PROCESSING YOUTUBE VIDEO LINK
    max_audio_file_size_mb = 49.5
    valid_url = YoutubeService.validate_video_url(message.text)
    if not valid_url:
        await message.reply('Please send me a valid YouTube video link.')
        return
    
    await message.answer('Trying to download the audio file.')
    try:
        temp_file, temp_dir, filesize_mb = YoutubeService.download_audio(message.text, max_audio_file_size_mb)
    except:
        await message.answer("An error occurred while downloading the audio file.")
        return
    
    try:
        files_to_send = YoutubeService.prepare_files_to_send(
            temp_file=temp_file,
            filesize_mb=filesize_mb,
            max_size_mb=max_audio_file_size_mb,
        )
    except Exception as e:
        logger.exception(e)
        await message.reply("An error occurred while preparing the audio file.")
        return

    for audio_chunk in files_to_send:
        try:
            await message.reply_audio(FSInputFile(audio_chunk))
        except Exception as e:
            logger.exception(e)
            await message.reply(f'An error occurred while sending file. {audio_chunk.name}')
            YoutubeService.clear_temp_dir(temp_dir)
            break


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

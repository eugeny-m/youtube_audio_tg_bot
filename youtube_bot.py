import asyncio
import math
import os
import shutil
import subprocess

import pytubefix
import pytubefix.extract

from pathlib import Path

from pytubefix import Stream
from pytubefix.cli import on_progress
from slugify import slugify

from aiogram.client.default import DefaultBotProperties
from aiogram import Bot, Dispatcher, html
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    FSInputFile
)

from log import get_logger
from visit_counter import BotUsageLogger, get_visit_storage


BOT_PROXY = os.environ.get("BOT_PROXY", None)
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")


def get_bot() -> Bot:
    bot_params = dict(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    if BOT_PROXY:
        from aiogram.client.session.aiohttp import AiohttpSession
        bot_params['session'] = AiohttpSession(proxy=BOT_PROXY)
    return Bot(**bot_params)


logger = get_logger()
bot = get_bot()
dp = Dispatcher()
TG_SUPERUSER = os.environ.get('TG_SUPERUSER')
BOT_USERNAME = 'get_me_youtube_audio_bot'
TEMP_DOWNLOAD_DIR = Path('temp_download').resolve()
usage_logger = BotUsageLogger()


class AdminCommandConst:
    USERS_STATS = 'users_stats'


def split_audio_ffmpeg(input_path: Path, max_size_mb: float):
    logger.info(f'Start splitting audio file {input_path} to chunks {max_size_mb}Mb')
    temp_dir = input_path.parent
    
    suffix = input_path.suffix
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries',
         'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
         input_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    duration = float(result.stdout.strip())
    logger.info(f"Duration: {duration:.2f} sec")
    
    file_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    logger.info(f"File size: {file_size_mb:.2f} MB")
    
    seconds_per_chunk = duration * (max_size_mb / file_size_mb)
    logger.info(f"Approx seconds per chunk: {seconds_per_chunk:.2f}")
    
    num_chunks = math.ceil(duration / seconds_per_chunk)
    logger.info(f"Splitting into {num_chunks} chunks")
    
    output_files = []
    
    for i in range(num_chunks):
        start_time = i * seconds_per_chunk
        output_path = temp_dir / f"{input_path.stem}_{i:02}{suffix}"
        
        cmd = [
            'ffmpeg', '-v', 'error',
            '-ss', str(start_time),
            '-t', str(seconds_per_chunk),
            '-i', input_path,
            '-acodec', 'copy',
            output_path
        ]
        logger.info(f"Creating chunk {i + 1}/{num_chunks}: {output_path}")
        
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True
            )
        except subprocess.CalledProcessError as e:
            logger.exception(e)
            logger.error(f"❌ Error creating chunk {i + 1}")
            logger.error("STDERR:\n", e.stderr)
            raise e
        
        output_files.append(output_path)
    
    logger.info(f"Finish splitting {input_path.name}.")
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
        streams = yt.streams.filter(only_audio=True, subtype='mp4').order_by("abr").desc()
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

            suffix = Path(audio_stream.default_filename).suffix
            audio_filename = slugify(audio_stream.default_filename, max_length=25, separator='_')
            audio_filename = f'{audio_filename}{suffix}'
            temp_dir = cls.prepare_temp_dir(audio_filename)

            audio_stream.download(output_path=str(temp_dir), filename=audio_filename)
        except Exception as e:
            logger.exception(e)
            raise e
        temp_file_path = temp_dir / audio_filename
        logger.info(f"Download completed. {temp_file_path}")
        return temp_file_path, temp_dir, filesize_mb

    @staticmethod
    def prepare_files_to_send(temp_file: Path, filesize_mb: float, max_size_mb: float) -> [Path]:
        if filesize_mb <= max_size_mb:
            return [temp_file]
        return split_audio_ffmpeg(temp_file, max_size_mb)

    @staticmethod
    def clear_temp_dir(temp_dir: Path):
        # remove directory recursive
        logger.info(f'Removing temp dir {temp_dir}')
        shutil.rmtree(temp_dir)


@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    logger.info(
        f'Start command called: '
        f'tg_id: {message.from_user.id}, '
        f'chat_id: {message.chat.id} '
        f'username: {message.from_user.full_name}'
    )
    visit_storage = get_visit_storage()
    visit_storage.add_id(message.from_user.id)
    await message.answer(
        'Привет!\nПришли мне ссылку на ютуб видео, а в ответ я пришлю '
        'аудиофайл этого видео для прослушивания.'
    )


@dp.message(Command(AdminCommandConst.USERS_STATS))
async def command_user_count(message: Message) -> None:
    if message.from_user.id != int(TG_SUPERUSER):
        await message.answer('Команда не существует')
        return

    visit_storage = get_visit_storage()
    analytics = usage_logger.get_stats(visit_storage.unique_ids)
    formatted = usage_logger.get_analytics_formatted_string(analytics)
    await message.answer(f'{html.pre(formatted)}')


@dp.message()
async def echo_handler(message: Message) -> None:
    """
    Handler will forward receive a message back to the sender
    By default, message handler will handle all message types (like a text, photo, sticker etc.)

    IMPORTANT! Place any commands handlers above this handler.!!!
    Any command handlers below this handler will be processed by this one.
    """
    logger.info(f'Received message from [{message.from_user.id}]: [{message.text}]')
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
        await message.reply('Пришли пожалуйста валидную ссылку на ютуб видео.')
        return

    logger.info(
        f'Received message from [{message.from_user.id}]: [{message.text}] '
        f'recognized as valid youtube video link. Processing..'
    )

    # store user id usage for analytics
    usage_logger.append(message.from_user.id)

    resp = await message.answer('Скачиваю файл..')

    try:
        temp_file, temp_dir, filesize_mb = YoutubeService.download_audio(message.text, max_audio_file_size_mb)
    except:
        await message.answer("Произошла ошибка при скачивании файла =(")
        return

    await resp.edit_text('Файл скачан, начинаю обработку..')
    try:
        files_to_send = YoutubeService.prepare_files_to_send(
            temp_file=temp_file,
            filesize_mb=filesize_mb,
            max_size_mb=max_audio_file_size_mb,
        )
    except Exception as e:
        logger.exception(e)
        await message.answer(
            "Произошла ошибка при подготовке аудиофайла =(\n"
            "Свяжитесь с администратором"
        )
        return

    success = True
    for ind, audio_chunk in enumerate(files_to_send, start=1):
        await resp.edit_text(f'Аудиофайл обработан, начинаю отправку {ind} файла из {len(files_to_send)}..')
        
        try:
            logger.info(f'Sending audio chunk {ind} of {len(files_to_send)}, {audio_chunk.name}')
            await message.answer_audio(FSInputFile(audio_chunk))
        except Exception as e:
            logger.exception(e)
            success = False
            break

    if success:
        await message.reply('Все файлы успешно отправлены!')
    else:
        await message.reply('Некоторые файлы не удалось отправить =(')

    YoutubeService.clear_temp_dir(temp_dir)
    logger.info(f'Finish processing message from [{message.from_user.id}]')


async def _main() -> None:
    logger.info(f'Start polling bot')
    await dp.start_polling(bot, polling_timeout=40)


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

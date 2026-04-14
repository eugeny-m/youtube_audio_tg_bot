import asyncio
import logging
import math
import os
import subprocess
from pathlib import Path


logger = logging.getLogger(__name__)


def split_audio_ffmpeg(input_path: Path, max_size_mb: float) -> list[Path]:
    """Split an audio file into chunks of approximately max_size_mb each.

    Uses ffmpeg to split without re-encoding (codec copy).
    Returns list of chunk file paths.
    """
    logger.info("split_started", extra={
        "input_path": str(input_path),
        "max_size_mb": max_size_mb,
    })

    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries',
         'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
         str(input_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    duration = float(result.stdout.strip())

    file_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    seconds_per_chunk = duration * (max_size_mb / file_size_mb)
    num_chunks = math.ceil(duration / seconds_per_chunk)

    logger.info("split_plan", extra={
        "duration": duration,
        "file_size_mb": file_size_mb,
        "seconds_per_chunk": seconds_per_chunk,
        "num_chunks": num_chunks,
    })

    temp_dir = input_path.parent
    suffix = input_path.suffix
    output_files = []

    for i in range(num_chunks):
        start_time = i * seconds_per_chunk
        output_path = temp_dir / f"{input_path.stem}_{i:02}{suffix}"

        cmd = [
            'ffmpeg', '-v', 'error',
            '-ss', str(start_time),
            '-t', str(seconds_per_chunk),
            '-i', str(input_path),
            '-acodec', 'copy',
            str(output_path),
        ]

        logger.info("split_chunk", extra={
            "chunk": i + 1,
            "total": num_chunks,
            "output_path": str(output_path),
        })

        try:
            subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            logger.error("split_chunk_failed", extra={
                "chunk": i + 1,
                "stderr": e.stderr,
            })
            raise

        output_files.append(output_path)

    logger.info("split_completed", extra={
        "input_path": str(input_path),
        "chunks": len(output_files),
    })
    return output_files


def prepare_files_to_send(temp_file: Path, filesize_mb: float, max_size_mb: float) -> list[Path]:
    """Prepare audio files for sending. Splits if over size limit.

    Returns list of file paths to send.
    """
    if filesize_mb <= max_size_mb:
        return [temp_file]
    return split_audio_ffmpeg(temp_file, max_size_mb)


async def async_split_audio_ffmpeg(input_path: Path, max_size_mb: float) -> list[Path]:
    """Async wrapper for split_audio_ffmpeg using asyncio.to_thread()."""
    return await asyncio.to_thread(split_audio_ffmpeg, input_path, max_size_mb)


async def async_prepare_files_to_send(temp_file: Path, filesize_mb: float, max_size_mb: float) -> list[Path]:
    """Async wrapper for prepare_files_to_send using asyncio.to_thread()."""
    return await asyncio.to_thread(prepare_files_to_send, temp_file, filesize_mb, max_size_mb)

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytubefix
import pytubefix.extract
from pytubefix.cli import on_progress
from slugify import slugify


logger = logging.getLogger(__name__)


@dataclass
class StreamInfo:
    itag: int
    language: Optional[str]
    abr: str
    size_mb: float


class YoutubeService:
    @staticmethod
    def validate_url(url: str) -> Optional[str]:
        """Validate YouTube URL and return video_id or None."""
        try:
            video_id = pytubefix.extract.video_id(url)
            return video_id
        except Exception:
            return None

    @staticmethod
    def get_available_streams(url: str) -> tuple[str, float, list[StreamInfo]]:
        """Get available audio streams for a video.

        Returns (title, duration_sec, list of StreamInfo).
        """
        logger.info("getting_available_streams", extra={"url": url})
        yt = pytubefix.YouTube(url, on_progress_callback=on_progress)
        streams = yt.streams.filter(only_audio=True, subtype='mp4').order_by("abr").desc()
        if not streams:
            raise ValueError("No audio streams available for this URL")

        title = yt.title
        duration_sec = float(yt.length)
        stream_list = []
        for s in streams:
            lang = getattr(s, 'audio_track_name', None)
            stream_list.append(StreamInfo(
                itag=s.itag,
                language=lang,
                abr=s.abr,
                size_mb=s.filesize_mb,
            ))

        logger.info("streams_found", extra={
            "url": url,
            "title": title,
            "stream_count": len(stream_list),
        })
        return title, duration_sec, stream_list

    @staticmethod
    def download_by_itag(url: str, itag: int, temp_dir: Path) -> Path:
        """Download a specific stream by itag to temp_dir. Returns path to downloaded file."""
        logger.info("download_by_itag_started", extra={"url": url, "itag": itag})
        yt = pytubefix.YouTube(url, on_progress_callback=on_progress)
        stream = yt.streams.get_by_itag(itag)
        if stream is None:
            raise ValueError(f"No stream found with itag {itag}")

        suffix = Path(stream.default_filename).suffix
        filename = slugify(stream.default_filename, max_length=25, separator='_')
        filename = f"{filename}{suffix}"

        temp_dir.mkdir(parents=True, exist_ok=True)
        stream.download(output_path=str(temp_dir), filename=filename)

        result_path = temp_dir / filename
        logger.info("download_by_itag_completed", extra={
            "url": url,
            "itag": itag,
            "path": str(result_path),
        })
        return result_path

    @classmethod
    def download_audio(cls, url: str, max_size_mb: float, temp_base_dir: Path) -> tuple[Path, Path, float]:
        """Download best quality audio. Convenience method.

        Returns (file_path, temp_dir, filesize_mb).
        """
        logger.info("download_audio_started", extra={"url": url})
        yt = pytubefix.YouTube(url, on_progress_callback=on_progress)
        streams = yt.streams.filter(only_audio=True, subtype='mp4').order_by("abr").desc()
        if not streams:
            raise ValueError("No audio streams available for this URL")

        audio_stream = streams[0]
        filesize_mb = audio_stream.filesize_mb

        suffix = Path(audio_stream.default_filename).suffix
        audio_filename = slugify(audio_stream.default_filename, max_length=25, separator='_')
        audio_filename = f"{audio_filename}{suffix}"

        temp_dir = temp_base_dir / Path(audio_filename).stem
        temp_dir.mkdir(parents=True, exist_ok=True)

        audio_stream.download(output_path=str(temp_dir), filename=audio_filename)

        temp_file_path = temp_dir / audio_filename
        logger.info("download_audio_completed", extra={
            "url": url,
            "path": str(temp_file_path),
            "filesize_mb": filesize_mb,
        })
        return temp_file_path, temp_dir, filesize_mb

    # Async wrappers using asyncio.to_thread()

    @classmethod
    async def async_get_available_streams(cls, url: str) -> tuple[str, float, list[StreamInfo]]:
        return await asyncio.to_thread(cls.get_available_streams, url)

    @classmethod
    async def async_download_by_itag(cls, url: str, itag: int, temp_dir: Path) -> Path:
        return await asyncio.to_thread(cls.download_by_itag, url, itag, temp_dir)

    @classmethod
    async def async_download_audio(cls, url: str, max_size_mb: float, temp_base_dir: Path) -> tuple[Path, Path, float]:
        return await asyncio.to_thread(cls.download_audio, url, max_size_mb, temp_base_dir)

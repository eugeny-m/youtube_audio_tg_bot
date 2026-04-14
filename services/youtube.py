import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytubefix
import pytubefix.extract
from pytubefix.streams import Stream
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
    def _get_streams_default_client(url: str) -> tuple[str, float, list[StreamInfo]]:
        """Get available audio streams using the default (ANDROID_VR) client.

        Returns (title, duration_sec, list of StreamInfo).
        """
        logger.info("getting_streams_default_client", extra={"url": url})
        yt = pytubefix.YouTube(url)
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
    def _get_streams_web_client(url: str) -> tuple[str, float, list[StreamInfo]]:
        """Get available audio streams using WEB client with SABR stream extraction.

        This discovers all audio tracks including dubbed/localized ones that are
        only available via the WEB client's SABR protocol.

        Returns (title, duration_sec, list of StreamInfo).
        """
        logger.info("getting_streams_web_client", extra={"url": url})
        yt = pytubefix.YouTube(url, client='WEB')
        vid_info = yt.vid_info
        streaming_data = vid_info['streamingData']
        stream_manifest = pytubefix.extract.apply_descrambler(streaming_data)

        title = vid_info['videoDetails']['title']
        duration_sec = float(vid_info['videoDetails']['lengthSeconds'])

        stream_list = []
        for fmt in stream_manifest:
            mime_type = fmt.get('mimeType', '')
            if 'audio' not in mime_type:
                continue
            stream = Stream(
                stream=fmt,
                monostate=yt.stream_monostate,
                po_token=yt.po_token,
                video_playback_ustreamer_config=yt.video_playback_ustreamer_config,
            )
            lang = getattr(stream, 'audio_track_name', None)
            stream_list.append(StreamInfo(
                itag=stream.itag,
                language=lang,
                abr=stream.abr,
                size_mb=stream.filesize_mb,
            ))

        if not stream_list:
            raise ValueError("No audio streams available from WEB client for this URL")

        # Sort by abr descending (same as default client)
        stream_list.sort(key=lambda s: s.abr, reverse=True)

        logger.info("streams_found_web_client", extra={
            "url": url,
            "title": title,
            "stream_count": len(stream_list),
            "languages": list(set(s.language for s in stream_list if s.language)),
        })
        return title, duration_sec, stream_list

    @staticmethod
    def get_available_streams(url: str) -> tuple[str, float, list[StreamInfo]]:
        """Get available audio streams for a video.

        Returns (title, duration_sec, list of StreamInfo).
        """
        return YoutubeService._get_streams_default_client(url)

    @staticmethod
    def download_by_itag(url: str, itag: int, temp_dir: Path) -> Path:
        """Download a specific stream by itag to temp_dir. Returns path to downloaded file."""
        logger.info("download_by_itag_started", extra={"url": url, "itag": itag})
        yt = pytubefix.YouTube(url)
        stream = yt.streams.get_by_itag(itag)
        if stream is None:
            raise ValueError(f"No stream found with itag {itag}")

        suffix = Path(stream.default_filename).suffix
        filename = slugify(Path(stream.default_filename).stem, max_length=25, separator='_')
        if not filename:
            filename = f"audio_{itag}"
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

    # Async wrappers using asyncio.to_thread()

    @classmethod
    async def async_get_available_streams(
        cls, url: str, timeout: float = 120,
    ) -> tuple[str, float, list[StreamInfo]]:
        return await asyncio.wait_for(
            asyncio.to_thread(cls.get_available_streams, url),
            timeout=timeout,
        )

    @classmethod
    async def async_download_by_itag(
        cls, url: str, itag: int, temp_dir: Path, timeout: float = 600,
    ) -> Path:
        return await asyncio.wait_for(
            asyncio.to_thread(cls.download_by_itag, url, itag, temp_dir),
            timeout=timeout,
        )

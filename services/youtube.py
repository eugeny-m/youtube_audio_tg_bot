import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytubefix
import pytubefix.extract
from pytubefix import exceptions as pytubefix_exceptions
from pytubefix.streams import Stream
from urllib.error import HTTPError
from slugify import slugify


logger = logging.getLogger(__name__)


def _parse_abr(abr: str | None) -> int:
    """Extract numeric bitrate from abr string like '128kbps'. Returns 0 on failure."""
    if not abr:
        return 0
    match = re.search(r"\d+", abr)
    return int(match.group()) if match else 0


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

        # YouTube ships each itag three times per language: the original audio
        # plus loudness-processed variants (DRC / "vb"), told apart by isDrc/xtags.
        # Those variants only exist on the SABR endpoint we can't download from,
        # so keep just the original per (itag, language) to avoid duplicate rows.
        seen: dict[tuple[int, Optional[str]], tuple[bool, StreamInfo]] = {}
        for fmt in stream_manifest:
            mime_type = fmt.get('mimeType', '')
            if 'audio' not in mime_type:
                continue
            try:
                stream = Stream(
                    stream=fmt,
                    monostate=yt.stream_monostate,
                    po_token=yt.po_token,
                    video_playback_ustreamer_config=yt.video_playback_ustreamer_config,
                )
                lang = getattr(stream, 'audio_track_name', None)
                is_original = not fmt.get('isDrc') and not fmt.get('xtags')
                key = (stream.itag, lang)
                existing = seen.get(key)
                if existing is not None and (existing[0] or not is_original):
                    # Already have the original, or this one isn't it — skip.
                    continue
                size_mb = stream.filesize_mb if stream._filesize_mb else 0.0
                seen[key] = (is_original, StreamInfo(
                    itag=stream.itag,
                    language=lang,
                    abr=stream.abr,
                    size_mb=size_mb,
                ))
            except Exception:
                logger.debug("skipping_unparseable_stream", extra={"itag": fmt.get("itag")})
                continue

        stream_list = [info for _, info in seen.values()]
        if not stream_list:
            raise ValueError("No audio streams available from WEB client for this URL")

        # Sort by abr descending (numeric, same as default client)
        stream_list.sort(key=lambda s: _parse_abr(s.abr), reverse=True)

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

        Tries WEB client first (discovers all audio tracks including dubbed/localized).
        Falls back to default client (ANDROID_VR) if WEB client fails.

        Returns (title, duration_sec, list of StreamInfo).
        """
        try:
            return YoutubeService._get_streams_web_client(url)
        except pytubefix_exceptions.LiveStreamEnded:
            # A just-ended live stream is unavailable on every client until
            # YouTube finishes processing the recording — falling back is futile.
            raise
        except Exception as e:
            logger.warning("web_client_failed_falling_back", extra={
                "url": url,
                "error": str(e),
            })
            return YoutubeService._get_streams_default_client(url)

    @staticmethod
    def _build_sabr_stream(url: str, itag: int) -> Stream:
        """Reconstruct a single SABR Stream by itag from WEB client's vid_info.

        Raises ValueError if the itag is not found among SABR audio streams.
        """
        yt = pytubefix.YouTube(url, client='WEB')
        vid_info = yt.vid_info
        streaming_data = vid_info['streamingData']
        stream_manifest = pytubefix.extract.apply_descrambler(streaming_data)

        for fmt in stream_manifest:
            if int(fmt.get('itag', 0)) == itag and 'audio' in fmt.get('mimeType', ''):
                return Stream(
                    stream=fmt,
                    monostate=yt.stream_monostate,
                    po_token=yt.po_token,
                    video_playback_ustreamer_config=yt.video_playback_ustreamer_config,
                )

        raise ValueError(f"No SABR audio stream found with itag {itag}")

    @staticmethod
    def _download_stream(stream, temp_dir: Path, itag: int) -> Path:
        """Download a stream to temp_dir. Returns path to downloaded file."""
        suffix = Path(stream.default_filename).suffix
        filename = slugify(Path(stream.default_filename).stem, max_length=25, separator='_')
        if not filename:
            filename = f"audio_{itag}"
        filename = f"{filename}{suffix}"

        temp_dir.mkdir(parents=True, exist_ok=True)
        stream.download(output_path=str(temp_dir), filename=filename)
        return temp_dir / filename

    @staticmethod
    def download_by_itag(url: str, itag: int, temp_dir: Path) -> Path:
        """Download a specific stream by itag to temp_dir. Returns path to downloaded file.

        Tries WEB client SABR stream first, falls back to default client.
        Raises an informative error on HTTP 403 (authentication may be required).
        """
        logger.info("download_by_itag_started", extra={"url": url, "itag": itag})

        # Try SABR stream (WEB client) first. Its media URLs often require a
        # po_token and return HTTP 403 — the default client serves the same itag
        # without one, so any failure here (403 included) must fall through.
        try:
            stream = YoutubeService._build_sabr_stream(url, itag)
            result_path = YoutubeService._download_stream(stream, temp_dir, itag)
            logger.info("download_by_itag_completed", extra={
                "url": url, "itag": itag, "path": str(result_path), "method": "sabr",
            })
            return result_path
        except Exception as e:
            logger.warning("sabr_download_failed_falling_back", extra={
                "url": url, "itag": itag, "error": str(e),
            })

        # Fallback to default client (ANDROID_VR).
        logger.info("download_by_itag_fallback_default", extra={"url": url, "itag": itag})
        try:
            yt = pytubefix.YouTube(url)
            stream = yt.streams.get_by_itag(itag)
            if stream is None:
                raise ValueError(f"No stream found with itag {itag}")
            result_path = YoutubeService._download_stream(stream, temp_dir, itag)
        except HTTPError as e:
            if e.code == 403:
                raise ValueError(
                    "Download blocked (HTTP 403). YouTube may require authentication "
                    "for this audio track. Try a different track or contact the bot admin."
                ) from e
            raise
        logger.info("download_by_itag_completed", extra={
            "url": url, "itag": itag, "path": str(result_path), "method": "default",
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

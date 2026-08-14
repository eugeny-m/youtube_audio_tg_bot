import asyncio
import logging
import re
import time
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

# Clients tried in order after the WEB/SABR path. None of them needs a po_token,
# but YouTube intermittently answers LOGIN_REQUIRED ("not a bot") to a given
# client, so a single one is not enough — TV keeps working when ANDROID_VR is
# refused, and vice versa. Their itag sets also differ (ANDROID_VR has 139,
# TV has 250), so neither one subsumes the other.
FALLBACK_CLIENTS = ('TV', 'ANDROID_VR')

# The bot check is transient: the same request usually passes seconds later.
BOT_DETECTION_RETRY_DELAY_SEC = 3.0

# Refusals aimed at the client rather than the video — the next client in the
# chain may well be served. Everything else under VideoUnavailable describes the
# video itself (live, private, removed…), so every client will answer the same.
CLIENT_REFUSALS = (
    pytubefix_exceptions.BotDetection,
    pytubefix_exceptions.LoginRequired,
    pytubefix_exceptions.PoTokenRequired,
    pytubefix_exceptions.InnerTubeResponseError,
)


def _is_about_the_video(error: Exception) -> bool:
    """Tell whether trying another client is pointless for this error."""
    return (
        isinstance(error, pytubefix_exceptions.VideoUnavailable)
        and not isinstance(error, CLIENT_REFUSALS)
    )


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


def _is_redundant(
    seen: dict[tuple[int, Optional[str]], tuple[bool, StreamInfo]],
    key: tuple[int, Optional[str]],
    is_original: bool,
) -> bool:
    """Tell whether this variant adds nothing over what is already recorded.

    YouTube ships each itag several times per language: the original audio plus
    loudness-processed variants (DRC / "vb"), told apart by isDrc/xtags. They
    are interchangeable for playback, so surfacing all of them would only mean
    duplicate rows in the track picker. Checked before the StreamInfo is built,
    since reading filesize costs a request to YouTube.
    """
    existing = seen.get(key)
    # Already have the original, or this one isn't it.
    return existing is not None and (existing[0] or not is_original)


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
    def _get_streams_query_client(url: str, client: str) -> tuple[str, float, list[StreamInfo]]:
        """Get available audio streams through pytubefix's stream query for a client.

        Returns (title, duration_sec, list of StreamInfo).
        """
        logger.info("getting_streams_query_client", extra={"url": url, "client": client})
        yt = pytubefix.YouTube(url, client=client)
        streams = yt.streams.filter(only_audio=True).order_by("abr").desc()
        if not streams:
            raise ValueError("No audio streams available for this URL")

        title = yt.title
        duration_sec = float(yt.length)
        seen: dict[tuple[int, Optional[str]], tuple[bool, StreamInfo]] = {}
        for s in streams:
            lang = getattr(s, 'audio_track_name', None)
            is_original = not getattr(s, 'is_drc', False) and not getattr(s, 'xtags', None)
            key = (s.itag, lang)
            if _is_redundant(seen, key, is_original):
                continue
            seen[key] = (is_original, StreamInfo(
                itag=s.itag,
                language=lang,
                abr=s.abr,
                size_mb=s.filesize_mb,
            ))

        stream_list = [info for _, info in seen.values()]
        logger.info("streams_found", extra={
            "url": url,
            "client": client,
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
                if _is_redundant(seen, key, is_original):
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
            # A live broadcast, or a recording YouTube hasn't finished processing,
            # carries no downloadable audio: its formats lack approxDurationMs and
            # are dropped above. check_availability turns that into the specific
            # reason (LiveStreamError, LiveStreamEnded…) YouTube already told us.
            yt.check_availability()
            raise ValueError("No audio streams available from WEB client for this URL")

        # Sort by abr descending (numeric, same order the query clients return)
        stream_list.sort(key=lambda s: _parse_abr(s.abr), reverse=True)

        logger.info("streams_found_web_client", extra={
            "url": url,
            "title": title,
            "stream_count": len(stream_list),
            "languages": list(set(s.language for s in stream_list if s.language)),
        })
        return title, duration_sec, stream_list

    @staticmethod
    def _get_streams_any_client(url: str) -> tuple[str, float, list[StreamInfo]]:
        """Walk the client chain until one returns audio streams.

        WEB comes first because it discovers dubbed/localized tracks the other
        clients don't expose. Raises the last client's error if none succeed.
        """
        try:
            return YoutubeService._get_streams_web_client(url)
        except Exception as e:
            if _is_about_the_video(e):
                raise
            logger.warning("web_client_failed_falling_back", extra={
                "url": url,
                "error": str(e),
            })
            last_error: Exception = e

        for client in FALLBACK_CLIENTS:
            try:
                return YoutubeService._get_streams_query_client(url, client)
            except Exception as e:
                if _is_about_the_video(e):
                    raise
                logger.warning("query_client_failed", extra={
                    "url": url,
                    "client": client,
                    "error": str(e),
                })
                last_error = e

        raise last_error

    @staticmethod
    def get_available_streams(url: str) -> tuple[str, float, list[StreamInfo]]:
        """Get available audio streams for a video.

        Returns (title, duration_sec, list of StreamInfo).
        """
        try:
            return YoutubeService._get_streams_any_client(url)
        except pytubefix_exceptions.BotDetection:
            logger.warning("bot_detection_retrying", extra={"url": url})
            time.sleep(BOT_DETECTION_RETRY_DELAY_SEC)
            return YoutubeService._get_streams_any_client(url)

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
    def _download_via_client(url: str, itag: int, temp_dir: Path, client: str) -> Path:
        """Download the itag through pytubefix's stream query for a client."""
        yt = pytubefix.YouTube(url, client=client)
        stream = yt.streams.get_by_itag(itag)
        if stream is None:
            raise ValueError(f"No stream found with itag {itag}")
        return YoutubeService._download_stream(stream, temp_dir, itag)

    @staticmethod
    def _download_any_client(url: str, itag: int, temp_dir: Path) -> Path:
        """Walk the client chain until one delivers the itag."""
        # SABR (WEB client) first: its media URLs often require a po_token and
        # return HTTP 403, but the other clients serve the same itag without one,
        # so any failure here (403 included) must fall through.
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
            last_error: Exception = e

        for client in FALLBACK_CLIENTS:
            logger.info("download_by_itag_fallback", extra={
                "url": url, "itag": itag, "client": client,
            })
            try:
                result_path = YoutubeService._download_via_client(url, itag, temp_dir, client)
            except Exception as e:
                logger.warning("client_download_failed", extra={
                    "url": url, "itag": itag, "client": client, "error": str(e),
                })
                last_error = e
                continue
            logger.info("download_by_itag_completed", extra={
                "url": url, "itag": itag, "path": str(result_path), "method": client,
            })
            return result_path

        if isinstance(last_error, HTTPError) and last_error.code == 403:
            raise ValueError(
                "Download blocked (HTTP 403). YouTube may require authentication "
                "for this audio track. Try a different track or contact the bot admin."
            ) from last_error
        raise last_error

    @staticmethod
    def download_by_itag(url: str, itag: int, temp_dir: Path) -> Path:
        """Download a specific stream by itag to temp_dir. Returns path to downloaded file.

        Raises an informative error on HTTP 403 (authentication may be required).
        """
        logger.info("download_by_itag_started", extra={"url": url, "itag": itag})
        try:
            return YoutubeService._download_any_client(url, itag, temp_dir)
        except pytubefix_exceptions.BotDetection:
            logger.warning("bot_detection_retrying", extra={"url": url, "itag": itag})
            time.sleep(BOT_DETECTION_RETRY_DELAY_SEC)
            return YoutubeService._download_any_client(url, itag, temp_dir)

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

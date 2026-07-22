import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from urllib.error import HTTPError

from services.youtube import YoutubeService, StreamInfo


class TestValidateUrl:
    def test_valid_url_returns_video_id(self):
        with patch("services.youtube.pytubefix.extract.video_id", return_value="abc123"):
            result = YoutubeService.validate_url("https://www.youtube.com/watch?v=abc123")
            assert result == "abc123"

    def test_invalid_url_returns_none(self):
        with patch("services.youtube.pytubefix.extract.video_id", side_effect=Exception("bad url")):
            result = YoutubeService.validate_url("not-a-url")
            assert result is None

    def test_empty_string_returns_none(self):
        with patch("services.youtube.pytubefix.extract.video_id", side_effect=Exception("empty")):
            result = YoutubeService.validate_url("")
            assert result is None


def _make_mock_stream(itag=140, abr="128kbps", filesize_mb=5.0, default_filename="test_video.mp4", audio_track_name=None):
    stream = MagicMock()
    stream.itag = itag
    stream.abr = abr
    stream.filesize_mb = filesize_mb
    stream.default_filename = default_filename
    stream.audio_track_name = audio_track_name
    return stream


def _make_mock_yt(title="Test Video", length=300, streams_list=None):
    if streams_list is None:
        streams_list = [_make_mock_stream()]

    yt = MagicMock()
    yt.title = title
    yt.length = length

    # Build a mock stream query that supports filter().order_by().desc()
    filtered = MagicMock()
    ordered = MagicMock()
    ordered.desc.return_value = streams_list
    filtered.order_by.return_value = ordered
    yt.streams.filter.return_value = filtered
    yt.streams.get_by_itag = lambda itag: next((s for s in streams_list if s.itag == itag), None)

    return yt


class TestGetAvailableStreams:
    def test_returns_streams(self):
        streams = [
            _make_mock_stream(itag=140, abr="128kbps", filesize_mb=5.0, audio_track_name="English"),
            _make_mock_stream(itag=251, abr="160kbps", filesize_mb=7.0, audio_track_name="Spanish"),
        ]
        mock_yt = _make_mock_yt(title="My Video", length=600, streams_list=streams)

        with patch("services.youtube.pytubefix.YouTube", return_value=mock_yt):
            title, duration, stream_infos = YoutubeService.get_available_streams("https://youtube.com/watch?v=test")

        assert title == "My Video"
        assert duration == 600.0
        assert len(stream_infos) == 2
        assert isinstance(stream_infos[0], StreamInfo)
        assert stream_infos[0].itag == 140
        assert stream_infos[0].language == "English"
        assert stream_infos[0].abr == "128kbps"
        assert stream_infos[0].size_mb == 5.0
        assert stream_infos[1].language == "Spanish"

    def test_no_streams_raises(self):
        mock_yt = _make_mock_yt(streams_list=[])
        # Empty list is falsy, so it should raise
        filtered = MagicMock()
        ordered = MagicMock()
        ordered.desc.return_value = []
        filtered.order_by.return_value = ordered
        mock_yt.streams.filter.return_value = filtered

        with patch("services.youtube.pytubefix.YouTube", return_value=mock_yt):
            with pytest.raises(ValueError, match="No audio streams"):
                YoutubeService.get_available_streams("https://youtube.com/watch?v=test")

    def test_stream_without_language(self):
        stream = _make_mock_stream(itag=140, abr="128kbps")
        # Simulate missing audio_track_name attribute
        del stream.audio_track_name
        mock_yt = _make_mock_yt(streams_list=[stream])

        with patch("services.youtube.pytubefix.YouTube", return_value=mock_yt):
            _, _, stream_infos = YoutubeService.get_available_streams("https://youtube.com/watch?v=test")

        assert stream_infos[0].language is None


class TestGetStreamsDefaultClient:
    def test_returns_same_result_as_get_available_streams(self):
        streams = [
            _make_mock_stream(itag=140, abr="128kbps", filesize_mb=5.0, audio_track_name="English"),
            _make_mock_stream(itag=251, abr="160kbps", filesize_mb=7.0, audio_track_name="Spanish"),
        ]
        mock_yt = _make_mock_yt(title="My Video", length=600, streams_list=streams)

        with patch("services.youtube.pytubefix.YouTube", return_value=mock_yt):
            result = YoutubeService._get_streams_default_client("https://youtube.com/watch?v=test")

        title, duration, stream_infos = result
        assert title == "My Video"
        assert duration == 600.0
        assert len(stream_infos) == 2
        assert stream_infos[0].itag == 140
        assert stream_infos[0].language == "English"
        assert stream_infos[0].abr == "128kbps"
        assert stream_infos[0].size_mb == 5.0
        assert stream_infos[1].itag == 251
        assert stream_infos[1].language == "Spanish"

    def test_no_streams_raises(self):
        mock_yt = _make_mock_yt(streams_list=[])
        filtered = MagicMock()
        ordered = MagicMock()
        ordered.desc.return_value = []
        filtered.order_by.return_value = ordered
        mock_yt.streams.filter.return_value = filtered

        with patch("services.youtube.pytubefix.YouTube", return_value=mock_yt):
            with pytest.raises(ValueError, match="No audio streams"):
                YoutubeService._get_streams_default_client("https://youtube.com/watch?v=test")


def _make_mock_sabr_fmt(itag=140, mime_type="audio/mp4", is_sabr=True):
    """Create a format dict as returned by extract.apply_descrambler for SABR streams."""
    return {
        'itag': itag,
        'mimeType': mime_type,
        'is_sabr': is_sabr,
    }


def _make_mock_web_yt(title="Test Video", length_seconds="300", streaming_data=None, stream_manifest=None):
    """Create a mock YouTube object for WEB client tests."""
    yt = MagicMock()
    yt.vid_info = {
        'videoDetails': {
            'title': title,
            'lengthSeconds': length_seconds,
        },
        'streamingData': streaming_data or {},
    }
    yt.stream_monostate = MagicMock()
    yt.po_token = "fake_po_token"
    yt.video_playback_ustreamer_config = "fake_config"
    return yt


class TestGetStreamsWebClient:
    def test_returns_sabr_audio_streams(self):
        stream_manifest = [
            _make_mock_sabr_fmt(itag=140, mime_type="audio/mp4"),
            _make_mock_sabr_fmt(itag=251, mime_type="audio/webm"),
            _make_mock_sabr_fmt(itag=299, mime_type="video/mp4"),  # video, should be excluded
        ]
        mock_yt = _make_mock_web_yt(title="Multi Track", length_seconds="600")

        mock_stream_140 = MagicMock()
        mock_stream_140.itag = 140
        mock_stream_140.abr = "128kbps"
        mock_stream_140.filesize_mb = 5.0
        mock_stream_140.audio_track_name = "English"

        mock_stream_251 = MagicMock()
        mock_stream_251.itag = 251
        mock_stream_251.abr = "160kbps"
        mock_stream_251.filesize_mb = 7.0
        mock_stream_251.audio_track_name = "Russian"

        stream_objects = iter([mock_stream_140, mock_stream_251])

        with patch("services.youtube.pytubefix.YouTube", return_value=mock_yt), \
             patch("services.youtube.pytubefix.extract.apply_descrambler", return_value=stream_manifest), \
             patch("services.youtube.Stream", side_effect=lambda **kwargs: next(stream_objects)):
            title, duration, stream_infos = YoutubeService._get_streams_web_client("https://youtube.com/watch?v=test")

        assert title == "Multi Track"
        assert duration == 600.0
        assert len(stream_infos) == 2
        # Sorted by abr descending: 160kbps first, then 128kbps
        assert stream_infos[0].itag == 251
        assert stream_infos[0].language == "Russian"
        assert stream_infos[0].abr == "160kbps"
        assert stream_infos[1].itag == 140
        assert stream_infos[1].language == "English"
        assert stream_infos[0].size_mb == 7.0
        assert stream_infos[1].size_mb == 5.0

    def test_returns_multiple_languages(self):
        stream_manifest = [
            _make_mock_sabr_fmt(itag=140, mime_type="audio/mp4"),
            _make_mock_sabr_fmt(itag=251, mime_type="audio/mp4"),
            _make_mock_sabr_fmt(itag=252, mime_type="audio/mp4"),
        ]
        mock_yt = _make_mock_web_yt(title="Polyglot Video", length_seconds="120")

        mock_streams = []
        for itag, lang, abr in [(140, "English", "128kbps"), (251, "Russian", "128kbps"), (252, "Spanish", "128kbps")]:
            s = MagicMock()
            s.itag = itag
            s.abr = abr
            s.filesize_mb = 5.0
            s.audio_track_name = lang
            mock_streams.append(s)

        stream_iter = iter(mock_streams)

        with patch("services.youtube.pytubefix.YouTube", return_value=mock_yt), \
             patch("services.youtube.pytubefix.extract.apply_descrambler", return_value=stream_manifest), \
             patch("services.youtube.Stream", side_effect=lambda **kwargs: next(stream_iter)):
            title, duration, stream_infos = YoutubeService._get_streams_web_client("https://youtube.com/watch?v=test")

        assert len(stream_infos) == 3
        languages = {s.language for s in stream_infos}
        assert languages == {"English", "Russian", "Spanish"}

    def test_no_audio_streams_raises(self):
        stream_manifest = [
            _make_mock_sabr_fmt(itag=299, mime_type="video/mp4"),  # only video
        ]
        mock_yt = _make_mock_web_yt()

        with patch("services.youtube.pytubefix.YouTube", return_value=mock_yt), \
             patch("services.youtube.pytubefix.extract.apply_descrambler", return_value=stream_manifest):
            with pytest.raises(ValueError, match="No audio streams available from WEB client"):
                YoutubeService._get_streams_web_client("https://youtube.com/watch?v=test")

    def test_uses_web_client(self):
        stream_manifest = [_make_mock_sabr_fmt(itag=140, mime_type="audio/mp4")]
        mock_yt = _make_mock_web_yt()
        mock_stream = MagicMock()
        mock_stream.itag = 140
        mock_stream.abr = "128kbps"
        mock_stream.filesize_mb = 5.0
        mock_stream.audio_track_name = None

        with patch("services.youtube.pytubefix.YouTube", return_value=mock_yt) as mock_yt_cls, \
             patch("services.youtube.pytubefix.extract.apply_descrambler", return_value=stream_manifest), \
             patch("services.youtube.Stream", return_value=mock_stream):
            YoutubeService._get_streams_web_client("https://youtube.com/watch?v=test")

        mock_yt_cls.assert_called_once_with("https://youtube.com/watch?v=test", client='WEB')

    def test_passes_monostate_and_tokens_to_stream(self):
        stream_manifest = [_make_mock_sabr_fmt(itag=140, mime_type="audio/mp4")]
        mock_yt = _make_mock_web_yt()
        mock_stream = MagicMock()
        mock_stream.itag = 140
        mock_stream.abr = "128kbps"
        mock_stream.filesize_mb = 5.0
        mock_stream.audio_track_name = None

        with patch("services.youtube.pytubefix.YouTube", return_value=mock_yt), \
             patch("services.youtube.pytubefix.extract.apply_descrambler", return_value=stream_manifest), \
             patch("services.youtube.Stream", return_value=mock_stream) as mock_stream_cls:
            YoutubeService._get_streams_web_client("https://youtube.com/watch?v=test")

        mock_stream_cls.assert_called_once_with(
            stream=stream_manifest[0],
            monostate=mock_yt.stream_monostate,
            po_token=mock_yt.po_token,
            video_playback_ustreamer_config=mock_yt.video_playback_ustreamer_config,
        )


class TestGetAvailableStreamsWithFallback:
    def test_web_success_returns_web_result(self):
        web_result = ("Web Title", 600.0, [
            StreamInfo(itag=140, language="English", abr="128kbps", size_mb=5.0),
            StreamInfo(itag=251, language="Russian", abr="128kbps", size_mb=5.0),
        ])

        with patch.object(YoutubeService, '_get_streams_web_client', return_value=web_result) as mock_web, \
             patch.object(YoutubeService, '_get_streams_default_client') as mock_default:
            title, duration, streams = YoutubeService.get_available_streams("https://youtube.com/watch?v=test")

        mock_web.assert_called_once_with("https://youtube.com/watch?v=test")
        mock_default.assert_not_called()
        assert title == "Web Title"
        assert len(streams) == 2
        assert streams[0].language == "English"
        assert streams[1].language == "Russian"

    def test_web_fails_falls_back_to_default(self):
        default_result = ("Default Title", 300.0, [
            StreamInfo(itag=140, language=None, abr="128kbps", size_mb=5.0),
        ])

        with patch.object(YoutubeService, '_get_streams_web_client', side_effect=Exception("cipher error")) as mock_web, \
             patch.object(YoutubeService, '_get_streams_default_client', return_value=default_result) as mock_default:
            title, duration, streams = YoutubeService.get_available_streams("https://youtube.com/watch?v=test")

        mock_web.assert_called_once_with("https://youtube.com/watch?v=test")
        mock_default.assert_called_once_with("https://youtube.com/watch?v=test")
        assert title == "Default Title"
        assert len(streams) == 1

    def test_live_stream_ended_does_not_fall_back(self):
        from pytubefix.exceptions import LiveStreamEnded

        with patch.object(YoutubeService, '_get_streams_web_client',
                          side_effect=LiveStreamEnded(video_id="test")) as mock_web, \
             patch.object(YoutubeService, '_get_streams_default_client') as mock_default:
            with pytest.raises(LiveStreamEnded):
                YoutubeService.get_available_streams("https://youtube.com/watch?v=test")

        mock_web.assert_called_once_with("https://youtube.com/watch?v=test")
        mock_default.assert_not_called()


class TestBuildSabrStream:
    def test_returns_stream_for_matching_itag(self):
        stream_manifest = [
            _make_mock_sabr_fmt(itag=140, mime_type="audio/mp4"),
            _make_mock_sabr_fmt(itag=251, mime_type="audio/webm"),
            _make_mock_sabr_fmt(itag=299, mime_type="video/mp4"),
        ]
        mock_yt = _make_mock_web_yt(title="Test", length_seconds="300")
        mock_stream = MagicMock()
        mock_stream.itag = 140

        with patch("services.youtube.pytubefix.YouTube", return_value=mock_yt) as mock_yt_cls, \
             patch("services.youtube.pytubefix.extract.apply_descrambler", return_value=stream_manifest), \
             patch("services.youtube.Stream", return_value=mock_stream) as mock_stream_cls:
            result = YoutubeService._build_sabr_stream("https://youtube.com/watch?v=test", 140)

        assert result == mock_stream
        mock_yt_cls.assert_called_once_with("https://youtube.com/watch?v=test", client='WEB')
        mock_stream_cls.assert_called_once_with(
            stream=stream_manifest[0],
            monostate=mock_yt.stream_monostate,
            po_token=mock_yt.po_token,
            video_playback_ustreamer_config=mock_yt.video_playback_ustreamer_config,
        )

    def test_raises_for_missing_itag(self):
        stream_manifest = [
            _make_mock_sabr_fmt(itag=140, mime_type="audio/mp4"),
        ]
        mock_yt = _make_mock_web_yt()

        with patch("services.youtube.pytubefix.YouTube", return_value=mock_yt), \
             patch("services.youtube.pytubefix.extract.apply_descrambler", return_value=stream_manifest):
            with pytest.raises(ValueError, match="No SABR audio stream found with itag 999"):
                YoutubeService._build_sabr_stream("https://youtube.com/watch?v=test", 999)

    def test_skips_video_streams(self):
        stream_manifest = [
            _make_mock_sabr_fmt(itag=140, mime_type="video/mp4"),  # video, not audio
        ]
        mock_yt = _make_mock_web_yt()

        with patch("services.youtube.pytubefix.YouTube", return_value=mock_yt), \
             patch("services.youtube.pytubefix.extract.apply_descrambler", return_value=stream_manifest):
            with pytest.raises(ValueError, match="No SABR audio stream found with itag 140"):
                YoutubeService._build_sabr_stream("https://youtube.com/watch?v=test", 140)


class TestDownloadByItag:
    def test_sabr_download_succeeds(self, tmp_path):
        """When SABR stream works, it should be used directly."""
        sabr_stream = _make_mock_stream(itag=140, default_filename="test_video.mp4")

        def fake_download(output_path, filename):
            Path(output_path, filename).touch()
        sabr_stream.download.side_effect = fake_download

        with patch.object(YoutubeService, '_build_sabr_stream', return_value=sabr_stream):
            result = YoutubeService.download_by_itag(
                "https://youtube.com/watch?v=test", 140, tmp_path
            )

        assert result.parent == tmp_path
        assert result.exists()
        sabr_stream.download.assert_called_once()

    def test_sabr_fails_falls_back_to_default(self, tmp_path):
        """When SABR fails with generic error, falls back to default client."""
        default_stream = _make_mock_stream(itag=140, default_filename="test_video.mp4")

        def fake_download(output_path, filename):
            Path(output_path, filename).touch()
        default_stream.download.side_effect = fake_download

        mock_yt = _make_mock_yt(streams_list=[default_stream])

        with patch.object(YoutubeService, '_build_sabr_stream', side_effect=Exception("SABR error")), \
             patch("services.youtube.pytubefix.YouTube", return_value=mock_yt):
            result = YoutubeService.download_by_itag(
                "https://youtube.com/watch?v=test", 140, tmp_path
            )

        assert result.exists()
        default_stream.download.assert_called_once()

    def test_sabr_403_falls_back_to_default(self, tmp_path):
        """HTTP 403 from SABR (needs po_token) must fall back to the default client."""
        http_error = HTTPError(
            url="https://example.com", code=403, msg="Forbidden",
            hdrs=MagicMock(), fp=MagicMock(),
        )
        default_stream = _make_mock_stream(itag=249, default_filename="test_video.webm")

        def fake_download(output_path, filename):
            Path(output_path, filename).touch()
        default_stream.download.side_effect = fake_download

        mock_yt = _make_mock_yt(streams_list=[default_stream])

        with patch.object(YoutubeService, '_build_sabr_stream', side_effect=http_error), \
             patch("services.youtube.pytubefix.YouTube", return_value=mock_yt):
            result = YoutubeService.download_by_itag(
                "https://youtube.com/watch?v=test", 249, tmp_path
            )

        assert result.exists()
        default_stream.download.assert_called_once()

    def test_default_403_raises_informative_message(self, tmp_path):
        """When even the default client 403s, raise the user-facing auth message."""
        http_error = HTTPError(
            url="https://example.com", code=403, msg="Forbidden",
            hdrs=MagicMock(), fp=MagicMock(),
        )
        default_stream = _make_mock_stream(itag=140, default_filename="test_video.mp4")
        default_stream.download.side_effect = http_error
        mock_yt = _make_mock_yt(streams_list=[default_stream])

        with patch.object(YoutubeService, '_build_sabr_stream', side_effect=Exception("SABR error")), \
             patch("services.youtube.pytubefix.YouTube", return_value=mock_yt):
            with pytest.raises(ValueError, match="HTTP 403"):
                YoutubeService.download_by_itag(
                    "https://youtube.com/watch?v=test", 140, tmp_path
                )

    def test_non_403_http_error_falls_back(self, tmp_path):
        """Non-403 HTTP errors should fall back to default client."""
        http_error = HTTPError(
            url="https://example.com", code=500, msg="Server Error",
            hdrs=MagicMock(), fp=MagicMock(),
        )

        default_stream = _make_mock_stream(itag=140, default_filename="test_video.mp4")

        def fake_download(output_path, filename):
            Path(output_path, filename).touch()
        default_stream.download.side_effect = fake_download

        mock_yt = _make_mock_yt(streams_list=[default_stream])

        with patch.object(YoutubeService, '_build_sabr_stream', side_effect=http_error), \
             patch("services.youtube.pytubefix.YouTube", return_value=mock_yt):
            result = YoutubeService.download_by_itag(
                "https://youtube.com/watch?v=test", 140, tmp_path
            )

        assert result.exists()

    def test_invalid_itag_both_clients_raises(self, tmp_path):
        """When itag not found in either client, raises ValueError."""
        mock_yt = _make_mock_yt(streams_list=[_make_mock_stream(itag=140)])

        with patch.object(YoutubeService, '_build_sabr_stream', side_effect=ValueError("No SABR")), \
             patch("services.youtube.pytubefix.YouTube", return_value=mock_yt):
            with pytest.raises(ValueError, match="No stream found with itag 999"):
                YoutubeService.download_by_itag(
                    "https://youtube.com/watch?v=test", 999, tmp_path
                )

    def test_creates_temp_dir_if_not_exists(self, tmp_path):
        sabr_stream = _make_mock_stream(itag=140, default_filename="test.mp4")

        def fake_download(output_path, filename):
            Path(output_path, filename).touch()
        sabr_stream.download.side_effect = fake_download

        new_dir = tmp_path / "subdir"
        with patch.object(YoutubeService, '_build_sabr_stream', return_value=sabr_stream):
            result = YoutubeService.download_by_itag(
                "https://youtube.com/watch?v=test", 140, new_dir
            )

        assert new_dir.exists()
        assert result.exists()


class TestAsyncWrappers:
    @pytest.mark.asyncio
    async def test_async_get_available_streams(self):
        streams = [_make_mock_stream(itag=140, abr="128kbps", audio_track_name="English")]
        mock_yt = _make_mock_yt(title="Async Test", length=120, streams_list=streams)

        with patch("services.youtube.pytubefix.YouTube", return_value=mock_yt):
            title, duration, infos = await YoutubeService.async_get_available_streams(
                "https://youtube.com/watch?v=test"
            )

        assert title == "Async Test"
        assert len(infos) == 1

    @pytest.mark.asyncio
    async def test_async_download_by_itag(self, tmp_path):
        sabr_stream = _make_mock_stream(itag=140, default_filename="test.mp4")

        def fake_download(output_path, filename):
            Path(output_path, filename).touch()

        sabr_stream.download.side_effect = fake_download

        with patch.object(YoutubeService, '_build_sabr_stream', return_value=sabr_stream):
            result = await YoutubeService.async_download_by_itag(
                "https://youtube.com/watch?v=test", 140, tmp_path
            )

        assert result.exists()

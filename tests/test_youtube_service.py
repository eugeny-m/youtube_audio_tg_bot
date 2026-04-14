import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

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


class TestDownloadByItag:
    def test_downloads_and_returns_path(self, tmp_path):
        stream = _make_mock_stream(itag=140, default_filename="test_video.mp4")
        mock_yt = _make_mock_yt(streams_list=[stream])

        # Make download create the file
        def fake_download(output_path, filename):
            Path(output_path, filename).touch()

        stream.download.side_effect = fake_download

        with patch("services.youtube.pytubefix.YouTube", return_value=mock_yt):
            result = YoutubeService.download_by_itag(
                "https://youtube.com/watch?v=test", 140, tmp_path
            )

        assert result.parent == tmp_path
        assert result.exists()
        stream.download.assert_called_once()

    def test_invalid_itag_raises(self, tmp_path):
        mock_yt = _make_mock_yt(streams_list=[_make_mock_stream(itag=140)])

        with patch("services.youtube.pytubefix.YouTube", return_value=mock_yt):
            with pytest.raises(ValueError, match="No stream found with itag 999"):
                YoutubeService.download_by_itag(
                    "https://youtube.com/watch?v=test", 999, tmp_path
                )

    def test_creates_temp_dir_if_not_exists(self, tmp_path):
        stream = _make_mock_stream(itag=140, default_filename="test.mp4")
        mock_yt = _make_mock_yt(streams_list=[stream])

        def fake_download(output_path, filename):
            Path(output_path, filename).touch()

        stream.download.side_effect = fake_download

        new_dir = tmp_path / "subdir"
        with patch("services.youtube.pytubefix.YouTube", return_value=mock_yt):
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
        stream = _make_mock_stream(itag=140, default_filename="test.mp4")
        mock_yt = _make_mock_yt(streams_list=[stream])

        def fake_download(output_path, filename):
            Path(output_path, filename).touch()

        stream.download.side_effect = fake_download

        with patch("services.youtube.pytubefix.YouTube", return_value=mock_yt):
            result = await YoutubeService.async_download_by_itag(
                "https://youtube.com/watch?v=test", 140, tmp_path
            )

        assert result.exists()

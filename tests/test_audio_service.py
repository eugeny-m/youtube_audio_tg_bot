from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from services.audio import split_audio_ffmpeg, prepare_files_to_send, async_split_audio_ffmpeg, async_prepare_files_to_send


class TestSplitAudioFfmpeg:
    def test_splits_into_expected_chunks(self, tmp_path):
        # Create a fake input file of 10MB
        input_file = tmp_path / "audio.mp4"
        input_file.write_bytes(b"\x00" * (10 * 1024 * 1024))

        ffprobe_result = MagicMock()
        ffprobe_result.stdout = "120.0\n"
        ffprobe_result.stderr = ""

        ffmpeg_result = MagicMock()
        ffmpeg_result.returncode = 0

        def fake_run(cmd, **kwargs):
            if cmd[0] == "ffprobe":
                return ffprobe_result
            # ffmpeg: create the output file
            output_path = cmd[-1]
            Path(output_path).touch()
            return ffmpeg_result

        with patch("services.audio.subprocess.run", side_effect=fake_run):
            chunks = split_audio_ffmpeg(input_file, max_size_mb=5.0)

        # 10MB file / 5MB chunks = 2 chunks
        assert len(chunks) == 2
        assert all(c.exists() for c in chunks)
        assert all(c.parent == tmp_path for c in chunks)
        assert chunks[0].name == "audio_00.mp4"
        assert chunks[1].name == "audio_01.mp4"

    def test_single_chunk_when_under_limit(self, tmp_path):
        input_file = tmp_path / "small.mp4"
        input_file.write_bytes(b"\x00" * (3 * 1024 * 1024))

        ffprobe_result = MagicMock()
        ffprobe_result.stdout = "60.0\n"

        def fake_run(cmd, **kwargs):
            if cmd[0] == "ffprobe":
                return ffprobe_result
            Path(cmd[-1]).touch()
            return MagicMock(returncode=0)

        with patch("services.audio.subprocess.run", side_effect=fake_run):
            chunks = split_audio_ffmpeg(input_file, max_size_mb=5.0)

        assert len(chunks) == 1

    def test_ffmpeg_error_raises(self, tmp_path):
        import subprocess as sp
        input_file = tmp_path / "audio.mp4"
        input_file.write_bytes(b"\x00" * (10 * 1024 * 1024))

        ffprobe_result = MagicMock()
        ffprobe_result.stdout = "120.0\n"

        call_count = 0

        def fake_run(cmd, **kwargs):
            nonlocal call_count
            if cmd[0] == "ffprobe":
                return ffprobe_result
            call_count += 1
            raise sp.CalledProcessError(1, cmd, stderr="ffmpeg error")

        with patch("services.audio.subprocess.run", side_effect=fake_run):
            with pytest.raises(sp.CalledProcessError):
                split_audio_ffmpeg(input_file, max_size_mb=5.0)

    def test_chunk_naming_preserves_suffix(self, tmp_path):
        input_file = tmp_path / "song.m4a"
        input_file.write_bytes(b"\x00" * (10 * 1024 * 1024))

        ffprobe_result = MagicMock()
        ffprobe_result.stdout = "200.0\n"

        def fake_run(cmd, **kwargs):
            if cmd[0] == "ffprobe":
                return ffprobe_result
            Path(cmd[-1]).touch()
            return MagicMock(returncode=0)

        with patch("services.audio.subprocess.run", side_effect=fake_run):
            chunks = split_audio_ffmpeg(input_file, max_size_mb=5.0)

        assert all(c.suffix == ".m4a" for c in chunks)


class TestPrepareFilesToSend:
    def test_under_limit_returns_single_file(self, tmp_path):
        f = tmp_path / "audio.mp4"
        f.touch()
        result = prepare_files_to_send(f, filesize_mb=3.0, max_size_mb=5.0)
        assert result == [f]

    def test_at_limit_returns_single_file(self, tmp_path):
        f = tmp_path / "audio.mp4"
        f.touch()
        result = prepare_files_to_send(f, filesize_mb=5.0, max_size_mb=5.0)
        assert result == [f]

    def test_over_limit_calls_split(self, tmp_path):
        f = tmp_path / "audio.mp4"
        f.touch()
        chunk1 = tmp_path / "audio_00.mp4"
        chunk2 = tmp_path / "audio_01.mp4"

        with patch("services.audio.split_audio_ffmpeg", return_value=[chunk1, chunk2]) as mock_split:
            result = prepare_files_to_send(f, filesize_mb=10.0, max_size_mb=5.0)

        mock_split.assert_called_once_with(f, 5.0)
        assert result == [chunk1, chunk2]


class TestAsyncWrappers:
    @pytest.mark.asyncio
    async def test_async_split_audio_ffmpeg(self, tmp_path):
        input_file = tmp_path / "audio.mp4"
        input_file.write_bytes(b"\x00" * (10 * 1024 * 1024))

        ffprobe_result = MagicMock()
        ffprobe_result.stdout = "120.0\n"

        def fake_run(cmd, **kwargs):
            if cmd[0] == "ffprobe":
                return ffprobe_result
            Path(cmd[-1]).touch()
            return MagicMock(returncode=0)

        with patch("services.audio.subprocess.run", side_effect=fake_run):
            chunks = await async_split_audio_ffmpeg(input_file, max_size_mb=5.0)

        assert len(chunks) == 2

    @pytest.mark.asyncio
    async def test_async_prepare_files_to_send_under_limit(self, tmp_path):
        f = tmp_path / "audio.mp4"
        f.touch()
        result = await async_prepare_files_to_send(f, filesize_mb=3.0, max_size_mb=5.0)
        assert result == [f]

    @pytest.mark.asyncio
    async def test_async_prepare_files_to_send_over_limit(self, tmp_path):
        f = tmp_path / "audio.mp4"
        f.touch()
        chunk1 = tmp_path / "audio_00.mp4"
        chunk2 = tmp_path / "audio_01.mp4"

        with patch("services.audio.split_audio_ffmpeg", return_value=[chunk1, chunk2]):
            result = await async_prepare_files_to_send(f, filesize_mb=10.0, max_size_mb=5.0)

        assert result == [chunk1, chunk2]

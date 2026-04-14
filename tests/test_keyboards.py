import pytest

from bot.keyboards import tracks_keyboard, bitrate_keyboard, get_track_languages
from services.youtube import StreamInfo


@pytest.fixture
def sample_streams():
    return [
        StreamInfo(itag=140, language="English", abr="128kbps", size_mb=3.5),
        StreamInfo(itag=251, language="English", abr="160kbps", size_mb=4.2),
        StreamInfo(itag=250, language="Spanish", abr="128kbps", size_mb=3.4),
    ]


@pytest.fixture
def single_language_streams():
    return [
        StreamInfo(itag=140, language=None, abr="128kbps", size_mb=3.5),
        StreamInfo(itag=251, language=None, abr="160kbps", size_mb=4.2),
    ]


class TestTracksKeyboard:
    def test_unique_languages_extracted(self, sample_streams):
        kb = tracks_keyboard(sample_streams)
        buttons = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "English" in buttons
        assert "Spanish" in buttons
        assert len(buttons) == 2

    def test_callback_data_format(self, sample_streams):
        kb = tracks_keyboard(sample_streams)
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "track:0" in callbacks
        assert "track:1" in callbacks

    def test_default_label_for_none_language(self, single_language_streams):
        kb = tracks_keyboard(single_language_streams)
        buttons = [btn.text for row in kb.inline_keyboard for btn in row]
        assert buttons == ["Default"]

    def test_callback_data_for_none_language(self, single_language_streams):
        kb = tracks_keyboard(single_language_streams)
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert callbacks == ["track:0"]

    def test_empty_streams(self):
        kb = tracks_keyboard([])
        assert kb.inline_keyboard == []


class TestBitrateKeyboard:
    def test_best_quality_button_present(self, sample_streams):
        kb = bitrate_keyboard(sample_streams)
        first_btn = kb.inline_keyboard[0][0]
        assert "Best quality" in first_btn.text
        assert first_btn.callback_data == "bitrate:best"

    def test_best_quality_uses_highest_bitrate(self, sample_streams):
        kb = bitrate_keyboard(sample_streams)
        first_btn = kb.inline_keyboard[0][0]
        assert "160kbps" in first_btn.text
        assert "4.2 MB" in first_btn.text

    def test_all_streams_have_buttons(self, sample_streams):
        kb = bitrate_keyboard(sample_streams)
        # 1 best + 2 individual (best stream excluded from individual list)
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        assert len(buttons) == 3

    def test_bitrate_callback_data_format(self, sample_streams):
        kb = bitrate_keyboard(sample_streams)
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "bitrate:best" in callbacks
        assert "bitrate:140" in callbacks
        # itag 251 is the best stream, so it only appears as "bitrate:best"
        assert "bitrate:250" in callbacks

    def test_size_displayed_in_buttons(self, sample_streams):
        kb = bitrate_keyboard(sample_streams)
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        # Each individual button should show size
        assert any("3.5 MB" in t for t in texts)
        assert any("4.2 MB" in t for t in texts)
        assert any("3.4 MB" in t for t in texts)

    def test_single_stream(self):
        streams = [StreamInfo(itag=140, language=None, abr="128kbps", size_mb=3.5)]
        kb = bitrate_keyboard(streams)
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        # Only 1 best button (single stream is the best, so no duplicates)
        assert len(buttons) == 1
        assert buttons[0].callback_data == "bitrate:best"

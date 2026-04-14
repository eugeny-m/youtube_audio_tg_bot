# Fix Audio Track Selection for Multi-Language Videos

## Overview
- YouTube videos with multiple audio tracks (e.g., original + dubbed) don't show track selection in the bot
- Root cause: pytubefix's default client (ANDROID_VR) only returns the original audio track; extra tracks (dubbed/localized) are only available via WEB client using SABR protocol
- Fix: switch to WEB client for stream discovery and download, handle SABR streams
- On Russian servers, SABR may work without authentication due to YouTube's ad policy in Russia

## Acceptance Criteria
1. Multi-language videos show audio track selection before bitrate selection
2. Single-language videos skip track selection (current behavior preserved)
3. Download works for both default and extra (SABR) audio tracks
4. If WEB client fails, fallback to ANDROID_VR client preserves current functionality

## Context (from discovery)
- **files/components involved**: `services/youtube.py`, `bot/handlers/download.py`, `tests/test_youtube_service.py`, `tests/test_handlers_download.py`, `requirements.txt`
- **related patterns found**: pytubefix WEB client discovers all audio tracks but `fmt_streams` fails on cipher; SABR streams can be created manually from `vid_info`; all `YoutubeService` methods are `@staticmethod`
- **dependencies**: pytubefix 9.5.0 → 10.3.8 (SABR support required)
- **key finding**: `extract.apply_descrambler()` + manual `Stream()` construction bypasses cipher issue for SABR-only streams

## Development Approach
- **testing approach**: Regular (code first, then tests)
- complete each task fully before moving to the next
- make small, focused changes
- **CRITICAL: every task MUST include new/updated tests** for code changes in that task
- **CRITICAL: all tests must pass before starting next task**
- **CRITICAL: update this plan file when scope changes during implementation**
- run tests after each change
- maintain backward compatibility

## Testing Strategy
- **unit tests**: required for every task, in `tests/test_youtube_service.py` and `tests/test_handlers_download.py`
- mock pytubefix internals (YouTube, extract, Stream) to avoid real network calls in tests

## Progress Tracking
- mark completed items with `[x]` immediately when done
- add newly discovered tasks with ➕ prefix
- document issues/blockers with ⚠️ prefix

## Solution Overview
1. Update pytubefix to 10.3.8 (required for SABR support)
2. Refactor `YoutubeService` to use WEB client with SABR stream extraction for discovery
3. Refactor `download_by_itag()` to reconstruct SABR streams for download (same WEB client approach)
4. Fall back to ANDROID_VR client if WEB client fails
5. Handle the case where SABR download fails (403) — fall back gracefully

## Technical Details

### SABR Stream Construction (pseudocode)
```python
from pytubefix import YouTube, extract
from pytubefix.streams import Stream

yt = YouTube(url, client='WEB')
# vid_info works fine, only fmt_streams fails on cipher
vid_info = yt.vid_info
streaming_data = vid_info['streamingData']

# apply_descrambler normalizes format data, sets is_sabr=True for URL-less formats
stream_manifest = extract.apply_descrambler(streaming_data)

# Filter and create Stream objects manually (bypasses cipher)
for fmt in stream_manifest:
    if fmt.get('is_sabr') and 'audio' in fmt.get('mimeType', ''):
        stream = Stream(
            stream=fmt,
            monostate=yt.stream_monostate,
            po_token=yt.po_token,
            video_playback_ustreamer_config=yt.video_playback_ustreamer_config,
        )
        # stream.audio_track_name → "English", "Russian", etc.
        # stream.is_sabr → True
        # stream.download() → uses ServerAbrStream internally
```

### Stream lifecycle: discovery → download
- **Problem**: current `download_by_itag()` creates a new `YouTube(url)` and calls `yt.streams.get_by_itag()`, which fails for WEB client (cipher error) and doesn't find SABR streams
- **Solution**: `download_by_itag()` must use the same WEB client + manual SABR stream reconstruction approach. Reconstruct the SABR Stream from `vid_info` at download time (stateless, no caching needed), then call `stream.download()`. This keeps `YoutubeService` stateless (`@staticmethod`s preserved).

### Discovery flow
1. Create `YouTube(url, client='WEB')`
2. Access `vid_info` → `streamingData` (does NOT trigger cipher)
3. Use `extract.apply_descrambler()` to normalize format data
4. Filter SABR audio streams, create `Stream()` objects manually
5. Extract `StreamInfo` from each Stream
6. If WEB fails entirely, fall back to default client (ANDROID_VR)

### Download flow
1. Create `YouTube(url, client='WEB')` again
2. Same SABR stream reconstruction from `vid_info`
3. Find stream matching requested itag
4. Call `stream.download()` — pytubefix handles SABR via `ServerAbrStream`
5. If 403/error → report to user

## Implementation Steps

### Task 1: Update pytubefix to 10.3.8

**Files:**
- Modify: `requirements.txt`

- [x] Update `pytubefix==9.5.0` → `pytubefix==10.3.8` in `requirements.txt`
- [x] Verify no breaking API changes in existing code by running tests
- [x] Run tests — must pass before next task

### Task 2a: Extract current stream logic into fallback method

**Files:**
- Modify: `services/youtube.py`

- [x] Move current `get_available_streams()` body into `_get_streams_default_client(url)` static method
- [x] Update `get_available_streams()` to call `_get_streams_default_client()` (behavior unchanged)
- [x] Write test verifying `_get_streams_default_client()` returns same result as before
- [x] Run tests — must pass before next task

### Task 2b: Implement WEB client SABR stream discovery

**Files:**
- Modify: `services/youtube.py`

- [x] Add `_get_streams_web_client(url)` static method:
  - Creates `YouTube(url, client='WEB')`
  - Accesses `yt.vid_info['streamingData']`
  - Calls `extract.apply_descrambler(streaming_data)`
  - Filters SABR audio streams (`is_sabr=True`, mimeType contains 'audio')
  - Creates `Stream()` objects manually using `yt.stream_monostate`, `yt.po_token`, `yt.video_playback_ustreamer_config`
  - Returns `(title, duration_sec, list[StreamInfo])`
- [x] Write tests for `_get_streams_web_client()` with mocked `YouTube`, `extract`, `Stream`
- [x] Write test that `_get_streams_web_client()` returns multiple languages
- [x] Run tests — must pass before next task

### Task 2c: Wire up WEB client with fallback

**Files:**
- Modify: `services/youtube.py`

- [x] Update `get_available_streams()` to try `_get_streams_web_client()` first
- [x] On any exception, log warning and fall back to `_get_streams_default_client()`
- [x] Write test: WEB success → returns WEB result
- [x] Write test: WEB fails → falls back to default client
- [x] Run tests — must pass before next task

### Task 3: Refactor download to use WEB client + SABR reconstruction

**Files:**
- Modify: `services/youtube.py`
- Modify: `bot/handlers/download.py`

- [ ] Add `_build_sabr_stream(url, itag)` static method that reconstructs a single SABR Stream by itag from WEB client's vid_info
- [ ] Update `download_by_itag()` to use `_build_sabr_stream()` instead of `yt.streams.get_by_itag()`
- [ ] Add fallback: if SABR stream not found or download fails, try default client's `get_by_itag()`
- [ ] Add graceful 403 error handling: notify user about possible authentication requirement
- [ ] Write tests for `_build_sabr_stream()` with mocked pytubefix
- [ ] Write tests for download fallback and 403 handling
- [ ] Run tests — must pass before next task

### Task 4: Verify acceptance criteria

- [ ] Verify multi-track video shows track selection (test with https://youtu.be/N0WuXG1wGQk)
- [ ] Verify single-track video skips to bitrate selection (current behavior preserved)
- [ ] Verify download works for both default and extra audio tracks
- [ ] Verify fallback to default client works when WEB client fails
- [ ] Run full test suite: `pytest tests/`

### Task 5: [Final] Update documentation

- [ ] Update CLAUDE.md if new patterns discovered
- [ ] Move this plan to `docs/plans/completed/`

## Post-Completion

**Manual verification** (on Russian server):
- Test with multi-language video (https://youtu.be/N0WuXG1wGQk) — should show Russian + English tracks
- Test SABR download without cookies — expected to work on Russian server without auth
- Test with single-language video — should skip track selection as before

**If SABR download requires authentication** (403 errors on server):
- Add `youtube_cookies_file: Optional[Path]` to `Settings` in `core/config.py`
- Load cookies from Netscape cookies.txt via `http.cookiejar.MozillaCookieJar`
- Pass cookie jar to `YouTube()` constructor
- Document in README.md how to export and configure cookies

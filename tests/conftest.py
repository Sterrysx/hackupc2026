"""Test configuration.

The voice stack (`faster_whisper` → `av`) ships native DLLs that are blocked
by Windows AppLocker on this dev box. Importing `app` indirectly loads them,
breaking *every* HTTP test even when the test has nothing to do with audio.

We pre-stub the audio modules here so `import app` succeeds. Tests that need
real STT/TTS behaviour should patch `app.transcriber` / `app.speaker` directly
(see `tests/test_app.py` for the pattern).
"""
from __future__ import annotations

import sys
import types


def _install_audio_stubs() -> None:
    class SpeechToText:  # noqa: D401 — stub
        def __init__(self, *_, **__): ...
        def transcribe(self, *_, **__) -> str: return ""

    class TextToSpeech:  # noqa: D401 — stub
        def __init__(self, *_, **__): self.voice = None
        async def generate_speech(self, *_, **__) -> str: return ""

    # Dual-key: stub under both the legacy top-level paths (`stt.transcriber`,
    # `tts.speaker`) AND the post-refactor paths (`backend.voice.stt.transcriber`,
    # `backend.voice.tts.speaker`). Whichever import path the code tries, the
    # stub is found before the real module's native DLLs load.
    if "stt.transcriber" not in sys.modules:
        stub_stt = types.ModuleType("stt.transcriber")
        stub_stt.SpeechToText = SpeechToText
        sys.modules.setdefault("stt", types.ModuleType("stt"))
        sys.modules["stt.transcriber"] = stub_stt

    if "tts.speaker" not in sys.modules:
        stub_tts = types.ModuleType("tts.speaker")
        stub_tts.TextToSpeech = TextToSpeech
        sys.modules.setdefault("tts", types.ModuleType("tts"))
        sys.modules["tts.speaker"] = stub_tts

    # For the new ``backend.voice.*`` paths the parent packages exist on disk
    # (after the Phase-2 move), so we MUST NOT stub them here — a non-package
    # ModuleType (without ``__path__``) would block Python from discovering
    # real submodules like ``backend.agent``. Stub only the leaf modules that
    # actually load DLLs.
    if "backend.voice.stt.transcriber" not in sys.modules:
        stub_stt_new = types.ModuleType("backend.voice.stt.transcriber")
        stub_stt_new.SpeechToText = SpeechToText
        sys.modules["backend.voice.stt.transcriber"] = stub_stt_new

    if "backend.voice.tts.speaker" not in sys.modules:
        stub_tts_new = types.ModuleType("backend.voice.tts.speaker")
        stub_tts_new.TextToSpeech = TextToSpeech
        sys.modules["backend.voice.tts.speaker"] = stub_tts_new


_install_audio_stubs()

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
    if "stt.transcriber" not in sys.modules:
        stub_stt = types.ModuleType("stt.transcriber")

        class SpeechToText:  # noqa: D401 — stub
            def __init__(self, *_, **__): ...
            def transcribe(self, *_, **__) -> str: return ""

        stub_stt.SpeechToText = SpeechToText
        sys.modules.setdefault("stt", types.ModuleType("stt"))
        sys.modules["stt.transcriber"] = stub_stt

    if "tts.speaker" not in sys.modules:
        stub_tts = types.ModuleType("tts.speaker")

        class TextToSpeech:  # noqa: D401 — stub
            def __init__(self, *_, **__): self.voice = None
            async def generate_speech(self, *_, **__) -> str: return ""

        stub_tts.TextToSpeech = TextToSpeech
        sys.modules.setdefault("tts", types.ModuleType("tts"))
        sys.modules["tts.speaker"] = stub_tts


_install_audio_stubs()

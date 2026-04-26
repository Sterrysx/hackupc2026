"""Unit tests for the voice I/O wrappers (`stt.transcriber`, `tts.speaker`).

The project's `tests/conftest.py` swaps these modules with empty stubs so
``import app`` succeeds on Windows AppLocker-blocked dev machines (faster_whisper's
PyAV native DLLs are blocked). For these unit tests we want the *real*
classes — so we drop the stubs from ``sys.modules`` and re-import after
mocking the underlying native libraries with ``unittest.mock``.

No ``pytest-asyncio`` dependency: async coroutines are driven via
``asyncio.run``.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ----------------------------------- import helpers (drop conftest stubs)


def _reload_real_stt(fake_whisper_cls):
    """Reload the real ``stt.transcriber`` with a faked ``WhisperModel``."""
    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = fake_whisper_cls
    sys.modules["faster_whisper"] = fake_module
    sys.modules.pop("stt.transcriber", None)
    # Wipe the conftest stub's package shim, but keep `stt` package directory.
    if "stt" in sys.modules and not hasattr(sys.modules["stt"], "__path__"):
        del sys.modules["stt"]
    return importlib.import_module("stt.transcriber")


def _reload_real_tts():
    """Reload ``tts.speaker`` so the real (non-stub) class is exercised."""
    sys.modules.pop("tts.speaker", None)
    if "tts" in sys.modules and not hasattr(sys.modules["tts"], "__path__"):
        del sys.modules["tts"]
    return importlib.import_module("tts.speaker")


# -------------------------------------------------- SpeechToText.__init__


def test_speech_to_text_init_passes_default_args_to_whisper():
    captured: dict = {}

    class FakeWhisper:
        def __init__(self, model_size, device, compute_type):
            captured["model_size"] = model_size
            captured["device"] = device
            captured["compute_type"] = compute_type

        def transcribe(self, *_, **__):
            return iter(()), None

    stt_mod = _reload_real_stt(FakeWhisper)
    _ = stt_mod.SpeechToText()
    assert captured == {"model_size": "base", "device": "cpu", "compute_type": "int8"}


def test_speech_to_text_init_forwards_overrides():
    captured: dict = {}

    class FakeWhisper:
        def __init__(self, model_size, device, compute_type):
            captured["args"] = (model_size, device, compute_type)

        def transcribe(self, *_, **__):
            return iter(()), None

    stt_mod = _reload_real_stt(FakeWhisper)
    _ = stt_mod.SpeechToText(model_size="small", device="cuda", compute_type="float16")
    assert captured["args"] == ("small", "cuda", "float16")


# ------------------------------------------ SpeechToText.transcribe joins


def _make_fake_segments(texts):
    """Yield fake whisper Segment-like objects whose .text is preset."""
    for t in texts:
        seg = MagicMock()
        seg.text = t
        yield seg


def test_transcribe_joins_segment_text_with_whitespace_and_strips():
    class FakeWhisper:
        def __init__(self, *a, **k): ...

        def transcribe(self, audio, beam_size=5):
            return _make_fake_segments(["Hello", "world", "this is a test"]), None

    stt_mod = _reload_real_stt(FakeWhisper)
    transcriber = stt_mod.SpeechToText()
    out = transcriber.transcribe("dummy.wav")
    # Real impl appends each segment.text + " " then strips → values get
    # joined with single spaces and the trailing space is stripped.
    assert out == "Hello world this is a test"


def test_transcribe_returns_empty_string_when_no_segments():
    class FakeWhisper:
        def __init__(self, *a, **k): ...

        def transcribe(self, audio, beam_size=5):
            return iter(()), None

    stt_mod = _reload_real_stt(FakeWhisper)
    transcriber = stt_mod.SpeechToText()
    assert transcriber.transcribe("anything.wav") == ""


def test_transcribe_propagates_underlying_model_errors(tmp_path):
    """File-not-found raised by the real whisper model surfaces to the caller."""

    class FakeWhisper:
        def __init__(self, *a, **k): ...

        def transcribe(self, audio, beam_size=5):
            raise FileNotFoundError(audio)

    stt_mod = _reload_real_stt(FakeWhisper)
    transcriber = stt_mod.SpeechToText()
    bogus_path = str(tmp_path / "does-not-exist.wav")
    assert not os.path.exists(bogus_path)
    with pytest.raises(FileNotFoundError):
        transcriber.transcribe(bogus_path)


# ---------------------------------------------------- TextToSpeech basics


def test_text_to_speech_default_voice():
    tts_mod = _reload_real_tts()
    speaker = tts_mod.TextToSpeech()
    assert speaker.voice == "en-US-AndrewNeural"


def test_text_to_speech_voice_attribute_is_mutable():
    tts_mod = _reload_real_tts()
    speaker = tts_mod.TextToSpeech()
    speaker.voice = "en-US-EmmaNeural"
    assert speaker.voice == "en-US-EmmaNeural"


# ----------------------------------------- TextToSpeech.generate_speech


def test_generate_speech_returns_mp3_path_and_invokes_communicate():
    tts_mod = _reload_real_tts()
    captured = {}

    class FakeCommunicate:
        def __init__(self, text, voice):
            captured["text"] = text
            captured["voice"] = voice

        async def save(self, path):
            captured["path"] = path

    with patch.object(tts_mod, "edge_tts") as fake_edge:
        fake_edge.Communicate = FakeCommunicate
        speaker = tts_mod.TextToSpeech()
        result_path = asyncio.run(speaker.generate_speech("Hello operator."))

    assert result_path.endswith(".mp3")
    assert captured["text"] == "Hello operator."
    assert captured["voice"] == "en-US-AndrewNeural"
    assert captured["path"] == result_path

    # Cleanup the temp file mkstemp created (Communicate was a fake, so
    # nothing was actually written, but the FD-backed file does exist).
    if os.path.exists(result_path):
        os.unlink(result_path)


def test_generate_speech_with_empty_string_still_returns_mp3_path():
    """Edge case: empty input is still passed through; we don't preempt
    edge_tts's own validation."""
    tts_mod = _reload_real_tts()

    class FakeCommunicate:
        def __init__(self, *_args, **_kwargs): ...

        async def save(self, _path): ...

    with patch.object(tts_mod, "edge_tts") as fake_edge:
        fake_edge.Communicate = FakeCommunicate
        speaker = tts_mod.TextToSpeech()
        path = asyncio.run(speaker.generate_speech(""))

    assert path.endswith(".mp3")
    if os.path.exists(path):
        os.unlink(path)


def test_generate_speech_uses_provided_output_path():
    tts_mod = _reload_real_tts()
    captured = {}

    class FakeCommunicate:
        def __init__(self, text, voice):
            captured["text"] = text

        async def save(self, path):
            captured["save_path"] = path

    with patch.object(tts_mod, "edge_tts") as fake_edge:
        fake_edge.Communicate = FakeCommunicate
        speaker = tts_mod.TextToSpeech()
        result = asyncio.run(speaker.generate_speech("hi", output_path="custom.mp3"))

    assert result == "custom.mp3"
    assert captured["save_path"] == "custom.mp3"


# --------------------------------------- text_to_speech_sync helper


def test_text_to_speech_sync_runs_async_path_under_sync():
    tts_mod = _reload_real_tts()

    class FakeCommunicate:
        def __init__(self, text, voice):
            self.text = text

        async def save(self, _path): ...

    with patch.object(tts_mod, "edge_tts") as fake_edge:
        fake_edge.Communicate = FakeCommunicate
        path = tts_mod.text_to_speech_sync("Hello", voice="en-GB-SoniaNeural")

    assert path.endswith(".mp3")
    if os.path.exists(path):
        os.unlink(path)

"""Integration test: STT -> agent -> TTS round-trip end-to-end (offline).

Generates a synthetic WAV in-memory (no binary fixtures), patches the
external services (faster-whisper / Groq / edge-tts) so the test runs
without network or GPU, and walks the full audio -> text -> diagnosis
-> audio chain through the FastAPI ``TestClient``.

The agent step is conditional on ``app._CHAT_AGENT_AVAILABLE`` — when
langchain isn't importable the ``/agent/query`` endpoint returns 503 and
we skip just that segment, while still verifying that STT and TTS work
end-to-end.
"""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import backend.app as app_module
from backend.app import app


_VALID_REPORT_SHAPE = {
    "grounded_text": "The nozzle plate is showing critical clog.",
    "evidence_citation": "Based on telemetry at 2026-04-25T14:05:02 in run R2",
    "severity_indicator": "CRITICAL",
    "recommended_actions": ["Stop the print", "Replace nozzle plate"],
    "priority_level": "HIGH",
}

_FIXED_TRANSCRIPT = "Why did the nozzle plate fail in run R2"


# ---------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def chat_agent_available() -> bool:
    """Whether the langchain stack imported successfully at app load.

    When False, ``/agent/query`` returns 503 and the agent step is skipped.
    """
    return bool(app_module._CHAT_AGENT_AVAILABLE)


def _synth_wav(target: Path) -> Path:
    """Write a 1-second 440 Hz sine wave at 16 kHz / 16-bit mono PCM.

    Uses only stdlib (``wave`` + ``struct``) so no binary fixture is shipped.
    """
    sample_rate = 16000
    duration_s = 1.0
    freq = 440.0
    amp = 16000  # well below int16 saturation

    n = int(sample_rate * duration_s)
    samples = [int(amp * math.sin(2.0 * math.pi * freq * t / sample_rate)) for t in range(n)]

    with wave.open(str(target), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack("<" + "h" * n, *samples))
    return target


@pytest.fixture
def wav_file(tmp_path: Path) -> Path:
    return _synth_wav(tmp_path / "input.wav")


@pytest.fixture
def fake_mp3(tmp_path: Path) -> Path:
    """A 4-byte 'fake' MP3 stand-in. The /tts/speak endpoint streams the file
    contents back, and that's exactly what the test asserts."""
    mp3 = tmp_path / "tts_output.mp3"
    mp3.write_bytes(b"fake")
    return mp3


# ----------------------------------------------------- pre-flight tests


def test_synthetic_wav_is_valid_riff(wav_file: Path):
    """Sanity: the in-memory WAV we feed to /stt/transcribe is well-formed.

    A bad RIFF header would mean every downstream test is exercising a
    side effect of malformed input rather than the real STT path."""
    assert wav_file.stat().st_size > 0, "WAV file is empty"

    head = wav_file.read_bytes()[:12]
    assert head.startswith(b"RIFF"), f"missing RIFF header: {head!r}"
    assert b"WAVE" in head, f"missing WAVE marker: {head!r}"

    # Confirm that wave.open can re-read it.
    with wave.open(str(wav_file), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000


# ----------------------------------------------------- /stt/transcribe


def test_stt_transcribe_returns_patched_transcript(
    client: TestClient, wav_file: Path,
):
    """POSTing a WAV to /stt/transcribe should call the patched
    ``transcriber.transcribe`` and return its result verbatim."""
    with patch.object(app_module.transcriber, "transcribe",
                      return_value=_FIXED_TRANSCRIPT) as mock_transcribe:
        with wav_file.open("rb") as fh:
            res = client.post(
                "/stt/transcribe",
                files={"file": ("input.wav", fh, "audio/wav")},
            )

    assert res.status_code == 200, res.text
    assert res.json() == {"text": _FIXED_TRANSCRIPT}
    mock_transcribe.assert_called_once()


# ----------------------------------------------------- /tts/speak


def test_tts_speak_streams_back_mocked_mp3_bytes(
    client: TestClient, fake_mp3: Path,
):
    """``speaker.generate_speech`` is async and returns a path; the endpoint
    wraps it in a FileResponse, so the response body must equal the file
    contents byte-for-byte."""
    with patch.object(app_module.speaker, "generate_speech",
                      new_callable=AsyncMock) as mock_speak:
        mock_speak.return_value = str(fake_mp3)
        res = client.post("/tts/speak", json={"text": "hello"})

    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "audio/mpeg"
    assert res.content == b"fake"
    mock_speak.assert_called_once()


# ----------------------------------------------------- /agent/query


def test_agent_query_returns_diagnostic_report_shape(
    client: TestClient, chat_agent_available: bool,
):
    """When langchain is available, the patched graph must yield a
    well-formed AgentResponse. When it's not, the endpoint returns 503 and
    the test is skipped to keep CI green on minimal images."""
    if not chat_agent_available:
        pytest.skip("Chat agent stack unavailable in this environment.")

    with patch.object(app_module, "agent_graph") as mock_graph:
        mock_graph.invoke = MagicMock(return_value={
            "final_report": dict(_VALID_REPORT_SHAPE),
            "messages": [],  # no tool calls in the fake trace
        })
        res = client.post("/agent/query", json={
            "query": _FIXED_TRANSCRIPT,
            "thread_id": "voice-test",
            "run_identifier": "R2",
        })

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["grounded_text"] == _VALID_REPORT_SHAPE["grounded_text"]
    assert body["severity_indicator"] == "CRITICAL"
    assert body["priority_level"] == "HIGH"
    assert body["recommended_actions"] == _VALID_REPORT_SHAPE["recommended_actions"]


# -------------------------------------------- end-to-end chain (STT -> Agent -> TTS)


def test_full_voice_chain_uses_each_step_output_as_next_input(
    client: TestClient, wav_file: Path, fake_mp3: Path,
    chat_agent_available: bool,
):
    """Sequence the three endpoints, threading each response into the next.

    This is the demo's marquee path: operator speaks -> Whisper -> agent ->
    Edge TTS -> reply audio. The test asserts the wiring without booting
    any external service."""
    # 1) STT
    with patch.object(app_module.transcriber, "transcribe",
                      return_value=_FIXED_TRANSCRIPT):
        with wav_file.open("rb") as fh:
            stt_res = client.post(
                "/stt/transcribe",
                files={"file": ("input.wav", fh, "audio/wav")},
            )
    assert stt_res.status_code == 200, stt_res.text
    transcript = stt_res.json()["text"]
    assert transcript == _FIXED_TRANSCRIPT

    # 2) Agent — only when langchain is importable. When not, jump to TTS
    # using a hard-coded fallback message; the chain still demonstrates the
    # voice round-trip.
    if chat_agent_available:
        with patch.object(app_module, "agent_graph") as mock_graph:
            mock_graph.invoke = MagicMock(return_value={
                "final_report": dict(_VALID_REPORT_SHAPE),
                "messages": [],
            })
            agent_res = client.post("/agent/query", json={
                "query": transcript,
                "thread_id": "chain-test",
                "run_identifier": "R2",
            })
        assert agent_res.status_code == 200, agent_res.text
        spoken_text = agent_res.json()["grounded_text"]
        assert spoken_text == _VALID_REPORT_SHAPE["grounded_text"]
    else:
        spoken_text = _VALID_REPORT_SHAPE["grounded_text"]

    # 3) TTS — feed the agent's grounded_text back as audio.
    with patch.object(app_module.speaker, "generate_speech",
                      new_callable=AsyncMock) as mock_speak:
        mock_speak.return_value = str(fake_mp3)
        tts_res = client.post("/tts/speak", json={"text": spoken_text})

    assert tts_res.status_code == 200, tts_res.text
    assert tts_res.content == b"fake"
    # The TTS module must have been called with the agent's text.
    mock_speak.assert_called_once()
    args, _ = mock_speak.call_args
    assert spoken_text in (args or ()), (
        f"speaker.generate_speech called with unexpected args: {args}"
    )

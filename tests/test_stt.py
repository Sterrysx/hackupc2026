import pytest
from backend.voice.stt.transcriber import SpeechToText

def test_stt_import():
    """Test that the SpeechToText class can be imported."""
    assert SpeechToText is not None

# Note: Full transcription tests would require a real audio file and the model downloaded.
# We skip them in basic environment checks.

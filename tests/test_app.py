import pytest
import os
import tempfile
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from backend.app import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body.get("agent_ready"), bool)

@patch("backend.app.transcriber.transcribe")
def test_transcribe_audio(mock_transcribe):
    # Mock the transcription result
    mock_transcribe.return_value = "Hello this is a test transcription."
    
    # Create a dummy audio file content
    file_content = b"dummy audio content"
    files = {"file": ("test.wav", file_content, "audio/wav")}
    
    response = client.post("/stt/transcribe", files=files)
    
    assert response.status_code == 200
    assert response.json() == {"text": "Hello this is a test transcription."}
    mock_transcribe.assert_called_once()

@patch("backend.app.agent_graph.invoke")
def test_query_agent(mock_invoke):
    # Mock the agent graph response with structured data
    mock_invoke.return_value = {
        "final_report": {
            "grounded_text": "The machine is in perfect condition.",
            "evidence_citation": "Based on the telemetry at 2026-04-25T14:00:00 in run R1",
            "severity_indicator": "INFO",
            "recommended_actions": ["Continue operations"],
            "priority_level": "LOW"
        }
    }
    
    payload = {
        "query": "What is the current status?",
        "thread_id": "test-session",
        "run_identifier": "test-run-123"
    }
    
    response = client.post("/agent/query", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["grounded_text"] == "The machine is in perfect condition."
    assert data["priority_level"] == "LOW"
    assert "recommended_actions" in data
    mock_invoke.assert_called_once()

def test_query_agent_minimal_payload():
    with patch("backend.app.agent_graph.invoke") as mock_invoke:
        mock_invoke.return_value = {
            "final_report": {
                "grounded_text": "Basic report.",
                "evidence_citation": "Based on the telemetry at 2026-04-25T14:00:00 in run R1",
                "severity_indicator": "INFO",
                "recommended_actions": ["Action"],
                "priority_level": "LOW"
            }
        }
        
        payload = {"query": "Tell me something."}
        response = client.post("/agent/query", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data["grounded_text"] == "Basic report."
        assert data["priority_level"] == "LOW"

@patch("backend.app.speaker.generate_speech")
def test_tts_speak(mock_generate):
    # Mock the returned path to a dummy file
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp.write(b"dummy mp3 content")
        tmp_path = tmp.name
    
    mock_generate.return_value = tmp_path
    
    payload = {"text": "Hello test", "voice": "en-US-AndrewNeural"}
    response = client.post("/tts/speak", json=payload)
    
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"dummy mp3 content"
    
    # Cleanup
    if os.path.exists(tmp_path):
        os.unlink(tmp_path)

def test_websocket_connection():
    with client.websocket_connect("/ws/notifications") as websocket:
        # Connection should be accepted
        pass

@patch("backend.app.insert_telemetry")
@patch("backend.app.analyze_and_notify")
def test_add_telemetry_triggers_watchdog(mock_analyze, mock_insert):
    mock_insert.return_value = 42
    
    payload = {
        "timestamp": "2026-04-25T17:00:00",
        "run_id": "R3",
        "component": "test_component",
        "health_index": 0.1,
        "status": "FAILED",
        "temperature": 140.0,
        "pressure": 1.0,
        "fan_speed": 0,
        "metrics": {"error": "motor_stall"}
    }
    
    # We use TestClient which handles background tasks synchronously for testing
    response = client.post("/telemetry", json=payload)
    
    assert response.status_code == 200
    assert response.json() == {"id": 42, "message": "Telemetry data added successfully."}
    
    # Verify that the background task was added/triggered
    mock_analyze.assert_called_once()

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from app import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

@patch("app.transcriber.transcribe")
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

@patch("app.agent_graph.invoke")
def test_query_agent(mock_invoke):
    # Mock the agent graph response with structured data
    mock_invoke.return_value = {
        "final_report": {
            "grounded_text": "The machine is in perfect condition.",
            "evidence_citation": "Based on the telemetry at 2026-04-25T14:00:00 in run R1",
            "severity_indicator": "INFO"
        }
    }
    
    payload = {
        "query": "What is the current status?",
        "chat_history": [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello! How can I help you today?"}
        ],
        "run_identifier": "test-run-123"
    }
    
    response = client.post("/agent/query", json=payload)
    
    assert response.status_code == 200
    assert response.json() == {
        "grounded_text": "The machine is in perfect condition.",
        "evidence_citation": "Based on the telemetry at 2026-04-25T14:00:00 in run R1",
        "severity_indicator": "INFO"
    }
    mock_invoke.assert_called_once()

def test_query_agent_minimal_payload():
    with patch("app.agent_graph.invoke") as mock_invoke:
        mock_invoke.return_value = {
            "final_report": {
                "grounded_text": "Basic report.",
                "evidence_citation": "Based on the telemetry at 2026-04-25T14:00:00 in run R1",
                "severity_indicator": "INFO"
            }
        }
        
        payload = {"query": "Tell me something."}
        response = client.post("/agent/query", json=payload)
        
        assert response.status_code == 200
        assert response.json() == {
            "grounded_text": "Basic report.",
            "evidence_citation": "Based on the telemetry at 2026-04-25T14:00:00 in run R1",
            "severity_indicator": "INFO"
        }

@patch("app.insert_telemetry")
def test_add_telemetry(mock_insert):
    mock_insert.return_value = 42
    
    payload = {
        "timestamp": "2026-04-25T17:00:00",
        "run_id": "R3",
        "component": "test_component",
        "health_index": 0.9,
        "status": "FUNCTIONAL",
        "temperature": 40.0,
        "pressure": 1.0,
        "fan_speed": 2500,
        "metrics": {"some_key": "some_value"}
    }
    
    response = client.post("/telemetry", json=payload)
    
    assert response.status_code == 200
    assert response.json() == {"id": 42, "message": "Telemetry data added successfully."}
    mock_insert.assert_called_once()

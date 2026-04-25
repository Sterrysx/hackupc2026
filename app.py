import os
import shutil
import tempfile
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from fastapi.responses import FileResponse
import base64

from stt.transcriber import SpeechToText
from tts.speaker import TextToSpeech
from Ai_Agent.graph import build_graph
from Ai_Agent.db import insert_telemetry, init_db

app = FastAPI(title="Digital Twin AI API")

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            await connection.send_json(message)

manager = ConnectionManager()

# Initialize components
transcriber = SpeechToText()
speaker = TextToSpeech()
agent_graph = build_graph()

# Initialize DB
init_db()

# --- Pydantic Schemas ---

class TranscribeResponse(BaseModel):
    text: str

class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None

class Message(BaseModel):
    role: str # "user" or "assistant"
    content: str

class AgentRequest(BaseModel):
    query: str
    thread_id: Optional[str] = "default-thread"
    run_identifier: Optional[str] = ""

class AgentResponse(BaseModel):
    grounded_text: str
    evidence_citation: str
    severity_indicator: str
    recommended_actions: List[str]
    priority_level: str

class TelemetryData(BaseModel):
    timestamp: str
    run_id: str
    component: str
    health_index: float
    status: str
    temperature: float
    pressure: float
    fan_speed: float
    metrics: dict

class TelemetryResponse(BaseModel):
    id: int
    message: str

async def analyze_and_notify(data: TelemetryData):
    """
    Background task to analyze a critical telemetry reading and notify all connected clients.
    """
    try:
        query = (
            f"ALERT: Component '{data.component}' reported status '{data.status}' "
            f"(Health: {data.health_index}) in run {data.run_id}. "
            "Please provide an immediate diagnostic report, including root cause and recommended actions."
        )
        
        # Use a unique thread ID for each autonomous alert to avoid context pollution,
        # or use a fixed one like "watchdog-alerts" to keep a history of alerts.
        config = {"configurable": {"thread_id": f"alert-{data.run_id}-{data.component}"}}
        
        initial_state = {
            "messages": [HumanMessage(content=query)],
            "run_identifier": data.run_id,
            "retrieved_telemetry": "",
            "final_report": "",
            "validation_attempts": 0,
        }
        
        result = agent_graph.invoke(initial_state, config=config)
        report = result.get("final_report")
        
        if report:
            await manager.broadcast({
                "type": "PROACTIVE_ALERT",
                "component": data.component,
                "status": data.status,
                "report": report
            })
    except Exception as e:
        print(f"Watchdog analysis failed: {e}")

# --- Endpoints ---

@app.websocket("/ws/notifications")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection open
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.post("/tts/speak")
async def speak_text(request: TTSRequest):
    """
    Endpoint to convert text to speech and return an MP3 file.
    """
    try:
        if request.voice:
            speaker.voice = request.voice
        
        path = await speaker.generate_speech(request.text)
        return FileResponse(path, media_type="audio/mpeg", filename="speech.mp3")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS failed: {str(e)}")

@app.post("/telemetry", response_model=TelemetryResponse)
async def add_telemetry(data: TelemetryData, background_tasks: BackgroundTasks):
    """
    Endpoint to add new telemetry data to the historian database.
    Triggers a proactive AI alert if status is CRITICAL or FAILED.
    """
    try:
        last_id = insert_telemetry(
            timestamp=data.timestamp,
            run_id=data.run_id,
            component=data.component,
            health_index=data.health_index,
            status=data.status,
            temperature=data.temperature,
            pressure=data.pressure,
            fan_speed=data.fan_speed,
            metrics=data.metrics
        )
        
        # Proactive Monitoring (Watchdog)
        if data.status.upper() in ["CRITICAL", "FAILED"]:
            background_tasks.add_task(analyze_and_notify, data)
            
        return TelemetryResponse(id=last_id, message="Telemetry data added successfully.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add telemetry: {str(e)}")

@app.post("/stt/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(file: UploadFile = File(...)):
    """
    Endpoint to transcribe an uploaded audio file using Faster Whisper.
    """
    if not file.content_type.startswith("audio/"):
        # Some clients might not set content_type correctly, but it's a good check if they do.
        pass

    try:
        # Save uploaded file to a temporary location
        suffix = os.path.splitext(file.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            shutil.copyfileobj(file.file, tmp_file)
            tmp_path = tmp_file.name

        # Transcribe
        text = transcriber.transcribe(tmp_path)
        
        # Cleanup
        os.unlink(tmp_path)
        
        return TranscribeResponse(text=text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")

@app.post("/agent/query", response_model=AgentResponse)
async def query_agent(request: AgentRequest):
    """
    Endpoint to trigger the AI Agent workflow with persistent memory.
    """
    try:
        config = {"configurable": {"thread_id": request.thread_id}}
        
        initial_state = {
            "messages": [HumanMessage(content=request.query)],
            "run_identifier": request.run_identifier or "",
            "retrieved_telemetry": "",
            "final_report": "",
            "validation_attempts": 0,
        }

        # Invoke the graph with thread configuration
        result = agent_graph.invoke(initial_state, config=config)
        
        final_report = result.get("final_report")
        if not final_report:
             raise HTTPException(status_code=500, detail="No report generated.")
        
        return final_report
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent workflow failed: {str(e)}")

@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

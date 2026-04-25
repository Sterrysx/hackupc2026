import os
import shutil
import tempfile
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from stt.transcriber import SpeechToText
from Ai_Agent.graph import build_graph
from Ai_Agent.db import insert_telemetry, init_db

app = FastAPI(title="Digital Twin AI API")

# CORS — lets the Vite dev server (and preview) call this API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    # Vite con `host: true`: el front suele abrirse como http://192.168.x.x:5173 — sin esto el navegador bloquea el fetch a :8000.
    allow_origin_regex=r"https?://(192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
transcriber = SpeechToText()
agent_graph = build_graph()

# Initialize DB
init_db()

# --- Pydantic Schemas ---

class TranscribeResponse(BaseModel):
    text: str

class Message(BaseModel):
    role: str # "user" or "assistant"
    content: str

class AgentRequest(BaseModel):
    query: str
    chat_history: Optional[List[Message]] = []
    run_identifier: Optional[str] = ""

class AgentResponse(BaseModel):
    final_report: str
    # You can add more fields if needed, like the updated history

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

# --- Endpoints ---

@app.get("/")
async def root():
    """Unified entry — FastAPI serves the AI/telemetry API; frontend runs via Vite (or static in prod)."""
    return {
        "service": "hackupc2026 Digital Twin API",
        "docs": "/docs",
        "health": "/health",
        "note": "Agent answers require GROQ_API_KEY in .env (see .env.example). Frontend: cd frontend && npm run dev",
    }


@app.post("/telemetry", response_model=TelemetryResponse)
async def add_telemetry(data: TelemetryData):
    """
    Endpoint to add new telemetry data to the historian database.
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
    Endpoint to trigger the AI Agent workflow.
    """
    try:
        # Convert Pydantic messages to LangChain messages if history is provided
        messages = []
        if request.chat_history:
            for msg in request.chat_history:
                if msg.role == "user":
                    messages.append(HumanMessage(content=msg.content))
                else:
                    messages.append(AIMessage(content=msg.content))
        
        # Add the current query
        messages.append(HumanMessage(content=request.query))

        initial_state = {
            "messages": messages,
            "run_identifier": request.run_identifier or "",
            "retrieved_telemetry": "",
            "final_report": "",
            "validation_attempts": 0,
        }

        # Invoke the graph
        result = agent_graph.invoke(initial_state)
        
        return AgentResponse(
            final_report=result.get("final_report", "No report generated.")
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent workflow failed: {str(e)}")

@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

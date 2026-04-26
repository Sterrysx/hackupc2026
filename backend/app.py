import os
import shutil
import tempfile
from typing import List, Optional
from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    BackgroundTasks,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
import base64
import logging

from backend.voice.stt.transcriber import SpeechToText
from backend.voice.tts.speaker import TextToSpeech
from backend.agent.db import insert_telemetry, init_db
from backend.agent.trace import build_reasoning_trace
from backend.agent import twin_data, forecast, predictions

# Chat-agent stack imports the langchain/langgraph stack, which currently
# pulls in ``langchain_protocol`` — a transitive dep that may not be
# installed in every environment. Make this optional so /twin/* endpoints
# (the dashboard data path) keep serving even when the chat agent is
# unavailable. The /agent/* endpoints will return 503 instead of 200 in
# that case.
logger = logging.getLogger(__name__)
try:
    from langchain_core.messages import HumanMessage, AIMessage, BaseMessage  # type: ignore
    from backend.agent.graph import build_graph  # type: ignore
    _CHAT_AGENT_AVAILABLE = True
    _CHAT_AGENT_IMPORT_ERROR = None
except Exception as _exc:  # broad: ImportError, attribute errors from broken deps
    HumanMessage = AIMessage = BaseMessage = None  # type: ignore
    build_graph = None  # type: ignore
    _CHAT_AGENT_AVAILABLE = False
    _CHAT_AGENT_IMPORT_ERROR = str(_exc)
    logger.warning(
        "Chat agent stack failed to import (%s). /agent/* endpoints will return 503; "
        "/twin/* endpoints still work.",
        _exc,
    )

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


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        stale: List[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                stale.append(connection)
        for connection in stale:
            self.disconnect(connection)


manager = ConnectionManager()

# Initialize components
transcriber = SpeechToText()
speaker = TextToSpeech()
agent_graph = build_graph() if _CHAT_AGENT_AVAILABLE and build_graph is not None else None

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

class ReasoningStep(BaseModel):
    """A single line in the LangGraph / tool trace (for UI transparency)."""
    kind: str
    label: str
    content: str


class AgentResponse(BaseModel):
    grounded_text: str
    evidence_citation: str
    severity_indicator: str
    recommended_actions: List[str]
    priority_level: str
    reasoning_trace: List[ReasoningStep] = []

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
    if not _CHAT_AGENT_AVAILABLE or agent_graph is None:
        logger.warning("analyze_and_notify skipped — chat agent unavailable: %s", _CHAT_AGENT_IMPORT_ERROR)
        return
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
        
        result = await run_in_threadpool(agent_graph.invoke, initial_state, config=config)
        report = result.get("final_report")
        trace = build_reasoning_trace(result)

        if report:
            if isinstance(report, dict):
                payload: dict = {**report, "reasoning_trace": trace}
            else:
                p = report.model_dump() if hasattr(report, "model_dump") else {}
                payload = {**p, "reasoning_trace": trace}
            await manager.broadcast(
                {
                    "type": "PROACTIVE_ALERT",
                    "component": data.component,
                    "status": data.status,
                    "report": payload,
                }
            )
    except Exception as e:
        print(f"Watchdog analysis failed: {e}")

# --- Endpoints ---


@app.get("/")
async def root():
    """Unified entry — FastAPI serves the AI/telemetry API; frontend runs via Vite (or static in prod)."""
    return {
        "service": "hackupc2026 Digital Twin API",
        "docs": "/docs",
        "health": "/health",
        "note": "Agent answers require GITHUB_TOKEN (preferred), GEMINI_API_KEY, or GROQ_API_KEY in .env (see .env.example). Frontend: cd frontend && npm run dev",
    }


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
    Transcribe an uploaded audio file using Faster Whisper.

    Browser MediaRecorder uploads usually arrive as `audio/webm;codecs=opus`
    or `audio/ogg;codecs=opus`. We do not enforce the MIME because curl /
    test clients sometimes omit it; we DO normalise the temp-file extension
    so PyAV / ffmpeg can demux it correctly.
    """
    tmp_path = None
    try:
        filename = file.filename or "upload.webm"
        suffix = os.path.splitext(filename)[1] or ".webm"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            shutil.copyfileobj(file.file, tmp_file)
            tmp_path = tmp_file.name

        text = transcriber.transcribe(tmp_path)
        return TranscribeResponse(text=text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

@app.post("/agent/query", response_model=AgentResponse)
async def query_agent(request: AgentRequest):
    """
    Endpoint to trigger the AI Agent workflow with persistent memory.
    """
    if not _CHAT_AGENT_AVAILABLE or agent_graph is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Chat agent unavailable in this environment "
                f"(import failed: {_CHAT_AGENT_IMPORT_ERROR}). "
                "Twin endpoints remain functional; install missing langchain deps to enable chat."
            ),
        )
    try:
        config = {"configurable": {"thread_id": request.thread_id}}
        
        initial_state = {
            "messages": [HumanMessage(content=request.query)],
            "run_identifier": request.run_identifier or "",
            "retrieved_telemetry": "",
            "final_report": "",
            "validation_attempts": 0,
        }

        # Run the blocking LangGraph call in a worker thread to keep the event loop responsive.
        result = await run_in_threadpool(agent_graph.invoke, initial_state, config=config)

        final_report = result.get("final_report")
        if not final_report:
            raise HTTPException(status_code=500, detail="No report generated.")

        if isinstance(final_report, dict):
            data = final_report
        else:
            data = final_report.model_dump() if hasattr(final_report, "model_dump") else {}

        trace = build_reasoning_trace(result)
        return AgentResponse(
            grounded_text=data.get("grounded_text", "") or "",
            evidence_citation=data.get("evidence_citation", "") or "",
            severity_indicator=str(data.get("severity_indicator", "INFO") or "INFO"),
            recommended_actions=list(data.get("recommended_actions", []) or []),
            priority_level=str(data.get("priority_level", "LOW") or "LOW"),
            reasoning_trace=[ReasoningStep(**s) for s in trace],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent workflow failed: {str(e)}")

@app.get("/health")
async def health_check():
    # The API can be up while the LLM backend is not configured.
    return {
        "status": "ok",
        "agent_ready": bool(
            os.getenv("GITHUB_TOKEN")
            or os.getenv("GITHUB_PAT")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("GROQ_API_KEY")
        ),
    }


# ---------------------------------------------------------------- /twin/* —
# Stage 1 timeline accessors. Read-only views over `data/fleet_baseline.parquet`
# shaped to match the React store's `SystemSnapshot` contract.

@app.get("/twin/cities")
async def twin_cities():
    return {"cities": twin_data.list_cities()}


@app.get("/twin/printers")
async def twin_printers(city: str):
    try:
        return {"city": city, "printers": twin_data.list_printers(city)}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/twin/snapshot")
async def twin_snapshot(city: str, printer_id: int, day: int):
    try:
        return twin_data.get_snapshot(city, printer_id, day)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/twin/timeline")
async def twin_timeline(
    city: str,
    printer_id: int,
    fields: str,
    day_from: Optional[int] = None,
    day_to: Optional[int] = None,
):
    """`fields` is a comma-separated list of parquet column names."""
    requested = [f.strip() for f in fields.split(",") if f.strip()]
    if not requested:
        raise HTTPException(status_code=400, detail="fields must be non-empty")
    try:
        return twin_data.get_timeline(
            city, printer_id, requested,
            day_from=day_from, day_to=day_to,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/twin/predictions/timeline")
async def twin_predictions_timeline(
    city: str,
    printer_id: int,
    fields: str,
    day_from: Optional[int] = None,
    day_to: Optional[int] = None,
):
    """Per-day predicted trajectory from `data/prediction/fleet_2026_2035.parquet`.

    Same shape as `/twin/timeline` but reads the forward-projected prediction
    fleet. Use for analytics tiles that animate the model's prediction as the
    operator scrubs through time.
    """
    requested = [f.strip() for f in fields.split(",") if f.strip()]
    if not requested:
        raise HTTPException(status_code=400, detail="fields must be non-empty")
    try:
        return predictions.get_timeline(
            city, printer_id, requested,
            day_from=day_from, day_to=day_to,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/twin/predictions/cities")
async def twin_predictions_cities():
    return {"cities": predictions.list_cities()}


@app.get("/twin/predictions/printers")
async def twin_predictions_printers(city: str):
    try:
        return {"city": city, "printers": predictions.list_printers(city)}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/twin/state")
async def twin_state(
    city: str,
    printer_id: int,
    day: int,
    horizon_d: float = twin_data.DEFAULT_FORECAST_HORIZON_D,
):
    """Combined snapshot + Stage 2 forecast — single round-trip per UI tick.

    Forecasts use the analytic projection by default (per-day hazard times
    horizon). When `ml_models/02_ssl/models/rul_head_ssl.pt` appears, the
    forecast module switches automatically — no API change required.
    """
    try:
        snap = twin_data.get_snapshot(
            city, printer_id, day,
            forecast_horizon_d=horizon_d,
        )
        snap["forecasts"] = forecast.compute_forecasts(
            city, printer_id, day, horizon_d=horizon_d,
        )
        return snap
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/twin/model_status")
async def twin_model_status():
    """Tells the UI whether forecasts are coming from the trained SSL+RUL
    head (`active_path == "ssl"`) or the analytic fallback."""
    return {
        "active_path": forecast.active_path(),
        "rul_head_present": bool(forecast._has_rul_head()),
    }


@app.get("/twin/forecast")
async def twin_forecast(
    city: str,
    printer_id: int,
    day: int,
    horizon_d: float = twin_data.DEFAULT_FORECAST_HORIZON_D,
):
    try:
        return {
            "horizonDays": horizon_d,
            "forecasts": forecast.compute_forecasts(
                city, printer_id, day, horizon_d=horizon_d,
            ),
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

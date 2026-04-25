import os
import shutil
import tempfile
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from stt.transcriber import SpeechToText
from Ai_Agent.graph import build_graph

app = FastAPI(title="Digital Twin AI API")

# Initialize components
transcriber = SpeechToText()
agent_graph = build_graph()

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

# --- Endpoints ---

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

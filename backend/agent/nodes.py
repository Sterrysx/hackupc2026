import json
import re
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

from .config import get_llm
from .prompts import GATHERER_SYSTEM_PROMPT, SYNTHESIZER_SYSTEM_PROMPT
from .state import GraphState
from .tools import query_database, get_existing_runs, think
from .schemas import DiagnosticReport

GATHERER_TOOLS = [think, get_existing_runs, query_database]
SYNTHESIZER_TOOLS = [think]

MAX_VALIDATION_ATTEMPTS = 3

_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_RUN_ID_RE = re.compile(r"run_id:\s*\w+|run\s+\w+")


def gatherer_node(state: GraphState) -> dict:
    llm = get_llm()
    llm_with_tools = llm.bind_tools(GATHERER_TOOLS)
    messages = [SystemMessage(content=GATHERER_SYSTEM_PROMPT)] + state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


def extract_telemetry(state: GraphState) -> dict:
    for msg in reversed(state["messages"]):
        if isinstance(msg, ToolMessage) and msg.content:
            return {"retrieved_telemetry": msg.content}
    return {"retrieved_telemetry": "No telemetry data retrieved."}


def synthesizer_node(state: GraphState) -> dict:
    llm = get_llm()
    # Use structured output for the final response
    llm_with_structured_output = llm.with_structured_output(DiagnosticReport)
    llm_with_tools = llm.bind_tools(SYNTHESIZER_TOOLS)
    
    telemetry = state.get("retrieved_telemetry", "No telemetry available.")
    if isinstance(telemetry, dict):
        telemetry = json.dumps(telemetry, indent=2)
    system_prompt = SYNTHESIZER_SYSTEM_PROMPT.format(retrieved_telemetry=telemetry)
    messages = [SystemMessage(content=system_prompt)] + list(state["messages"])

    # First, allow the LLM to use the think tool
    while True:
        try:
            response = llm_with_tools.invoke(messages)
        except Exception as e:
            err = str(e)
            # Some providers may still emit an out-of-schema tool call.
            # Fallback to direct structured output instead of failing the request.
            if "tool call validation failed" in err and "not in request.tools" in err:
                structured_response = llm_with_structured_output.invoke(messages)
                return {"final_report": structured_response}
            raise
        messages.append(response)
        tool_calls = getattr(response, "tool_calls", None)
        if not tool_calls:
            # If no more tool calls, we need the structured output
            # We call the LLM again but this time forcing structured output
            structured_response = llm_with_structured_output.invoke(messages)
            return {"final_report": structured_response}
        
        for tc in tool_calls:
            messages.append(ToolMessage(content="", tool_call_id=tc["id"]))


def guardrail_node(state: GraphState) -> dict:
    report = state.get("final_report")
    if not report and state.get("messages"):
        # Backward-compat: support old state shapes that placed structured output in messages.
        report = state["messages"][-1]

    if not isinstance(report, DiagnosticReport):
        # If it's not a DiagnosticReport, it might be a dict
        if isinstance(report, dict):
            try:
                report = DiagnosticReport(**report)
            except:
                pass
        elif hasattr(report, "content") and not report.content:
             # Check for tool_calls parsed data in some langchain versions
             pass

    attempts = state.get("validation_attempts", 0)
    
    errors = []
    if not isinstance(report, DiagnosticReport):
        errors.append("Output is not in the required structured format (DiagnosticReport).")
    else:
        if report.severity_indicator not in ["INFO", "WARNING", "CRITICAL"]:
            errors.append("severity_indicator must be INFO, WARNING, or CRITICAL.")
        
        if report.priority_level not in ["LOW", "MEDIUM", "HIGH"]:
            errors.append("priority_level must be LOW, MEDIUM, or HIGH.")
            
        if not report.recommended_actions or len(report.recommended_actions) < 1:
            errors.append("At least one recommended_action must be provided.")
        
        has_timestamp = bool(_TIMESTAMP_RE.search(report.evidence_citation))
        has_run_id = bool(_RUN_ID_RE.search(report.evidence_citation.lower()))
        
        if not has_timestamp:
            errors.append("evidence_citation must include a timestamp (YYYY-MM-DDTHH:MM:SS).")
        if not has_run_id:
            errors.append("evidence_citation must include a run identifier (e.g., 'run R1').")

    if not errors:
        # Store the report as a dict for serialization in GraphState if needed, 
        # but final_report expects a dict or object that app.py can handle.
        return {"final_report": report.model_dump() if isinstance(report, DiagnosticReport) else report, "validation_attempts": attempts}

    new_attempts = attempts + 1
    if new_attempts >= MAX_VALIDATION_ATTEMPTS:
        fallback = {
            "severity_indicator": "CRITICAL",
            "grounded_text": f"Validation failed after {MAX_VALIDATION_ATTEMPTS} attempts.",
            "evidence_citation": f"Errors: {'; '.join(errors)}"
        }
        return {"final_report": fallback, "validation_attempts": new_attempts}

    correction = HumanMessage(content=(
        f"Report failed validation (attempt {new_attempts}/{MAX_VALIDATION_ATTEMPTS}). "
        f"Fix the following errors in the structured output: {'; '.join(errors)}. "
        "Ensure evidence_citation includes both timestamp and run_id."
    ))
    # Clear final_report so routing loops back to synthesizer instead of ending.
    return {"messages": [correction], "validation_attempts": new_attempts, "final_report": ""}

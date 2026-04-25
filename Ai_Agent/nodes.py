import json
import re
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

from .config import get_llm
from .prompts import GATHERER_SYSTEM_PROMPT, SYNTHESIZER_SYSTEM_PROMPT
from .state import GraphState
from .tools import query_database, get_db_schema, think

GATHERER_TOOLS = [think, get_db_schema, query_database]
SYNTHESIZER_TOOLS = [think]

MAX_VALIDATION_ATTEMPTS = 3

_SEVERITY_RE = re.compile(r"\[(INFO|WARNING|CRITICAL)\]")
_TIMESTAMP_RE = re.compile(r"timestamp:\s*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_RUN_ID_RE = re.compile(r"run_id:\s*\w+")


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
    llm_with_tools = llm.bind_tools(SYNTHESIZER_TOOLS)
    telemetry = state.get("retrieved_telemetry", "No telemetry available.")
    if isinstance(telemetry, dict):
        telemetry = json.dumps(telemetry, indent=2)
    system_prompt = SYNTHESIZER_SYSTEM_PROMPT.format(retrieved_telemetry=telemetry)
    messages = [SystemMessage(content=system_prompt)] + list(state["messages"])

    while True:
        response = llm_with_tools.invoke(messages)
        messages.append(response)
        tool_calls = getattr(response, "tool_calls", None)
        if not tool_calls:
            break
        for tc in tool_calls:
            messages.append(ToolMessage(content="", tool_call_id=tc["id"]))

    return {"messages": [response]}


def guardrail_node(state: GraphState) -> dict:
    last_msg = state["messages"][-1]
    content = last_msg.content if hasattr(last_msg, "content") else ""
    attempts = state.get("validation_attempts", 0)

    has_severity = bool(_SEVERITY_RE.search(content))
    has_citation = bool(_TIMESTAMP_RE.search(content)) or bool(_RUN_ID_RE.search(content))

    errors = []
    if not has_severity:
        errors.append("Missing severity indicator ([INFO], [WARNING], or [CRITICAL])")
    if not has_citation:
        errors.append("Missing evidence citation (must include 'timestamp: YYYY-MM-DDTHH:MM:SS' and/or 'run_id: <id>')")

    if not errors:
        return {"final_report": content, "validation_attempts": attempts}

    new_attempts = attempts + 1
    if new_attempts >= MAX_VALIDATION_ATTEMPTS:
        fallback = (
            "[CRITICAL]\n\n"
            f"Validation failed after {MAX_VALIDATION_ATTEMPTS} attempts. "
            "Please review raw telemetry data manually.\n\n"
            f"Errors: {'; '.join(errors)}"
        )
        return {"final_report": fallback, "validation_attempts": new_attempts}

    correction = HumanMessage(content=(
        f"Report failed validation (attempt {new_attempts}/{MAX_VALIDATION_ATTEMPTS}). "
        f"Fix: {'; '.join(errors)}. "
        "Start with a severity tag like [CRITICAL] on its own line, "
        "then cite specific timestamps and run IDs from the telemetry data."
    ))
    return {"messages": [correction], "validation_attempts": new_attempts}

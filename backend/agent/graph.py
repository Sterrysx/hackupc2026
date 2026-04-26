from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

from .state import GraphState
from .nodes import (
    gatherer_node,
    extract_telemetry,
    synthesizer_node,
    guardrail_node,
    MAX_VALIDATION_ATTEMPTS,
)
from .nodes import GATHERER_TOOLS


def _route_after_gatherer(state: GraphState) -> str:
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return "extract_telemetry"


def _route_after_guardrail(state: GraphState) -> str:
    if state.get("final_report"):
        return END
    if state.get("validation_attempts", 0) >= MAX_VALIDATION_ATTEMPTS:
        return END
    return "synthesizer"


def build_graph():
    tool_node = ToolNode(GATHERER_TOOLS)

    graph = StateGraph(GraphState)

    graph.add_node("gatherer", gatherer_node)
    graph.add_node("tools", tool_node)
    graph.add_node("extract_telemetry", extract_telemetry)
    graph.add_node("synthesizer", synthesizer_node)
    graph.add_node("guardrail", guardrail_node)

    graph.add_edge(START, "gatherer")
    graph.add_conditional_edges("gatherer", _route_after_gatherer, {
        "tools": "tools",
        "extract_telemetry": "extract_telemetry",
    })
    graph.add_edge("tools", "gatherer")
    graph.add_edge("extract_telemetry", "synthesizer")
    graph.add_edge("synthesizer", "guardrail")
    graph.add_conditional_edges("guardrail", _route_after_guardrail, {
        END: END,
        "synthesizer": "synthesizer",
    })

    return graph.compile(checkpointer=MemorySaver())

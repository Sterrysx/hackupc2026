from typing import Annotated, TypedDict
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class GraphState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    run_identifier: str
    retrieved_telemetry: dict | str
    final_report: dict | str
    validation_attempts: int

"""
Serialize LangGraph final state into a UI-friendly reasoning trace.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

_MAX_DEFAULT = 3000
_MAX_TOOL = 12000
_MAX_SYS = 500


def _clip(text: str, n: int) -> str:
    t = text.strip() if text else ""
    if len(t) <= n:
        return t
    return t[:n] + "…"


def _content_preview(msg: Any) -> str:
    c = getattr(msg, "content", None)
    if c is None:
        if hasattr(msg, "model_dump"):
            try:
                return _clip(json.dumps(msg.model_dump(), indent=2, default=str), 4000)
            except Exception:
                return str(msg)
        return str(msg)
    if isinstance(c, str):
        return c
    return _clip(json.dumps(c, default=str) if not isinstance(c, str) else c, 4000)


def _serialize_messages(messages: list[BaseMessage] | list[Any] | None) -> list[dict[str, str]]:
    if not messages:
        return []
    out: list[dict[str, str]] = []
    for i, msg in enumerate(messages):
        if isinstance(msg, SystemMessage):
            c = (msg.content or "") if isinstance(msg.content, str) else str(msg.content)
            out.append(
                {
                    "kind": "system",
                    "label": f"System · {i + 1}",
                    "content": _clip(c, _MAX_SYS) or "(system prompt)",
                }
            )
        elif isinstance(msg, HumanMessage):
            h = (msg.content or "") if isinstance(msg.content, str) else json.dumps(msg.content, default=str)
            out.append({"kind": "user", "label": "User / feedback", "content": _clip(h, 2500)})
        elif isinstance(msg, AIMessage):
            body = (msg.content or "").strip()
            tcs = getattr(msg, "tool_calls", None) or []
            if not body and tcs:
                body = f"Requesting {len(tcs)} tool call(s)…"
            elif not body:
                body = "(no assistant text)"
            out.append(
                {
                    "kind": "assistant",
                    "label": "Model",
                    "content": _clip(body, _MAX_DEFAULT),
                }
            )
            for tc in tcs:
                if isinstance(tc, dict):
                    name = tc.get("name", "tool")
                    args = tc.get("args", {})
                else:
                    name = getattr(tc, "name", "tool")
                    args = getattr(tc, "args", {}) or {}
                a_str = _clip(
                    json.dumps(args, default=str) if not isinstance(args, str) else args,
                    2000,
                )
                out.append(
                    {
                        "kind": "tool_call",
                        "label": f"Call · {name}",
                        "content": a_str,
                    }
                )
        elif isinstance(msg, ToolMessage):
            name = msg.name or "tool"
            content = (msg.content or "") if isinstance(msg.content, str) else str(msg.content)
            out.append(
                {
                    "kind": "tool_result",
                    "label": f"Result · {name}",
                    "content": _clip(content, _MAX_TOOL),
                }
            )
        else:
            # e.g. DiagnosticReport placed directly in messages by synthesizer
            label = type(msg).__name__
            if hasattr(msg, "model_dump"):
                try:
                    d = msg.model_dump()
                    out.append(
                        {
                            "kind": "structured",
                            "label": f"Draft report · {label}",
                            "content": _clip(json.dumps(d, indent=2, default=str), 3500),
                        }
                    )
                except Exception:
                    out.append(
                        {
                            "kind": "other",
                            "label": label,
                            "content": _clip(str(msg), 2000),
                        }
                    )
            else:
                out.append(
                    {
                        "kind": "other",
                        "label": label,
                        "content": _clip(_content_preview(msg), 2000),
                    }
                )
    return out


def build_reasoning_trace(result: dict[str, Any]) -> list[dict[str, str]]:
    """Turn graph invoke result into ordered steps for the API / UI."""
    steps: list[dict[str, str]] = []
    raw_msgs = result.get("messages")
    if isinstance(raw_msgs, list) and raw_msgs:
        try:
            steps.extend(_serialize_messages(raw_msgs))
        except Exception as exc:
            steps.append(
                {
                    "kind": "error",
                    "label": "Trace",
                    "content": f"Could not fully serialize message history: {exc}",
                }
            )

    tel = result.get("retrieved_telemetry", "")
    if tel and str(tel).strip():
        if isinstance(tel, (dict, list)):
            tel_s = json.dumps(tel, indent=2, default=str)
        else:
            tel_s = str(tel)
        # Insert after gather phase contextually: show as the bundle fed to synthesis
        rec = {
            "kind": "retrieval",
            "label": "Telemetry bundle (synthesizer input)",
            "content": _clip(tel_s, 5000),
        }
        if steps:
            # Place after the first system block (gatherer prompt) is noisy — prepend as overview
            steps.insert(0, rec)
        else:
            steps.append(rec)

    va = int(result.get("validation_attempts") or 0)
    if va > 0:
        steps.append(
            {
                "kind": "meta",
                "label": "Validation",
                "content": f"Guardrail validation attempts: {va}",
            }
        )
    return steps

"""Integration test: real LangGraph agent grounded in the real historian.

This is a LIVE test — it builds the actual LangGraph via
``Ai_Agent.graph.build_graph()`` and submits a question to the real Groq
LLM. The whole module is skipped cleanly when ``GROQ_API_KEY`` is unset
so the default offline ``uv run pytest`` invocation stays green.

Asserts the "no hallucinations" demo contract:
- the returned ``final_report`` carries every required ``DiagnosticReport`` field;
- ``evidence_citation`` includes an ISO-8601 timestamp + a run reference;
- ``recommended_actions`` is non-empty;
- only canonical component names appear in ``grounded_text``.

Inspired by ``tests/test_integration_e2e.py`` but exercises the graph
directly (no FastAPI/TestClient layer).
"""
from __future__ import annotations

import os
import re
import uuid

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.getenv("GROQ_API_KEY"),
        reason="GROQ_API_KEY not set — live agent grounding tests need real LLM access.",
    ),
]

# These imports require the langchain stack; importing them at module scope
# is fine because the live skipif above will short-circuit collection
# rather than execution when the key is missing.
# But the langchain imports are heavy, so place them inside the fixture so
# offline `pytest --collect-only` stays fast.

_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_RUN_ID_RE = re.compile(r"run_id:\s*\w+|run\s+\w+", re.IGNORECASE)

# Canonical frontend component names — the agent should never invent any
# other "component_xxx" identifiers.
_VALID_COMPONENT_NAMES = {
    "recoater_blade",
    "recoater_motor",
    "nozzle_plate",
    "thermal_resistor",
    "heating_element",
    "insulation_panel",
}

# Forbidden patterns: the agent must not invent components like
# ``component_xyz``, ``part_42``, etc. The legitimate components above are
# whitelisted explicitly below.
_HALLUCINATED_PART_RE = re.compile(r"\b(component|part|module)_\w+\b", re.IGNORECASE)


@pytest.fixture(scope="module")
def compiled_graph():
    """Build the real graph once per module.

    Importing langchain/langgraph here (inside the fixture) avoids paying
    that cost during ``pytest --collect-only`` on offline runs.
    """
    from Ai_Agent.graph import build_graph
    return build_graph()


def _invoke_graph(graph, query: str, *, run_identifier: str = "R1") -> dict:
    from langchain_core.messages import HumanMessage

    initial_state = {
        "messages": [HumanMessage(content=query)],
        "run_identifier": run_identifier,
        "retrieved_telemetry": "",
        "final_report": "",
        "validation_attempts": 0,
    }
    config = {"configurable": {"thread_id": f"int-{uuid.uuid4()}"}}
    return graph.invoke(initial_state, config=config)


def _final_report_dict(result) -> dict:
    """Normalise final_report to a dict (graph may emit dict or DiagnosticReport)."""
    fr = result.get("final_report")
    assert fr, "agent returned no final_report"
    if isinstance(fr, dict):
        return fr
    assert hasattr(fr, "model_dump"), f"final_report shape unrecognised: {type(fr)}"
    return fr.model_dump()


def test_agent_returns_full_diagnostic_report_for_run_r1(compiled_graph):
    """The DiagnosticReport contract: all four scalar fields plus a list of
    actions must come back populated for a typical "what happened in R1"
    question."""
    result = _invoke_graph(
        compiled_graph,
        "Why did the nozzle plate degrade in run R1? Cite the exact telemetry.",
        run_identifier="R1",
    )
    report = _final_report_dict(result)

    for key in ("grounded_text", "evidence_citation", "severity_indicator",
                "recommended_actions", "priority_level"):
        assert key in report, f"final_report missing {key!r}: {report}"

    assert report["severity_indicator"] in {"INFO", "WARNING", "CRITICAL"}
    assert report["priority_level"] in {"LOW", "MEDIUM", "HIGH"}


def test_agent_evidence_citation_contains_timestamp_and_run_reference(compiled_graph):
    """The "no hallucinations" guardrail: every citation must reference an
    ISO timestamp + a run identifier. Same regex the runtime guardrail
    enforces (see ``Ai_Agent.nodes.guardrail_node``)."""
    result = _invoke_graph(
        compiled_graph,
        "Tell me what was happening with the heating element in run R1.",
        run_identifier="R1",
    )
    report = _final_report_dict(result)

    citation = report["evidence_citation"]
    assert citation, "evidence_citation must not be empty"
    assert _TIMESTAMP_RE.search(citation), (
        f"evidence_citation missing ISO timestamp: {citation!r}"
    )
    assert _RUN_ID_RE.search(citation), (
        f"evidence_citation missing run identifier: {citation!r}"
    )


def test_agent_grounded_text_and_actions_are_non_empty(compiled_graph):
    """The agent must never deflect with an empty answer — there's always
    *something* in the historian to talk about for R1."""
    result = _invoke_graph(
        compiled_graph,
        "Summarise the incident in run R1 and recommend remediation steps.",
        run_identifier="R1",
    )
    report = _final_report_dict(result)

    assert isinstance(report["grounded_text"], str)
    assert report["grounded_text"].strip(), "grounded_text is blank"

    actions = report["recommended_actions"]
    assert isinstance(actions, list)
    assert len(actions) >= 1, "recommended_actions must contain at least one item"
    assert all(isinstance(a, str) and a.strip() for a in actions), (
        "recommended_actions contains empty strings"
    )


def test_agent_does_not_hallucinate_component_names(compiled_graph):
    """The grounded_text must not invent component identifiers like
    ``component_xyz``. The only valid component names are the six in the
    canonical mapping. Generic words ("system", "machine", "printer") are
    fine — those aren't part identifiers.

    Lenient: at least one canonical component name must appear (R1 is a
    real incident with nozzle_plate / heating_element activity)."""
    result = _invoke_graph(
        compiled_graph,
        "Diagnose run R1 in detail and tell me which component failed.",
        run_identifier="R1",
    )
    report = _final_report_dict(result)
    text = report["grounded_text"].lower()

    # No invented "component_foo" / "part_42" / "module_xx" identifiers.
    invented = _HALLUCINATED_PART_RE.findall(text)
    # Filter out matches that happen to overlap a legit name (defensive).
    invented = [
        token for token in invented
        if token.lower() not in _VALID_COMPONENT_NAMES
    ]
    assert not invented, (
        f"agent hallucinated component identifiers: {invented} in text {text!r}"
    )

    # Must reference at least one real component — R1 is a printhead/thermal
    # incident with nozzle_plate + heating_element evidence in the seed.
    mentioned = {
        name for name in _VALID_COMPONENT_NAMES
        # Match either the snake_case form or the spaced "nozzle plate" form
        # (the LLM may humanise it). Substring check is enough because the
        # canonical ids are distinctive.
        if name in text or name.replace("_", " ") in text
    }
    assert mentioned, (
        f"grounded_text references no canonical component name. Text: {text!r}"
    )

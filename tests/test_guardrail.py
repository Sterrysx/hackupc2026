import pytest
from langchain_core.messages import AIMessage, HumanMessage
from backend.agent.nodes import guardrail_node, MAX_VALIDATION_ATTEMPTS
from backend.agent.schemas import DiagnosticReport


def _state(report, attempts=0):
    # In the new flow, synthesizer_node appends a DiagnosticReport object (or similar) to messages
    return {
        "messages": [report],
        "run_identifier": "R1",
        "retrieved_telemetry": "{}",
        "final_report": "",
        "validation_attempts": attempts,
    }


def test_valid_report_sets_final_report():
    report = DiagnosticReport(
        grounded_text="The nozzle plate failed.",
        evidence_citation="Based on timestamp: 2026-04-25T14:05:02, run_id: R1",
        severity_indicator="CRITICAL",
        recommended_actions=["Replace nozzle plate", "Cool down system"],
        priority_level="HIGH"
    )
    result = guardrail_node(_state(report))
    assert result["final_report"]["grounded_text"] == report.grounded_text
    assert result["final_report"]["severity_indicator"] == "CRITICAL"
    assert result["final_report"]["priority_level"] == "HIGH"
    assert len(result["final_report"]["recommended_actions"]) == 2


def test_missing_timestamp_triggers_retry():
    report = DiagnosticReport(
        grounded_text="The nozzle plate failed.",
        evidence_citation="Based on run_id: R1",
        severity_indicator="CRITICAL",
        recommended_actions=["Inspect system"],
        priority_level="HIGH"
    )
    result = guardrail_node(_state(report))
    assert "final_report" not in result or result.get("final_report", "") == ""
    assert result["validation_attempts"] == 1
    assert any("evidence_citation must include a timestamp" in m.content for m in result["messages"] if isinstance(m, HumanMessage))


def test_missing_run_id_triggers_retry():
    report = DiagnosticReport(
        grounded_text="The nozzle plate failed.",
        evidence_citation="Based on timestamp: 2026-04-25T14:05:02",
        severity_indicator="CRITICAL",
        recommended_actions=["Inspect system"],
        priority_level="HIGH"
    )
    result = guardrail_node(_state(report))
    assert result.get("final_report", "") == ""
    assert result["validation_attempts"] == 1
    assert any("evidence_citation must include a run identifier" in m.content for m in result["messages"] if isinstance(m, HumanMessage))


def test_missing_recommended_actions_triggers_retry():
    # Pydantic will catch empty list if we enforce it in guardrail, but here we test the guardrail logic
    report = DiagnosticReport(
        grounded_text="The nozzle plate failed.",
        evidence_citation="Based on timestamp: 2026-04-25T14:05:02, run_id: R1",
        severity_indicator="CRITICAL",
        recommended_actions=[],
        priority_level="HIGH"
    )
    result = guardrail_node(_state(report))
    assert result.get("final_report", "") == ""
    assert any("At least one recommended_action must be provided" in m.content for m in result["messages"] if isinstance(m, HumanMessage))


def test_invalid_priority_triggers_retry():
    report = DiagnosticReport(
        grounded_text="The nozzle plate failed.",
        evidence_citation="Based on timestamp: 2026-04-25T14:05:02, run_id: R1",
        severity_indicator="CRITICAL",
        recommended_actions=["Action"],
        priority_level="URGENT" # Invalid
    )
    result = guardrail_node(_state(report))
    assert result.get("final_report", "") == ""
    assert any("priority_level must be LOW, MEDIUM, or HIGH" in m.content for m in result["messages"] if isinstance(m, HumanMessage))


def test_max_attempts_returns_fallback():
    report = "Invalid format"
    result = guardrail_node(_state(report, attempts=MAX_VALIDATION_ATTEMPTS - 1))
    assert result["final_report"]["severity_indicator"] == "CRITICAL"
    assert "Validation failed" in result["final_report"]["grounded_text"]


def test_info_severity_is_accepted():
    report = DiagnosticReport(
        grounded_text="All components nominal.",
        evidence_citation="timestamp: 2026-04-25T14:00:00, run_id: R1",
        severity_indicator="INFO",
        recommended_actions=["Continue monitoring"],
        priority_level="LOW"
    )
    result = guardrail_node(_state(report))
    assert result["final_report"]["severity_indicator"] == "INFO"


def test_warning_severity_is_accepted():
    report = DiagnosticReport(
        grounded_text="Degradation detected.",
        evidence_citation="timestamp: 2026-04-25T14:05:02, run_id: R1",
        severity_indicator="WARNING",
        recommended_actions=["Schedule maintenance"],
        priority_level="MEDIUM"
    )
    result = guardrail_node(_state(report))
    assert result["final_report"]["severity_indicator"] == "WARNING"

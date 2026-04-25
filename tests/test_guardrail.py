import pytest
from langchain_core.messages import AIMessage, HumanMessage
from Ai_Agent.nodes import guardrail_node, MAX_VALIDATION_ATTEMPTS


def _state(content, attempts=0):
    return {
        "messages": [AIMessage(content=content)],
        "run_identifier": "R1",
        "retrieved_telemetry": "{}",
        "final_report": "",
        "validation_attempts": attempts,
    }


def test_valid_report_sets_final_report():
    content = "[CRITICAL]\nThe nozzle plate failed. timestamp: 2026-04-25T14:05:02, run_id: R1"
    result = guardrail_node(_state(content))
    assert result["final_report"] == content


def test_missing_severity_triggers_retry():
    content = "The nozzle plate failed. timestamp: 2026-04-25T14:05:02, run_id: R1"
    result = guardrail_node(_state(content))
    assert result.get("final_report", "") == ""
    assert result["validation_attempts"] == 1
    assert any(isinstance(m, HumanMessage) for m in result["messages"])


def test_missing_citation_triggers_retry():
    content = "[CRITICAL]\nThe nozzle plate temperature was very high."
    result = guardrail_node(_state(content))
    assert result.get("final_report", "") == ""
    assert result["validation_attempts"] == 1


def test_max_attempts_returns_fallback():
    content = "No severity no citation."
    result = guardrail_node(_state(content, attempts=MAX_VALIDATION_ATTEMPTS - 1))
    assert result["final_report"].startswith("[CRITICAL]")
    assert "Validation failed" in result["final_report"]


def test_info_severity_is_accepted():
    content = "[INFO]\nAll components nominal. timestamp: 2026-04-25T14:00:00, run_id: R1"
    result = guardrail_node(_state(content))
    assert result["final_report"] == content


def test_warning_severity_is_accepted():
    content = "[WARNING]\nDegradation detected. timestamp: 2026-04-25T14:05:02, run_id: R1"
    result = guardrail_node(_state(content))
    assert result["final_report"] == content

from langchain_core.messages import HumanMessage

from backend.agent.nodes import synthesizer_node
from backend.agent.schemas import DiagnosticReport


class _FakeBoundTools:
    def invoke(self, _messages):
        raise Exception(
            "tool call validation failed: attempted to call tool 'query_database' which was not in request.tools"
        )


class _FakeStructuredOutput:
    def invoke(self, _messages):
        return DiagnosticReport(
            grounded_text="Recovered via structured fallback.",
            evidence_citation="Based on the telemetry at 2026-04-25T14:05:02 for run R1.",
            severity_indicator="WARNING",
            recommended_actions=["Continue monitoring"],
            priority_level="MEDIUM",
        )


class _FakeLlm:
    def bind_tools(self, _tools):
        return _FakeBoundTools()

    def with_structured_output(self, _schema):
        return _FakeStructuredOutput()


def test_synthesizer_falls_back_to_structured_output_on_tool_validation_error(monkeypatch):
    monkeypatch.setattr("backend.agent.nodes.get_llm", lambda: _FakeLlm())

    state = {
        "messages": [HumanMessage(content="Diagnose this run")],
        "run_identifier": "R1",
        "retrieved_telemetry": "[{\"timestamp\": \"2026-04-25T14:05:02\", \"run_id\": \"R1\"}]",
        "final_report": "",
        "validation_attempts": 0,
    }

    result = synthesizer_node(state)

    assert "final_report" in result
    assert "messages" not in result
    report = result["final_report"]
    assert isinstance(report, DiagnosticReport)
    assert report.severity_indicator == "WARNING"
    assert report.priority_level == "MEDIUM"

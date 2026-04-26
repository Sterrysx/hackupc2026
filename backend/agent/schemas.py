from pydantic import BaseModel, Field
from typing import Optional


class QueryDatabaseInput(BaseModel):
    run_identifier: str = Field(description="The run or scenario ID to query (e.g. 'R1', 'R2')")
    timestamp_range: Optional[str] = Field(
        default=None,
        description="Optional time range filter in format 'HH:MM:SS-HH:MM:SS'",
    )
    component: Optional[str] = Field(
        default=None,
        description="Optional component filter: 'recoater_blade', 'nozzle_plate', or 'heating_element'",
    )
    status: Optional[str] = Field(
        default=None,
        description="Optional state filter: 'FUNCTIONAL', 'DEGRADED', 'CRITICAL', or 'FAILED'",
    )


class TelemetryRecord(BaseModel):
    timestamp: str
    run_id: str
    component: str
    health_index: float
    status: str
    temperature: float
    pressure: float
    fan_speed: float
    metrics: dict


class DiagnosticReport(BaseModel):
    grounded_text: str = Field(description="A clear, plain-language explanation based solely on telemetry. If multiple runs or timeframes are analyzed, explain the root cause and chain of events.")
    evidence_citation: str = Field(description="A reference to the specific data point or timestamp used (e.g., 'Based on the telemetry at 14:05:02...'). Must include the run identifier if applicable.")
    severity_indicator: str = Field(description="A categorization of the information: INFO, WARNING, or CRITICAL.")
    recommended_actions: list[str] = Field(default_factory=list, description="Specific, actionable steps the operator should take based on the diagnosis.")
    priority_level: str = Field(description="Priority of the recommended actions: LOW, MEDIUM, HIGH.")

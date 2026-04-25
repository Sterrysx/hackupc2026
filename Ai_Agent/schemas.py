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
    grounded_text: str
    evidence_citations: list[str]
    severity: str

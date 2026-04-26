from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, MutableMapping


@dataclass
class Component:
    id: str
    spec: Mapping
    counters: MutableMapping[str, int]
    alpha: float = 1.0
    H: float = 1.0
    tau_mant_d: float = 0.0
    L_d: float = 0.0
    hours_since_failure: float = 0.0

    @property
    def lambda0_per_d(self) -> float:
        return float(self.spec["lambda0_per_d"]) * float(self.alpha)

    def status(self) -> str:
        if self.H <= 0.1:
            return "FAILED"
        if self.H <= 0.4:
            return "CRITICAL"
        if self.H <= 0.7:
            return "WARNING"
        return "OK"

    def apply_degradation(self, dH: float) -> None:
        self.H = min(1.0, max(0.0, self.H - float(dH)))

    def apply_preventive(self) -> bool:
        self.H = min(self.H + 0.5, 1.0)
        self.tau_mant_d = 0.0
        return True

    def apply_corrective(self) -> bool:
        self.H = 1.0
        self.tau_mant_d = 0.0
        self.L_d = 0.0
        self.hours_since_failure = 0.0
        return True

    def accumulate_hours(self, hours: float) -> None:
        self.hours_since_failure += float(hours)

    def advance_time(self, days: float) -> None:
        self.tau_mant_d += float(days)
        self.L_d += float(days)

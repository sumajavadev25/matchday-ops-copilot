"""Domain models for stadium operations.

The copilot reasons over a `StadiumSnapshot` (zones + incidents) and returns
`Recommendation`s that always carry an explicit `reasoning` field — the
challenge explicitly rewards explainable output, not bare answers.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class RiskLevel(str, Enum):
    NORMAL = "normal"
    ELEVATED = "elevated"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentType(str, Enum):
    MEDICAL = "medical"
    SECURITY = "security"
    CROWD = "crowd"
    FACILITY = "facility"


class Zone(BaseModel):
    """A gate, concourse, or stand section with a live occupancy count."""

    id: str = Field(..., min_length=1)
    name: str
    capacity: int = Field(..., ge=0)
    occupancy: int = Field(..., ge=0)
    # Optional coordinates let the frontend / Google Maps layer place the zone.
    lat: Optional[float] = None
    lng: Optional[float] = None

    @field_validator("occupancy")
    @classmethod
    def _occupancy_reasonable(cls, v: int) -> int:
        # Occupancy above capacity is allowed (over-crowding is the whole point),
        # but a hard cap avoids nonsense from a malformed upload.
        if v > 1_000_000:
            raise ValueError("occupancy implausibly large")
        return v

    @property
    def density(self) -> float:
        """Occupancy as a fraction of capacity. Guards divide-by-zero."""
        if self.capacity <= 0:
            # A zone with no declared capacity that holds people is maximally risky.
            return 1.0 if self.occupancy > 0 else 0.0
        return self.occupancy / self.capacity


class Incident(BaseModel):
    id: str = Field(..., min_length=1)
    type: IncidentType
    zone_id: str
    severity: int = Field(..., ge=1, le=5)
    description: str = ""
    resolved: bool = False


class StadiumSnapshot(BaseModel):
    """A point-in-time view of the venue the copilot reasons over."""

    zones: list[Zone] = Field(default_factory=list)
    incidents: list[Incident] = Field(default_factory=list)


class Recommendation(BaseModel):
    zone_id: str
    zone_name: str
    risk: RiskLevel
    density: float
    # The three things every recommendation must answer: what, why, and do-what.
    headline: str
    reasoning: str
    action: str
    # Ready-to-broadcast announcement, keyed by language code.
    announcements: dict[str, str] = Field(default_factory=dict)


class CopilotReport(BaseModel):
    generated_by: str  # "gemini" or "fallback" — honest about provenance
    threshold: float
    recommendations: list[Recommendation] = Field(default_factory=list)
    summary: str = ""

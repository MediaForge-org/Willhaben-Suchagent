from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from agent.app.core.time import utc_now


@dataclass(slots=True)
class HealthState:
    process_started_at: datetime = field(default_factory=utc_now)
    last_cycle_started_at: datetime | None = None
    next_cycle_due_at: datetime | None = None
    last_cycle_completed_at: datetime | None = None
    last_successful_cycle_at: datetime | None = None
    last_successful_willhaben_cycle_at: datetime | None = None
    last_successful_notification_at: datetime | None = None
    total_cycle_count: int = 0
    failed_cycle_count: int = 0
    last_cycle_duration_seconds: float | None = None
    last_cycle_error: str | None = None
    last_notification_error: str | None = None
    last_provider_errors: dict[int, str] = field(default_factory=dict)
    scheduler_running: bool = False

    @property
    def status(self) -> str:
        if self.last_cycle_error or self.last_provider_errors or self.last_notification_error:
            return "degraded"
        return "ok"

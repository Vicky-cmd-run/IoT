from __future__ import annotations

from dataclasses import dataclass, field

from model import RouteResponse, SignalPlan


@dataclass
class TraCICommandExecutor:
    enabled: bool = False
    command_log: list[dict] = field(default_factory=list)

    def apply_route_update(self, route: RouteResponse) -> dict:
        record = {
            "type": "route_update",
            "vehicle_id": route.vehicle_id,
            "path": route.best_path,
            "executed": self.enabled,
        }
        self.command_log.append(record)
        return record

    def apply_signal_plan(self, plan: SignalPlan) -> dict:
        record = {
            "type": "signal_plan",
            "intersection_id": plan.intersection_id,
            "green_duration_seconds": plan.green_duration_seconds,
            "mode": plan.mode,
            "executed": self.enabled,
        }
        self.command_log.append(record)
        return record

    def recent_commands(self) -> list[dict]:
        return self.command_log[-20:]

    def clear(self) -> None:
        self.command_log.clear()

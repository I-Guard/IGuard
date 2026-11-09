"""Runtime-tunable system settings stored in the database with validated defaults."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.models import SystemSetting


@dataclass(frozen=True)
class Definition:
    default: Any
    type: str  # "int" | "float" | "bool"
    description: str
    minimum: float | None = None
    maximum: float | None = None


DEFINITIONS: dict[str, Definition] = {
    "cpu_warning_percent": Definition(80, "float", "CPU usage warning threshold (%)", 1, 100),
    "cpu_critical_percent": Definition(95, "float", "CPU usage critical threshold (%)", 1, 100),
    "memory_warning_percent": Definition(80, "float", "Memory usage warning threshold (%)", 1, 100),
    "memory_critical_percent": Definition(
        92, "float", "Memory usage critical threshold (%)", 1, 100
    ),
    "disk_warning_percent": Definition(80, "float", "Disk usage warning threshold (%)", 1, 100),
    "disk_critical_percent": Definition(90, "float", "Disk usage critical threshold (%)", 1, 100),
    "latency_critical_multiplier": Definition(
        3, "float", "A service is CRITICAL-slow when latency exceeds threshold x this", 1, 50
    ),
    "container_restart_threshold": Definition(
        3, "int", "Container restarts within 10 min that raise an incident", 1, 100
    ),
    "sustained_evaluations": Definition(
        2,
        "int",
        "Consecutive detector evaluations a metric breach must persist before an incident is raised",
        1,
        20,
    ),
    "clear_evaluations": Definition(
        3, "int", "Consecutive healthy evaluations before an incident auto-resolves", 1, 50
    ),
    "incident_cooldown_seconds": Definition(
        300,
        "int",
        "A resolved incident re-triggering within this window is reopened (flap tracking) instead of duplicated",
        0,
        86400,
    ),
    "flap_window_seconds": Definition(
        1800, "int", "Window used to count reopen events for flapping detection", 60, 86400
    ),
    "flap_threshold": Definition(
        3, "int", "Reopen count within the window that marks an incident as flapping", 2, 50
    ),
    "escalation_after_seconds": Definition(
        600, "int", "Unacknowledged CRITICAL incidents escalate after this many seconds", 30, 86400
    ),
    "auto_recovery_enabled": Definition(
        True, "bool", "Allow policy-driven automatic recovery for non-sensitive actions"
    ),
    "detection_interval_seconds": Definition(
        15, "int", "Interval of the incident detection loop", 5, 3600
    ),
    "check_retention_days": Definition(14, "int", "Days of service check history to keep", 1, 365),
}


def _coerce(key: str, value: Any) -> Any:
    d = DEFINITIONS[key]
    try:
        if d.type == "bool":
            if isinstance(value, bool):
                return value
            raise ValueError("must be a boolean")
        if isinstance(value, bool):
            raise ValueError("must be a number")
        num = int(value) if d.type == "int" and float(value).is_integer() else float(value)
        if d.type == "int" and not float(value).is_integer():
            raise ValueError("must be an integer")
    except (TypeError, ValueError) as exc:
        raise ValidationFailed(f"Setting '{key}' {exc}") from exc
    if d.minimum is not None and num < d.minimum:
        raise ValidationFailed(f"Setting '{key}' must be >= {d.minimum}")
    if d.maximum is not None and num > d.maximum:
        raise ValidationFailed(f"Setting '{key}' must be <= {d.maximum}")
    return int(num) if d.type == "int" else num


def effective(db: Session) -> dict[str, Any]:
    values = {k: d.default for k, d in DEFINITIONS.items()}
    for row in db.scalars(select(SystemSetting)):
        if row.key in DEFINITIONS:
            values[row.key] = row.value
    return values


def list_settings(db: Session) -> list[dict[str, Any]]:
    rows = {r.key: r for r in db.scalars(select(SystemSetting))}
    out = []
    for key, d in DEFINITIONS.items():
        row = rows.get(key)
        out.append(
            {
                "key": key,
                "value": row.value if row else d.default,
                "description": d.description,
                "default": d.default,
                "type": d.type,
                "minimum": d.minimum,
                "maximum": d.maximum,
                "updated_at": row.updated_at if row else None,
                "updated_by": row.updated_by if row else None,
            }
        )
    return out


def update(db: Session, values: dict[str, Any], actor_name: str) -> dict[str, Any]:
    unknown = sorted(set(values) - set(DEFINITIONS))
    if unknown:
        raise ValidationFailed("Unknown setting(s): " + ", ".join(unknown))
    coerced = {k: _coerce(k, v) for k, v in values.items()}
    merged = {**effective(db), **coerced}
    for prefix in ("cpu", "memory", "disk"):
        if merged[f"{prefix}_warning_percent"] >= merged[f"{prefix}_critical_percent"]:
            raise ValidationFailed(
                f"{prefix}_warning_percent must be below {prefix}_critical_percent"
            )
    for key, val in coerced.items():
        row = db.get(SystemSetting, key)
        if row is None:
            db.add(
                SystemSetting(
                    key=key,
                    value=val,
                    updated_by=actor_name,
                    description=DEFINITIONS[key].description,
                )
            )
        else:
            row.value = val
            row.updated_by = actor_name
    db.flush()
    return coerced

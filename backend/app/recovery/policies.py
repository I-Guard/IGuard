"""Recovery policy loading and validation (the action allowlist).

Policies are declared in YAML under ``recovery/policies`` and synchronised into the
``recovery_actions`` table at startup. API users can never create or edit actions - they can only
*invoke* actions that already exist here. Targets that look like critical infrastructure are
rejected unless explicitly marked ``allow_critical`` (which also forces ``sensitive`` and forbids
automatic triggering).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import RecoveryAction, Service
from app.models.enums import ActionType, IncidentCategory, RoleName

log = get_logger(__name__)

TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")
CRITICAL_RE = re.compile(
    r"(postgres|database|(^|[-_.])db($|[-_.])|prometheus|grafana|loki|promtail|alertmanager|"
    r"docker|socket|iguard-backend|iguard-frontend|recovery-agent|nginx|cadvisor|node-exporter)",
    re.IGNORECASE,
)


def is_critical_target(target: str) -> bool:
    return bool(CRITICAL_RE.search(target))


class PolicyAction(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9\-]{2,100}$")
    name: str = Field(min_length=3, max_length=255)
    description: str = ""
    action_type: ActionType
    target: str
    service: str | None = None
    sensitive: bool = False
    allow_critical: bool = False
    requires_dry_run: bool = True
    auto_trigger: bool = False
    trigger_categories: list[IncidentCategory] = Field(default_factory=list)
    enabled: bool = True
    cooldown_seconds: int = Field(default=300, ge=0, le=86400)
    timeout_seconds: float = Field(default=60, ge=1, le=900)
    max_attempts_per_hour: int = Field(default=3, ge=1, le=60)
    breaker_threshold: int = Field(default=3, ge=1, le=20)
    breaker_reset_seconds: int = Field(default=900, ge=1, le=86400)
    min_role: RoleName = RoleName.OPERATOR
    verify_after_seconds: int = Field(default=10, ge=0, le=300)

    @field_validator("target")
    @classmethod
    def _target(cls, v: str) -> str:
        if not TARGET_RE.match(v):
            raise ValueError(
                "target must be a plain container/script name (no paths or shell syntax)"
            )
        return v

    @model_validator(mode="after")
    def _safety(self) -> PolicyAction:
        if self.action_type in (
            ActionType.CONTAINER_RESTART,
            ActionType.SERVICE_RESTART,
        ) and is_critical_target(self.target):
            if not self.allow_critical:
                raise ValueError(
                    f"target '{self.target}' looks like critical infrastructure; "
                    "set allow_critical: true (and sensitive: true) to expose it"
                )
            if not self.sensitive:
                raise ValueError("critical targets must be sensitive: true")
            if self.auto_trigger:
                raise ValueError("critical targets must never be auto_trigger")
        if self.sensitive and self.auto_trigger:
            raise ValueError("sensitive actions can never be auto_trigger")
        if self.auto_trigger and not self.trigger_categories:
            raise ValueError("auto_trigger requires trigger_categories")
        return self


class PolicyFile(BaseModel):
    actions: list[PolicyAction]


class PolicyError(Exception):
    pass


def load_policy_files(directory: str | Path) -> list[PolicyAction]:
    path = Path(directory)
    if not path.is_dir():
        log.warning("recovery policy directory not found", extra={"dir": str(path)})
        return []
    actions: list[PolicyAction] = []
    seen: set[str] = set()
    for file in sorted(path.glob("*.y*ml")):
        try:
            raw = yaml.safe_load(file.read_text()) or {}
            parsed = PolicyFile.model_validate(raw)
        except (yaml.YAMLError, ValidationError) as exc:
            raise PolicyError(f"Invalid recovery policy {file.name}: {exc}") from exc
        for a in parsed.actions:
            if a.key in seen:
                raise PolicyError(f"Duplicate recovery action key '{a.key}' in {file.name}")
            seen.add(a.key)
            actions.append(a)
    return actions


def sync_policies(db: Session, directory: str | Path) -> dict[str, int]:
    """Upsert policy actions. Actions removed from YAML are disabled (history is preserved)."""
    actions = load_policy_files(directory)
    by_key = {a.key: a for a in db.scalars(select(RecoveryAction))}
    services = {s.name: s for s in db.scalars(select(Service))}
    stats = {"created": 0, "updated": 0, "disabled": 0}
    declared = set()
    for p in actions:
        declared.add(p.key)
        svc = services.get(p.service) if p.service else None
        values = {
            "name": p.name,
            "description": p.description,
            "action_type": p.action_type,
            "target": p.target,
            "service_id": svc.id if svc else None,
            "sensitive": p.sensitive,
            "requires_dry_run": p.requires_dry_run,
            "auto_trigger": p.auto_trigger,
            "trigger_categories": [c.value for c in p.trigger_categories],
            "enabled": p.enabled,
            "cooldown_seconds": p.cooldown_seconds,
            "timeout_seconds": p.timeout_seconds,
            "max_attempts_per_hour": p.max_attempts_per_hour,
            "breaker_threshold": p.breaker_threshold,
            "breaker_reset_seconds": p.breaker_reset_seconds,
            "min_role": p.min_role,
            "verify_after_seconds": p.verify_after_seconds,
        }
        row = by_key.get(p.key)
        if row is None:
            db.add(RecoveryAction(key=p.key, **values))
            stats["created"] += 1
        else:
            for k, v in values.items():
                setattr(row, k, v)
            stats["updated"] += 1
    for key, row in by_key.items():
        if key not in declared and row.enabled:
            row.enabled = False
            stats["disabled"] += 1
    db.flush()
    return stats

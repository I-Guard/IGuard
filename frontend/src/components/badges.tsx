import type { ExecutionStatus, Health, IncidentStatus, ServiceStatus, Severity } from "../types/api";
import { titleCase } from "../utils/format";
import { Badge, type Tone } from "./ui";

const SEV: Record<Severity, Tone> = { INFO: "info", WARNING: "warn", CRITICAL: "crit" };
export const SeverityBadge = ({ severity }: { severity: Severity }) => <Badge tone={SEV[severity]}>{severity}</Badge>;

const INC: Record<IncidentStatus, Tone> = { DETECTED: "crit", ACKNOWLEDGED: "warn", INVESTIGATING: "warn", RECOVERING: "info", RESOLVED: "ok" };
export const IncidentStatusBadge = ({ status }: { status: IncidentStatus }) => <Badge tone={INC[status]}>{titleCase(status)}</Badge>;

const SVC: Record<ServiceStatus, Tone> = { UNKNOWN: "neutral", UP: "ok", DEGRADED: "warn", DOWN: "crit" };
export const ServiceStatusBadge = ({ status }: { status: ServiceStatus }) => <Badge tone={SVC[status]}>{status}</Badge>;

const HEALTH: Record<Health, Tone> = { healthy: "ok", degraded: "warn", unhealthy: "crit", unknown: "neutral" };
export const HealthBadge = ({ health }: { health: Health }) => <Badge tone={HEALTH[health]}>{titleCase(health)}</Badge>;

const EXEC: Record<ExecutionStatus, Tone> = { DRY_RUN_OK: "info", RUNNING: "warn", SUCCEEDED: "ok", FAILED: "crit", VERIFICATION_FAILED: "crit", REJECTED: "neutral" };
export const ExecutionBadge = ({ status }: { status: ExecutionStatus }) => <Badge tone={EXEC[status]}>{titleCase(status)}</Badge>;

import { describe, expect, it } from "vitest";
import { computePosture, recoverySuccessRate, statusRank } from "../src/utils/posture";
import type { Overview } from "../src/types/api";

const base = (o: Partial<Overview> = {}): Overview => ({
  generated_at: "2026-11-01T00:00:00Z", monitoring: { prometheus_available: true },
  servers: { total: 1, healthy: 1, degraded: 0, unhealthy: 0, unknown: 0 }, incidents: { active: 0, critical: 0 },
  services: { total: 2, up: 2, degraded: 0, down: 0, unknown: 0, availability_24h_percent: 100, avg_latency_ms_15m: 10 },
  utilization: { cpu_percent: 1, memory_percent: 1, disk_percent: 1 }, recent_incidents: [], recent_alerts: [], recovery_activity_24h: {}, ...o,
});

describe("computePosture", () => {
  it("is operational when everything is healthy", () => { expect(computePosture(base()).level).toBe("operational"); });
  it("is an outage for a critical incident, a down service or an unhealthy server", () => {
    expect(computePosture(base({ incidents: { active: 1, critical: 1 } })).level).toBe("outage");
    expect(computePosture(base({ services: { ...base().services, down: 1, up: 1 } })).level).toBe("outage");
    expect(computePosture(base({ servers: { ...base().servers, healthy: 0, unhealthy: 1 } })).level).toBe("outage");
  });
  it("is degraded for non-critical incidents or degraded targets", () => {
    const p = computePosture(base({ incidents: { active: 2, critical: 0 } }));
    expect(p.level).toBe("degraded");
    expect(p.reasons[0]).toContain("2 active incidents");
  });
  it("never claims health when nothing is monitored", () => {
    const p = computePosture(base({ servers: { total: 0, healthy: 0, degraded: 0, unhealthy: 0, unknown: 0 }, services: { ...base().services, total: 0, up: 0 } }));
    expect(p.level).toBe("unknown");
  });
  it("is unknown while every target is still unreported", () => {
    const p = computePosture(base({ servers: { total: 1, healthy: 0, degraded: 0, unhealthy: 0, unknown: 1 }, services: { ...base().services, up: 0, unknown: 2 } }));
    expect(p.level).toBe("unknown");
  });
  it("flags missing Prometheus as a caveat without inventing an incident", () => {
    const p = computePosture(base({ monitoring: { prometheus_available: false } }));
    expect(p.level).toBe("operational");
    expect(p.caveats.join()).toContain("Prometheus");
  });
});

describe("recoverySuccessRate", () => {
  it("is null with no executions (never 0 or 100)", () => { expect(recoverySuccessRate({})).toBeNull(); });
  it("counts failed and verification failures against success", () => { expect(recoverySuccessRate({ SUCCEEDED: 3, FAILED: 1 })).toBe(75); expect(recoverySuccessRate({ SUCCEEDED: 1, VERIFICATION_FAILED: 1 })).toBe(50); });
});

describe("statusRank", () => { it("sorts worst first", () => { expect(["UP", "DOWN", "UNKNOWN", "DEGRADED"].sort((a, b) => statusRank(a) - statusRank(b))).toEqual(["DOWN", "DEGRADED", "UNKNOWN", "UP"]); }); });

import type { Overview } from "../types/api";

export type PostureLevel = "operational" | "degraded" | "outage" | "unknown";
export interface Posture { level: PostureLevel; headline: string; reasons: string[]; caveats: string[] }

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** Derives the overall posture strictly from the counts the API returned - nothing is assumed. */
export function computePosture(o: Overview): Posture {
  const reasons: string[] = [];
  const caveats: string[] = [];
  if (!o.monitoring.prometheus_available) caveats.push("Host metrics unavailable (Prometheus unreachable)");

  const nothingMonitored = o.servers.total === 0 && o.services.total === 0;
  if (nothingMonitored) return { level: "unknown", headline: "Nothing is monitored yet", reasons: ["Add a server or a service to begin"], caveats };

  if (o.incidents.critical > 0) reasons.push(`${plural(o.incidents.critical, "critical incident")} open`);
  if (o.services.down > 0) reasons.push(`${plural(o.services.down, "service")} down`);
  if (o.servers.unhealthy > 0) reasons.push(`${plural(o.servers.unhealthy, "server")} unhealthy`);
  if (reasons.length) return { level: "outage", headline: "Major disruption", reasons, caveats };

  const rest: string[] = [];
  const nonCritical = o.incidents.active - o.incidents.critical;
  if (nonCritical > 0) rest.push(`${plural(nonCritical, "active incident")}`);
  if (o.services.degraded > 0) rest.push(`${plural(o.services.degraded, "service")} degraded`);
  if (o.servers.degraded > 0) rest.push(`${plural(o.servers.degraded, "server")} degraded`);
  if (rest.length) return { level: "degraded", headline: "Partially degraded", reasons: rest, caveats };

  const unknown = o.services.unknown + o.servers.unknown;
  if (unknown > 0 && unknown === o.services.total + o.servers.total) return { level: "unknown", headline: "Waiting for first results", reasons: ["No checks or metrics have reported yet"], caveats };
  if (unknown > 0) caveats.push(`${plural(unknown, "target")} not yet reporting`);
  return { level: "operational", headline: "All systems operational", reasons: [], caveats };
}

/** Recovery success rate over real (non dry-run) executions; null when there were none. */
export function recoverySuccessRate(counts: Record<string, number>): number | null {
  const ok = counts.SUCCEEDED ?? 0;
  const bad = (counts.FAILED ?? 0) + (counts.VERIFICATION_FAILED ?? 0);
  return ok + bad === 0 ? null : (ok / (ok + bad)) * 100;
}

const ORDER: Record<string, number> = { DOWN: 0, DEGRADED: 1, UNKNOWN: 2, UP: 3 };
export const statusRank = (s: string) => ORDER[s] ?? 4;

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../services/api";
import type {
  AlertConfig, AlertsResponse, AuditLog, CheckResult, Incident, IncidentDetail, IncidentEvent, LogEntry, NodeMetrics, Overview, Page,
  RangeSeries, RecoveryAction, RecoveryExecution, Server, Service, ServiceCheck, Setting, User, UserRef,
} from "../types/api";

type Q = Record<string, unknown>;
const list = <T>(path: string, q: Q) => api.get<Page<T>>(path, q);

export const useOverview = () => useQuery({ queryKey: ["overview"], queryFn: () => api.get<Overview>("/overview"), refetchInterval: 15_000 });
export const useServers = (q: Q) => useQuery({ queryKey: ["servers", q], queryFn: () => list<Server>("/servers", q), placeholderData: keepPreviousData });
export const useServer = (id: string) => useQuery({ queryKey: ["server", id], queryFn: () => api.get<Server>(`/servers/${id}`) });
export const useServerMetrics = (id: string, enabled = true) => useQuery({ queryKey: ["server-metrics", id], queryFn: () => api.get<NodeMetrics>(`/servers/${id}/metrics`), refetchInterval: 15_000, enabled });
export const useServerRange = (id: string, metric: string, minutes: number) => useQuery({ queryKey: ["server-range", id, metric, minutes], queryFn: () => api.get<RangeSeries>(`/servers/${id}/metrics/range`, { metric, minutes }), refetchInterval: 30_000 });
export const useServices = (q: Q) => useQuery({ queryKey: ["services", q], queryFn: () => list<Service>("/services", q), placeholderData: keepPreviousData, refetchInterval: 15_000 });
export const useService = (id: string) => useQuery({ queryKey: ["service", id], queryFn: () => api.get<Service>(`/services/${id}`), refetchInterval: 15_000 });
export const useServiceChecks = (id: string, hours = 24) => useQuery({ queryKey: ["service-checks", id, hours], queryFn: () => api.get<ServiceCheck[]>(`/services/${id}/checks`, { hours, limit: 200 }), refetchInterval: 15_000 });
export const useServiceAvailability = (id: string) => useQuery({ queryKey: ["service-avail", id], queryFn: () => api.get<Record<string, number | null>>(`/services/${id}/availability`) });
export const useIncidents = (q: Q) => useQuery({ queryKey: ["incidents", q], queryFn: () => list<Incident>("/incidents", q), placeholderData: keepPreviousData, refetchInterval: 15_000 });
export const useIncident = (id: string) => useQuery({ queryKey: ["incident", id], queryFn: () => api.get<IncidentDetail>(`/incidents/${id}`), refetchInterval: 10_000 });
export const useTimeline = (id: string) => useQuery({ queryKey: ["timeline", id], queryFn: () => api.get<IncidentEvent[]>(`/incidents/${id}/timeline`), refetchInterval: 10_000 });
export const useAssignable = (enabled: boolean) => useQuery({ queryKey: ["assignable"], queryFn: () => api.get<UserRef[]>("/users/assignable"), enabled });
export const useRecoveryActions = () => useQuery({ queryKey: ["recovery-actions"], queryFn: () => api.get<RecoveryAction[]>("/recovery/actions"), refetchInterval: 10_000 });
export const useRecoveryHistory = (q: Q) => useQuery({ queryKey: ["recovery-history", q], queryFn: () => list<RecoveryExecution>("/recovery/history", q), placeholderData: keepPreviousData, refetchInterval: 10_000 });
export const useLogs = (q: Q, enabled = true) => useQuery({ queryKey: ["logs", q], queryFn: () => api.get<LogEntry[]>(q.q ? "/logs/search" : "/logs", q), enabled, retry: false });
export const useAlerts = (q: Q) => useQuery({ queryKey: ["alerts", q], queryFn: () => api.get<AlertsResponse>("/alerts", q), refetchInterval: 20_000, placeholderData: keepPreviousData });
export const useAlertConfig = () => useQuery({ queryKey: ["alert-config"], queryFn: () => api.get<AlertConfig>("/alerts/configuration") });
export const useAudit = (q: Q) => useQuery({ queryKey: ["audit", q], queryFn: () => list<AuditLog>("/audit-logs", q), placeholderData: keepPreviousData });
export const useUsers = (q: Q) => useQuery({ queryKey: ["users", q], queryFn: () => list<User>("/users", q), placeholderData: keepPreviousData });
export const useSettings = () => useQuery({ queryKey: ["settings"], queryFn: () => api.get<Setting[]>("/settings") });
export const useReport = <T,>(name: string, days: number) => useQuery({ queryKey: ["report", name, days], queryFn: () => api.get<T>(`/reports/${name}`, { days }) });

/** Mutation helper that invalidates the given query-key prefixes on success. */
export function useAction<TVars, TRes>(fn: (v: TVars) => Promise<TRes>, invalidate: string[] = []) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => { invalidate.forEach((k) => qc.invalidateQueries({ queryKey: [k] })); } });
}

export const checkServiceNow = (id: string) => api.post<CheckResult>(`/services/${id}/check`);

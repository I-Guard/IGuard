export type Role = "ADMIN" | "OPERATOR" | "VIEWER";
export type Severity = "INFO" | "WARNING" | "CRITICAL";
export type IncidentStatus = "DETECTED" | "ACKNOWLEDGED" | "INVESTIGATING" | "RECOVERING" | "RESOLVED";
export type ServiceStatus = "UNKNOWN" | "UP" | "DEGRADED" | "DOWN";
export type Health = "healthy" | "degraded" | "unhealthy" | "unknown";
export type ExecutionStatus = "DRY_RUN_OK" | "RUNNING" | "SUCCEEDED" | "FAILED" | "VERIFICATION_FAILED" | "REJECTED";

export interface Page<T> { items: T[]; total: number; page: number; page_size: number; pages: number }

export interface User {
  id: string; email: string; username: string; full_name: string; is_active: boolean;
  must_change_password: boolean; roles: Role[]; last_login_at: string | null; created_at: string;
}
export interface TokenResponse { access_token: string; token_type: string; expires_in: number; csrf_token: string; user: User }
export interface UserRef { id: string; username: string; full_name: string }

export interface Server {
  id: string; name: string; hostname: string; ip_address: string | null; environment: string; description: string;
  prometheus_instance: string | null; tags: string[]; is_active: boolean; created_at: string; updated_at: string;
  health: Health; active_incidents: number; service_count: number;
}
export interface Service {
  id: string; name: string; description: string; server_id: string | null; server_name: string | null;
  check_type: "HTTP" | "HTTPS" | "TCP"; url: string | null; host: string | null; port: number | null;
  expected_status_codes: number[]; interval_seconds: number; timeout_seconds: number; retry_threshold: number;
  latency_threshold_ms: number; enabled: boolean; container_name: string | null; status: ServiceStatus;
  consecutive_failures: number; last_checked_at: string | null; last_response_ms: number | null;
  last_status_code: number | null; last_error: string | null; status_since: string | null;
  created_at: string; updated_at: string; availability_24h: number | null;
}
export interface ServiceCheck { id: number; service_id: string; checked_at: string; success: boolean; status_code: number | null; response_time_ms: number | null; error: string | null }
export interface CheckResult { service_id: string; success: boolean; status: ServiceStatus; status_code: number | null; response_time_ms: number | null; error: string | null; checked_at: string }

export interface Incident {
  id: string; title: string; description: string; severity: Severity; category: string; status: IncidentStatus;
  source: string; fingerprint: string; server_id: string | null; server_name: string | null;
  service_id: string | null; service_name: string | null; acknowledged_by: UserRef | null; assigned_to: UserRef | null;
  root_cause: string | null; resolution_summary: string | null; occurrences: number; flap_count: number;
  is_flapping: boolean; escalation_level: number; correlation_group: string | null; context: Record<string, unknown> | null;
  first_seen_at: string; last_seen_at: string; created_at: string; updated_at: string;
  acknowledged_at: string | null; resolved_at: string | null;
}
export interface IncidentDetail extends Incident { related: Incident[] }
export interface IncidentEvent { id: string; incident_id: string; event_type: string; message: string; actor_name: string | null; data: Record<string, unknown> | null; created_at: string }

export interface RecoveryAction {
  id: string; key: string; name: string; description: string; action_type: string; target: string;
  service_id: string | null; service_name: string | null; sensitive: boolean; requires_dry_run: boolean;
  auto_trigger: boolean; trigger_categories: string[]; enabled: boolean; cooldown_seconds: number;
  timeout_seconds: number; max_attempts_per_hour: number; breaker_threshold: number; breaker_reset_seconds: number;
  min_role: Role; circuit_open: boolean; cooldown_remaining_seconds: number; last_execution_at: string | null;
  last_status: ExecutionStatus | null;
}
export interface RecoveryExecution {
  id: string; action_id: string; action_key: string | null; action_name: string | null; incident_id: string | null;
  requested_by_name: string | null; trigger: "MANUAL" | "AUTOMATIC"; dry_run: boolean; status: ExecutionStatus;
  simulated: boolean; verification_passed: boolean | null; output: string | null; error: string | null;
  started_at: string | null; finished_at: string | null; duration_ms: number | null; created_at: string;
}

export interface Overview {
  generated_at: string;
  monitoring: { prometheus_available: boolean };
  servers: { total: number; healthy: number; degraded: number; unhealthy: number; unknown: number };
  incidents: { active: number; critical: number };
  services: { total: number; up: number; degraded: number; down: number; unknown: number; availability_24h_percent: number | null; avg_latency_ms_15m: number | null };
  utilization: { cpu_percent: number | null; memory_percent: number | null; disk_percent: number | null };
  recent_incidents: Incident[];
  recent_alerts: Notification[];
  recovery_activity_24h: Record<string, number>;
}
export interface Notification { id: string; channel: string; event_type: string; incident_id: string | null; severity: string | null; title: string; body: string; status: string; attempts: number; last_error: string | null; sent_at: string | null; created_at: string }
export interface AlertItem { source: string; name: string; severity: string | null; state: string; summary: string; started_at: string | null; labels: Record<string, string>; incident_id: string | null }
export interface AlertsResponse { alertmanager_available: boolean; active: AlertItem[]; history: { items: AlertItem[]; total: number; page: number; page_size: number } }
export interface AlertConfig { id: string; channel: string; enabled: boolean; min_severity: Severity; notify_events: string[]; cooldown_seconds: number; updated_at: string; channel_configured: boolean }
export interface AuditLog { id: string; created_at: string; actor_id: string | null; actor_name: string; action: string; resource_type: string; resource_id: string | null; outcome: string; ip_address: string | null; request_id: string | null; details: Record<string, unknown> | null }
export interface LogEntry { timestamp: string; line: string; labels: Record<string, string>; fields: Record<string, unknown> }
export interface Setting { key: string; value: number | boolean; description: string; default: number | boolean; type: "int" | "float" | "bool"; minimum: number | null; maximum: number | null; updated_at: string | null; updated_by: string | null }

export interface NodeMetrics {
  available: boolean; reason: string | null;
  metrics: null | {
    instance: string; cpu_usage_percent: number | null; load1: number | null; load5: number | null; load15: number | null;
    cpu_cores: number | null; memory_total_bytes: number | null; memory_available_bytes: number | null; memory_used_bytes: number | null;
    memory_usage_percent: number | null; disk_total_bytes: number | null; disk_free_bytes: number | null; disk_usage_percent: number | null;
    disk_io_utilization_percent: number | null; disk_read_bytes_per_sec: number | null; disk_write_bytes_per_sec: number | null;
    network_receive_bytes_per_sec: number | null; network_transmit_bytes_per_sec: number | null;
    network_receive_errors_per_sec: number | null; network_transmit_errors_per_sec: number | null;
    network_receive_drops_per_sec: number | null; network_transmit_drops_per_sec: number | null;
    uptime_seconds: number | null; host: { hostname?: string; kernel?: string; machine?: string; os?: string } | null;
    per_core_cpu_percent: { cpu: string; usage_percent: number }[];
    filesystems: { mountpoint: string; fstype: string; usage_percent: number }[];
  };
}
export interface RangeSeries { metric: string; step?: number; series: { labels: Record<string, string>; points: { t: number; v: number }[] }[] }

export interface ApiErrorBody { error: { code: string; message: string; details?: unknown; request_id?: string } }

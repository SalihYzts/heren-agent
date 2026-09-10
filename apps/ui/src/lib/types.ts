// Wire types — mirror apps/core/nero_core/protocol.py. Keep in sync by hand until codegen.

export type DeviceStatus = 'online' | 'offline'
export type Risk = 'low' | 'medium' | 'high' | 'critical'
export type ActionStatus =
  | 'pending' | 'awaiting_approval' | 'approved' | 'denied' | 'expired'
  | 'running' | 'completed' | 'failed' | 'device_offline'

export interface Device {
  device_id: string
  name: string
  platform: string
  public_key: string
  status: DeviceStatus
  last_seen: number | null
  capabilities: string[]
}

export interface Metrics {
  load1?: number
  load5?: number
  cpu_pct?: number
  ram_pct?: number
  ram_total_mb?: number
  ts?: number
}

export interface Approval {
  request_id: string
  device_id: string
  action: string
  params: Record<string, unknown>
  risk: Risk
  requested_by: string
  expires_at?: number
}

export interface ActionResult {
  request_id: string
  status: ActionStatus
  output: Record<string, unknown>
  error: string | null
  duration_ms: number | null
}

export interface ActionRecord {
  request_id: string
  device_id: string
  action: string
  params: Record<string, unknown>
  requested_by: string
  created_at: number
  status: ActionStatus
  approved_by: string | null
  risk: Risk
}

export interface AuditRow {
  id: number
  ts: number
  request_id: string
  device_id: string
  action: string
  risk: Risk
  approved_by: string | null
  result: string
  duration_ms: number | null
  error: string | null
  params: Record<string, unknown>
}

export interface BootEntry {
  id: string
  title: string
  default: boolean
  active?: boolean
}

export interface Event {
  type: string
  payload: Record<string, unknown>
  ts: number
}

export const ACTION_RISK: Record<string, Risk> = {
  get_status: 'low', get_metrics: 'low', get_boot_entries: 'low',
  lock: 'medium', launch_app: 'medium', stop_app: 'medium', restart_service: 'medium',
  run_approved_command: 'medium', wake: 'medium',
  sleep: 'high', shutdown: 'high', restart: 'high', set_next_boot: 'high',
}

export const riskOf = (action: string): Risk => ACTION_RISK[action] ?? 'critical'

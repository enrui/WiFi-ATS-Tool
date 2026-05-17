export interface Run {
  id: string
  timestamp: string
  type: string
  passed: number
  failed: number
  total: number
  has_ai_report: boolean
  stability?: {
    band: string
    checks: number
    dl_avg_mbps: number
    ul_avg_mbps: number
    drops: number
    duration_s: number
    result: string
  }
  reset?: {
    total: number
    success: number
    failure: number
    result: string
  }
  ssh_stress?: {
    total: number
    success: number
    failure: number
    result: string
  }
}

export interface RunDetail extends Run {
  cases: { name: string; status: string; time: number; message?: string }[]
  ai_report?: string
  reset_detail?: {
    total: number
    success: number
    failure: number
    result: string
    iterations: {
      iteration: number
      result: string
      browser_ok: boolean
      serial_ok: boolean
      boot_detected: boolean
      boot_time_s: number
      serial_log?: string
    }[]
  }
  ssh_stress_detail?: {
    total: number
    success: number
    failure: number
    result: string
    iterations: {
      iteration: number
      result: string
      browser_ok: boolean
      ssh_success: number
      ssh_fail: number
      ssh_cycles: { cycle: number; success: boolean; time_ms: number; error: string }[]
      serial_ok: boolean
      boot_detected: boolean
      boot_time_s: number
    }[]
  }
  log?: string
}

export interface RunStatus {
  running: boolean
  pid?: number
  log_file?: string
  mode?: string
}

export interface StationStatus {
  nodes: {
    dut: { ip: string; ok: boolean }
    bpi: { ip: string; ok: boolean }
  }
  api_key: { set: boolean; preview: string }
  packages: Record<string, boolean>
}

export interface Settings {
  api_key_set: boolean
  api_key_preview: string
  dut_ip: string
  bpi_ip: string
  serial_port: string
  serial_baud: number
  web_host: string
  web_user: string
  web_password: string
  ssh_user: string
  ssh_password: string
}

export interface SaveSettingsReq {
  api_key?:      string
  dut_ip?:       string
  bpi_ip?:       string
  serial_port?:  string
  serial_baud?:  number
  web_host?:     string
  web_user?:     string
  web_password?: string
  ssh_user?:     string
  ssh_password?: string
}

export interface TriggerReq {
  mode:        string
  iterations?: number
  ssh_cycles?: number
  do_reset?:   boolean
}

const get  = (url: string) => fetch(url).then(r => r.json())
const post = (url: string, body: unknown) =>
  fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(r => r.json())

export interface LiveLog {
  content: string
  running: boolean
}

export const api = {
  liveLog:       (): Promise<LiveLog>              => get('/api/log/live'),
  runs:          (): Promise<Run[]>               => get('/api/runs'),
  runDetail:     (id: string): Promise<RunDetail>  => get(`/api/runs/${id}`),
  status:        (): Promise<RunStatus>            => get('/api/status'),
  stationStatus: (): Promise<StationStatus>        => get('/api/station/status'),
  settings:      (): Promise<Settings>             => get('/api/settings'),
  saveSettings:  (body: SaveSettingsReq)           => post('/api/settings', body),
  trigger:       (req: TriggerReq)                 => post('/api/trigger', req),
  stop:          ()                               => fetch('/api/trigger', { method: 'DELETE' }).then(r => r.json()),
}

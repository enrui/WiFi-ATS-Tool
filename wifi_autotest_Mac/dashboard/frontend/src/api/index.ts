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
}

export interface RunDetail extends Run {
  cases: { name: string; status: string; time: number; message?: string }[]
  ai_report?: string
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
}

const get = (url: string) => fetch(url).then(r => r.json())
const post = (url: string, body: unknown) =>
  fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(r => r.json())

export const api = {
  runs:          (): Promise<Run[]>         => get('/api/runs'),
  runDetail:     (id: string): Promise<RunDetail> => get(`/api/runs/${id}`),
  status:        (): Promise<RunStatus>     => get('/api/status'),
  stationStatus: (): Promise<StationStatus> => get('/api/station/status'),
  settings:      (): Promise<Settings>      => get('/api/settings'),
  saveSettings:  (body: { api_key?: string }) => post('/api/settings', body),
  trigger:       (mode: string)             => post('/api/trigger', { mode }),
  stop:          ()                         => fetch('/api/trigger', { method: 'DELETE' }).then(r => r.json()),
}

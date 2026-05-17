import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api, type Run, type RunStatus } from '@/api'

export const useAppStore = defineStore('app', () => {
  // ── theme ──────────────────────────────────────────────────
  const theme = ref<'dark' | 'light'>(
    (localStorage.getItem('ats-theme') as 'dark' | 'light') || 'dark'
  )
  function setTheme(t: 'dark' | 'light') {
    theme.value = t
    localStorage.setItem('ats-theme', t)
  }

  // Override accent color to amber in light mode (matches the style reference)
  const themeOverrides = computed(() =>
    theme.value === 'light'
      ? {
          common: {
            primaryColor:       '#c9932a',
            primaryColorHover:  '#e0a832',
            primaryColorPressed:'#b07d20',
            primaryColorSuppl:  '#c9932a',
          },
        }
      : {}
  )

  // ── run data ───────────────────────────────────────────────
  const runs   = ref<Run[]>([])
  const status = ref<RunStatus>({ running: false })

  const rfRuns        = computed(() => runs.value.filter((r: Run) => r.type !== 'stability'))
  const stabilityRuns = computed(() => runs.value.filter((r: Run) => r.type === 'stability'))

  const overallPassRate = computed(() => {
    const rf = rfRuns.value.filter((r: Run) => r.total > 0)
    if (!rf.length) return 100
    return Math.round(
      rf.reduce((s: number, r: Run) => s + r.passed, 0) /
      rf.reduce((s: number, r: Run) => s + r.total, 0) * 100
    )
  })

  async function refresh() {
    const [r, s] = await Promise.all([api.runs(), api.status()])
    runs.value   = r
    status.value = s
  }

  async function pollStatus() {
    const prev = status.value.running
    status.value = await api.status()
    if (prev && !status.value.running) await refresh()
  }

  async function trigger(mode: string, iterations = 0) {
    const res = await api.trigger(mode, iterations)
    if (res.status === 'already_running') return res
    status.value = { running: true, pid: res.pid, log_file: res.log_file, mode }
    return res
  }

  async function stop() {
    await api.stop()
    status.value = { running: false }
  }

  return {
    theme, setTheme, themeOverrides,
    runs, status, rfRuns, stabilityRuns, overallPassRate,
    refresh, pollStatus, trigger, stop,
  }
})

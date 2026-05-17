<script setup lang="ts">
import { h, ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { NTag, useMessage } from 'naive-ui'
import { api, type Run, type RunDetail } from '@/api'
import { useAppStore } from '@/stores/app'

const store   = useAppStore()
const message = useMessage()

// Use store.runs directly so the ↻ refresh button and auto-poll both work
const runs = computed(() => store.runs.filter((r: Run) => r.type === 'ssh-stress'))

const detail     = ref<RunDetail | null>(null)
const showModal  = ref(false)
const loading    = ref(false)
const iterations = ref(5)
const sshCycles  = ref(10)
const doReset    = ref(true)

const isRunning = computed(() =>
  store.status.running && store.status.mode === 'ssh-stress'
)

// ── Live log ──────────────────────────────────────────────────────────────────
const liveLogContent = ref('')
const liveLogEl      = ref<HTMLElement | null>(null)
let liveTimer: ReturnType<typeof setInterval> | null = null

async function fetchLiveLog() {
  const res = await api.liveLog()
  liveLogContent.value = res.content
  await nextTick()
  if (liveLogEl.value) liveLogEl.value.scrollTop = liveLogEl.value.scrollHeight
}

watch(isRunning, (running) => {
  if (running) {
    fetchLiveLog()
    liveTimer = setInterval(fetchLiveLog, 2000)
  } else {
    if (liveTimer) { clearInterval(liveTimer); liveTimer = null }
    // Final fetch after test finishes
    fetchLiveLog()
  }
}, { immediate: true })

onMounted(() => store.refresh())
onUnmounted(() => { if (liveTimer) clearInterval(liveTimer) })

function fmtDate(ts?: string) {
  if (!ts) return '—'
  const m = ts.match(/(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/)
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : ts
}

const columns = [
  { title: 'Timestamp', key: 'ts',      render: (r: Run) => fmtDate(r.timestamp) },
  {
    title: 'Result', key: 'result', width: 90,
    render: (r: Run) => h(NTag,
      { type: r.ssh_stress?.result === 'PASS' ? 'success' : 'error', size: 'small' },
      { default: () => r.ssh_stress?.result || '—' }),
  },
  { title: 'Cycles',  key: 'total',   width: 80, render: (r: Run) => String(r.ssh_stress?.total   ?? r.total  ?? '—') },
  { title: '✓ Pass',  key: 'success', width: 80, render: (r: Run) => String(r.ssh_stress?.success ?? r.passed ?? '—') },
  { title: '✗ Fail',  key: 'failure', width: 80, render: (r: Run) => String(r.ssh_stress?.failure ?? r.failed ?? '—') },
]

type SshCycle = { cycle: number; success: boolean; time_ms: number; error: string }
type IterInfo = {
  iteration: number
  result: string
  browser_ok: boolean
  ssh_success: number
  ssh_fail: number
  ssh_cycles: SshCycle[]
  serial_ok: boolean
  boot_detected: boolean
  boot_time_s: number
}

const iterColumns = [
  { title: '#',          key: 'iteration',   width: 50 },
  {
    title: 'Result',     key: 'result',      width: 80,
    render: (it: IterInfo) => h(NTag,
      { type: it.result === 'PASS' ? 'success' : 'error', size: 'small' },
      { default: () => it.result }),
  },
  { title: 'Browser',   key: 'browser_ok',  width: 80,  render: (it: IterInfo) => it.browser_ok   ? '✓' : '✗' },
  { title: 'SSH ✓',     key: 'ssh_success', width: 70,  render: (it: IterInfo) => String(it.ssh_success) },
  { title: 'SSH ✗',     key: 'ssh_fail',    width: 70,  render: (it: IterInfo) => String(it.ssh_fail) },
  { title: 'Serial',    key: 'serial_ok',   width: 70,  render: (it: IterInfo) => it.serial_ok    ? '✓' : '✗' },
  { title: 'Boot',      key: 'boot_detected', width: 70, render: (it: IterInfo) => it.boot_detected ? '✓' : '✗' },
  { title: 'Boot Time', key: 'boot_time_s', width: 90,  render: (it: IterInfo) => it.boot_time_s > 0 ? `${it.boot_time_s}s` : '—' },
]

const sshCycleColumns = [
  { title: '#',       key: 'cycle',   width: 50 },
  {
    title: 'Result',  key: 'success', width: 80,
    render: (c: SshCycle) => h(NTag,
      { type: c.success ? 'success' : 'error', size: 'small' },
      { default: () => c.success ? 'OK' : 'FAIL' }),
  },
  { title: 'Time',    key: 'time_ms', width: 90,  render: (c: SshCycle) => `${c.time_ms} ms` },
  { title: 'Error',   key: 'error',               render: (c: SshCycle) => c.error || '—' },
]

const selectedIter = ref<IterInfo | null>(null)

async function openDetail(row: Run) {
  loading.value   = true
  showModal.value = true
  detail.value    = null
  selectedIter.value = null
  try {
    detail.value = await api.runDetail(row.id)
  } finally {
    loading.value = false
  }
}

async function runTest() {
  const res = await store.trigger({
    mode:       'ssh-stress',
    iterations: iterations.value,
    ssh_cycles: sshCycles.value,
    do_reset:   doReset.value,
  })
  if (res?.status === 'already_running') {
    message.warning(`Already running (PID ${res.pid})`)
  } else {
    const n = iterations.value
    message.info(`SSH Stress started — ${n === 0 ? '∞' : n} cycles × ${sshCycles.value} SSH attempts`)
  }
}
</script>

<template>
  <n-space vertical :size="16">

    <!-- ── Actions ── -->
    <n-card size="small">
      <n-space align="center" :size="12" wrap>
        <n-input-number v-model:value="iterations" :min="0" :max="9999" style="width:140px;">
          <template #prefix>Cycles</template>
        </n-input-number>
        <n-input-number v-model:value="sshCycles"  :min="1" :max="100"  style="width:150px;">
          <template #prefix>SSH/cycle</template>
        </n-input-number>

        <n-divider vertical />

        <n-space align="center" :size="6">
          <n-switch v-model:value="doReset" />
          <n-text :depth="doReset ? 1 : 3" style="font-size:13px;">
            Reset Default
          </n-text>
        </n-space>

        <n-text depth="3" style="font-size:12px;">（Cycles=0 為無限循環）</n-text>

        <n-button type="primary" :disabled="store.status.running" @click="runTest">
          🔑 Run SSH Stress
        </n-button>

        <template v-if="isRunning">
          <n-divider vertical />
          <n-badge dot processing type="warning" />
          <n-text depth="3" style="font-size:13px;">Running… PID {{ store.status.pid }}</n-text>
          <n-button size="small" type="error" ghost @click="store.stop()">■ Stop</n-button>
        </template>
      </n-space>
    </n-card>

    <!-- ── Flow info ── -->
    <n-alert type="info" :bordered="false" style="font-size:13px;">
      每個 cycle：
      <strong>①</strong> Browser 登入 DUT Web GUI → 開啟 SSH Service →
      <strong>②</strong> 等待 SSH 就緒 →
      <strong>③</strong> 做 N 次 SSH 連線/斷線 →
      <strong v-if="doReset">④</strong><span v-if="doReset"> Serial 執行 restore_to_default → 等待重開機。</span>
      <span v-else>（Reset Default 已關閉，不執行恢復出廠）</span>
      設定 (DUT IP / Serial / Web 帳密) 請至 <strong>Settings</strong> 頁修改。
    </n-alert>

    <!-- ── Live Log ── -->
    <n-card v-if="liveLogContent" size="small">
      <template #header>
        <n-space align="center" :size="8">
          <span>Live Log</span>
          <n-badge v-if="isRunning" dot processing type="warning" />
          <n-text v-else depth="3" style="font-size:12px;">（已結束）</n-text>
        </n-space>
      </template>
      <div ref="liveLogEl" style="max-height:320px;overflow-y:auto;background:var(--n-color);border-radius:4px;padding:8px;">
        <pre style="font-size:11px;line-height:1.5;white-space:pre-wrap;margin:0;font-family:monospace;">{{ liveLogContent }}</pre>
      </div>
    </n-card>

    <!-- ── History ── -->
    <n-card title="SSH Stress History" size="small">
      <n-empty v-if="!runs.length" description="No SSH stress test runs yet" />
      <n-data-table
        v-else
        :columns="columns"
        :data="runs"
        :row-props="(row: Run) => ({ style: 'cursor:pointer;', onClick: () => openDetail(row) })"
        size="small"
        :bordered="false"
        :pagination="{ pageSize: 15 }"
      />
    </n-card>

    <!-- ── Detail modal ── -->
    <n-modal
      v-model:show="showModal"
      preset="card"
      :title="detail ? fmtDate(detail.timestamp) : 'Loading…'"
      style="width:820px;"
    >
      <n-spin v-if="loading" />
      <template v-else-if="detail">
        <n-space vertical :size="12">

          <!-- summary tags -->
          <n-space :size="8">
            <n-tag :type="detail.ssh_stress?.result === 'PASS' ? 'success' : 'error'">
              {{ detail.ssh_stress?.result || '—' }}
            </n-tag>
            <n-tag type="default">{{ detail.ssh_stress?.total ?? 0 }} cycles</n-tag>
            <n-tag type="success">✓ {{ detail.ssh_stress?.success ?? 0 }}</n-tag>
            <n-tag v-if="(detail.ssh_stress?.failure ?? 0) > 0" type="error">
              ✗ {{ detail.ssh_stress?.failure }}
            </n-tag>
          </n-space>

          <!-- per-iteration table -->
          <n-data-table
            v-if="detail.ssh_stress_detail?.iterations?.length"
            :columns="iterColumns"
            :data="detail.ssh_stress_detail.iterations"
            :row-props="(row: IterInfo) => ({ style: 'cursor:pointer;', onClick: () => selectedIter = row })"
            size="small"
            :bordered="false"
            max-height="220"
          />

          <!-- SSH cycle detail for selected iteration -->
          <template v-if="selectedIter">
            <n-divider>第 {{ selectedIter.iteration }} 輪 — SSH 連線明細</n-divider>
            <n-data-table
              :columns="sshCycleColumns"
              :data="selectedIter.ssh_cycles"
              size="small"
              :bordered="false"
              max-height="180"
            />
          </template>

          <!-- raw log -->
          <template v-if="detail.log">
            <n-divider>Log (last 8 KB)</n-divider>
            <n-scrollbar style="max-height:200px;">
              <pre style="font-size:11px;white-space:pre-wrap;margin:0;">{{ detail.log }}</pre>
            </n-scrollbar>
          </template>

        </n-space>
      </template>
    </n-modal>

  </n-space>
</template>

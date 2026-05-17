<script setup lang="ts">
import { h, ref, computed, onMounted } from 'vue'
import { NTag, useMessage } from 'naive-ui'
import { api, type Run, type RunDetail } from '@/api'
import { useAppStore } from '@/stores/app'

const store   = useAppStore()
const message = useMessage()

const runs       = ref<Run[]>([])
const detail     = ref<RunDetail | null>(null)
const showModal  = ref(false)
const loading    = ref(false)
const iterations = ref(10)

const isResetRunning = computed(() =>
  store.status.running && store.status.mode === 'reset'
)

onMounted(async () => {
  runs.value = (await api.runs()).filter((r: Run) => r.type === 'reset')
})

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
      { type: r.reset?.result === 'PASS' ? 'success' : 'error', size: 'small' },
      { default: () => r.reset?.result || '—' }),
  },
  { title: 'Cycles',  key: 'total',   width: 80,  render: (r: Run) => String(r.reset?.total   ?? r.total ?? '—') },
  { title: '✓ Pass',  key: 'success', width: 80,  render: (r: Run) => String(r.reset?.success ?? r.passed ?? '—') },
  { title: '✗ Fail',  key: 'failure', width: 80,  render: (r: Run) => String(r.reset?.failure ?? r.failed ?? '—') },
]

type IterInfo = {
  iteration: number
  result: string
  browser_ok: boolean
  serial_ok: boolean
  boot_detected: boolean
  boot_time_s: number
  serial_log?: string
}

const iterColumns = [
  { title: '#',         key: 'iteration',    width: 50 },
  {
    title: 'Result', key: 'result', width: 80,
    render: (it: IterInfo) => h(NTag,
      { type: it.result === 'PASS' ? 'success' : 'error', size: 'small' },
      { default: () => it.result }),
  },
  {
    title: 'Browser',  key: 'browser_ok',    width: 80,
    render: (it: IterInfo) => it.browser_ok  ? '✓' : '✗',
  },
  {
    title: 'Serial',   key: 'serial_ok',     width: 80,
    render: (it: IterInfo) => it.serial_ok   ? '✓' : '✗',
  },
  {
    title: 'Boot',     key: 'boot_detected', width: 80,
    render: (it: IterInfo) => it.boot_detected ? '✓' : '✗',
  },
  {
    title: 'Boot Time', key: 'boot_time_s',  width: 100,
    render: (it: IterInfo) => it.boot_time_s > 0 ? `${it.boot_time_s}s` : '—',
  },
]

async function openDetail(row: Run) {
  loading.value   = true
  showModal.value = true
  detail.value    = null
  try {
    detail.value = await api.runDetail(row.id)
  } finally {
    loading.value = false
  }
}

async function runTest() {
  const n = iterations.value
  const res = await store.trigger({ mode: 'reset', iterations: n })
  if (res?.status === 'already_running') {
    message.warning(`Already running (PID ${res.pid})`)
  } else {
    message.info(`Reset stress test started — ${n === 0 ? '∞' : n} cycles`)
    runs.value = (await api.runs()).filter((r: Run) => r.type === 'reset')
  }
}
</script>

<template>
  <n-space vertical :size="16">

    <!-- ── Actions ── -->
    <n-card size="small">
      <n-space align="center" :size="12">
        <n-input-number
          v-model:value="iterations"
          :min="0"
          :max="9999"
          style="width:130px;"
        >
          <template #prefix>Cycles</template>
        </n-input-number>
        <n-text depth="3" style="font-size:12px;">（0 = 無限循環）</n-text>

        <n-button
          type="warning"
          :disabled="store.status.running"
          @click="runTest"
        >
          🔁 Run Reset Test
        </n-button>

        <template v-if="isResetRunning">
          <n-divider vertical />
          <n-badge dot processing type="warning" />
          <n-text depth="3" style="font-size:13px;">Running… PID {{ store.status.pid }}</n-text>
          <n-button size="small" type="error" ghost @click="store.stop()">■ Stop</n-button>
        </template>
      </n-space>
    </n-card>

    <!-- ── Info ── -->
    <n-alert type="info" :bordered="false" style="font-size:13px;">
      每個 cycle：Browser 登入 DUT Web GUI → Serial 執行 restore_to_default → 等待重開機完成。
      設定 (IP / Serial port / Web 帳密) 可在 <strong>Settings</strong> 頁修改。
    </n-alert>

    <!-- ── History ── -->
    <n-card title="Reset Test History" size="small">
      <n-empty v-if="!runs.length" description="No reset test runs yet" />
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
      style="width:760px;"
    >
      <n-spin v-if="loading" />
      <template v-else-if="detail">
        <n-space vertical :size="12">

          <!-- summary -->
          <n-space :size="8">
            <n-tag :type="detail.reset?.result === 'PASS' ? 'success' : 'error'">
              {{ detail.reset?.result || '—' }}
            </n-tag>
            <n-tag type="default">{{ detail.reset?.total ?? 0 }} cycles</n-tag>
            <n-tag type="success">✓ {{ detail.reset?.success ?? 0 }}</n-tag>
            <n-tag v-if="(detail.reset?.failure ?? 0) > 0" type="error">
              ✗ {{ detail.reset?.failure }}
            </n-tag>
          </n-space>

          <!-- per-iteration table -->
          <n-data-table
            v-if="detail.reset_detail?.iterations?.length"
            :columns="iterColumns"
            :data="detail.reset_detail.iterations"
            size="small"
            :bordered="false"
            max-height="280"
          />

          <!-- raw log -->
          <template v-if="detail.log">
            <n-divider>Log (last 8 KB)</n-divider>
            <n-scrollbar style="max-height:240px;">
              <pre style="font-size:11px;white-space:pre-wrap;margin:0;">{{ detail.log }}</pre>
            </n-scrollbar>
          </template>

        </n-space>
      </template>
    </n-modal>

  </n-space>
</template>

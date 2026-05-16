<script setup lang="ts">
import { h, ref, onMounted } from 'vue'
import { NTag, useMessage } from 'naive-ui'
import { api, type Run, type RunDetail } from '@/api'
import { useAppStore } from '@/stores/app'

const store   = useAppStore()
const message = useMessage()

const runs      = ref<Run[]>([])
const detail    = ref<RunDetail | null>(null)
const showModal = ref(false)
const loading   = ref(false)

onMounted(async () => { runs.value = (await api.runs()).filter((r: Run) => r.type !== 'stability') })

function fmtDate(ts?: string) {
  if (!ts) return '—'
  const m = ts.match(/(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/)
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : ts
}

const columns = [
  { title: 'Timestamp', key: 'ts',     render: (r: Run) => fmtDate(r.timestamp) },
  {
    title: 'Result', key: 'result', width: 90,
    render: (r: Run) => h(NTag, { type: r.failed > 0 ? 'error' : 'success', size: 'small' },
      { default: () => r.failed > 0 ? '✗ FAIL' : '✓ PASS' }),
  },
  {
    title: 'Cases', key: 'cases',
    render: (r: Run) => `✓${r.passed}${r.failed > 0 ? ' ✗' + r.failed : ''} / ${r.total}`,
  },
  {
    title: 'AI Report', key: 'ai', width: 80,
    render: (r: Run) => r.has_ai_report ? h(NTag, { type: 'info', size: 'small' }, { default: () => '🤖 Yes' }) : '—',
  },
]

const caseColumns = [
  { title: 'Test Case', key: 'name' },
  {
    title: 'Status', key: 'status', width: 80,
    render: (c: { name: string; status: string; time: number; message?: string }) =>
      h(NTag, { type: c.status === 'PASS' ? 'success' : 'error', size: 'small' },
        { default: () => c.status }),
  },
  {
    title: 'Time (s)', key: 'time', width: 90,
    render: (c: { name: string; status: string; time: number }) => c.time.toFixed(1),
  },
  {
    title: 'Message', key: 'message',
    render: (c: { name: string; status: string; time: number; message?: string }) =>
      h('span', { style: 'font-size:12px;color:var(--n-text-color-3)' }, c.message || ''),
  },
]

async function openDetail(row: Run) {
  loading.value = true
  showModal.value = true
  detail.value = null
  try {
    detail.value = await api.runDetail(row.id)
  } finally {
    loading.value = false
  }
}

async function runTest() {
  const res = await store.trigger('rf')
  if (res?.status === 'already_running') message.warning(`Already running (PID ${res.pid})`)
  else message.info('RF test started')
}
</script>

<template>
  <n-space vertical :size="16">

    <!-- Actions -->
    <n-card size="small">
      <n-space align="center" :size="10">
        <n-button type="primary" :disabled="store.status.running" @click="runTest">
          📡 Run RF Tests
        </n-button>
        <template v-if="store.status.running && store.status.mode?.includes('rf')">
          <n-divider vertical />
          <n-badge dot processing type="warning" />
          <n-text depth="3" style="font-size:13px;">Running… PID {{ store.status.pid }}</n-text>
          <n-button size="small" type="error" ghost @click="store.stop()">■ Stop</n-button>
        </template>
      </n-space>
    </n-card>

    <!-- History table -->
    <n-card title="RF Test History" size="small">
      <n-data-table
        :columns="columns"
        :data="runs"
        :row-props="(row: Run) => ({ style: 'cursor:pointer;', onClick: () => openDetail(row) })"
        size="small"
        :bordered="false"
        :pagination="{ pageSize: 15 }"
      />
    </n-card>

    <!-- Detail modal -->
    <n-modal v-model:show="showModal" preset="card" :title="detail ? fmtDate(detail.timestamp) : 'Loading…'" style="width:720px;">
      <n-spin v-if="loading" />
      <template v-else-if="detail">
        <n-space vertical :size="12">
          <!-- summary tags -->
          <n-space :size="8">
            <n-tag :type="detail.failed > 0 ? 'error' : 'success'">
              {{ detail.failed > 0 ? `✗ ${detail.failed} failed` : '✓ All passed' }}
            </n-tag>
            <n-tag type="default">{{ detail.total }} total</n-tag>
            <n-tag v-if="detail.has_ai_report" type="info">🤖 AI report</n-tag>
          </n-space>

          <!-- case table -->
          <n-data-table
            :columns="caseColumns"
            :data="detail.cases"
            size="small"
            :bordered="false"
            max-height="300"
          />

          <!-- AI report -->
          <template v-if="detail.ai_report">
            <n-divider>AI Analysis</n-divider>
            <n-scrollbar style="max-height:260px;">
              <pre style="font-size:12px;white-space:pre-wrap;margin:0;">{{ detail.ai_report }}</pre>
            </n-scrollbar>
          </template>
        </n-space>
      </template>
    </n-modal>

  </n-space>
</template>

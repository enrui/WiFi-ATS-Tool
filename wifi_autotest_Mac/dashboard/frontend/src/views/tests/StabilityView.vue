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

onMounted(async () => { runs.value = (await api.runs()).filter((r: Run) => r.type === 'stability') })

function fmtDate(ts?: string) {
  if (!ts) return '—'
  const m = ts.match(/(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/)
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : ts
}

function fmtDuration(s?: number) {
  if (!s) return '—'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

const columns = [
  { title: 'Timestamp', key: 'ts',      render: (r: Run) => fmtDate(r.timestamp) },
  {
    title: 'Result', key: 'result', width: 90,
    render: (r: Run) => h(NTag,
      { type: r.stability?.result === 'PASS' ? 'success' : 'error', size: 'small' },
      { default: () => r.stability?.result || '—' }),
  },
  { title: 'Band',    key: 'band',   width: 70,  render: (r: Run) => r.stability?.band || '—' },
  { title: 'DL Avg',  key: 'dl',     width: 100, render: (r: Run) => r.stability ? r.stability.dl_avg_mbps + ' Mbps' : '—' },
  { title: 'UL Avg',  key: 'ul',     width: 100, render: (r: Run) => r.stability ? r.stability.ul_avg_mbps + ' Mbps' : '—' },
  { title: 'Drops',   key: 'drops',  width: 70,  render: (r: Run) => String(r.stability?.drops ?? '—') },
  { title: 'Checks',  key: 'checks', width: 70,  render: (r: Run) => String(r.stability?.checks ?? '—') },
  { title: 'Duration',key: 'dur',    width: 90,  render: (r: Run) => fmtDuration(r.stability?.duration_s) },
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
  const res = await store.trigger('stability')
  if (res?.status === 'already_running') message.warning(`Already running (PID ${res.pid})`)
  else message.info('Stability test started')
}
</script>

<template>
  <n-space vertical :size="16">

    <!-- Actions -->
    <n-card size="small">
      <n-space align="center" :size="10">
        <n-button :disabled="store.status.running" @click="runTest">
          ⏱ Run Stability Test
        </n-button>
        <template v-if="store.status.running && store.status.mode?.includes('stability')">
          <n-divider vertical />
          <n-badge dot processing type="warning" />
          <n-text depth="3" style="font-size:13px;">Running… PID {{ store.status.pid }}</n-text>
          <n-button size="small" type="error" ghost @click="store.stop()">■ Stop</n-button>
        </template>
      </n-space>
    </n-card>

    <!-- History table -->
    <n-card title="Stability Test History" size="small">
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
    <n-modal v-model:show="showModal" preset="card" :title="detail ? fmtDate(detail.timestamp) : 'Loading…'" style="width:640px;">
      <n-spin v-if="loading" />
      <template v-else-if="detail">
        <n-space vertical :size="12">
          <n-descriptions bordered :column="2" label-placement="left">
            <n-descriptions-item label="Result">
              <n-tag :type="detail.stability?.result === 'PASS' ? 'success' : 'error'">
                {{ detail.stability?.result || '—' }}
              </n-tag>
            </n-descriptions-item>
            <n-descriptions-item label="Band">{{ detail.stability?.band || '—' }}</n-descriptions-item>
            <n-descriptions-item label="DL Avg">{{ detail.stability?.dl_avg_mbps }} Mbps</n-descriptions-item>
            <n-descriptions-item label="UL Avg">{{ detail.stability?.ul_avg_mbps }} Mbps</n-descriptions-item>
            <n-descriptions-item label="Checks">{{ detail.stability?.checks }}</n-descriptions-item>
            <n-descriptions-item label="Drops">{{ detail.stability?.drops }}</n-descriptions-item>
            <n-descriptions-item label="Duration">{{ fmtDuration(detail.stability?.duration_s) }}</n-descriptions-item>
          </n-descriptions>

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

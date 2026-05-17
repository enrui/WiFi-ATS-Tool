<script setup lang="ts">
import { h, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NTag, useMessage } from 'naive-ui'
import { useAppStore } from '@/stores/app'
import type { Run } from '@/api'

const store   = useAppStore()
const router  = useRouter()
const message = useMessage()

onMounted(() => store.refresh())

const passRateType = computed(() => {
  const r = store.overallPassRate
  return r >= 90 ? 'success' : r >= 70 ? 'warning' : 'error'
})

function fmtDate(ts?: string) {
  if (!ts) return '—'
  const m = ts.match(/(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/)
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : ts
}

const rfColumns = [
  {
    title: 'Timestamp', key: 'timestamp',
    render: (r: Run) => fmtDate(r.timestamp),
  },
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
    title: 'AI', key: 'ai', width: 50,
    render: (r: Run) => r.has_ai_report ? '🤖' : '',
  },
]

const stabilityColumns = [
  { title: 'Timestamp', key: 'ts', render: (r: Run) => fmtDate(r.timestamp) },
  {
    title: 'Result', key: 'result', width: 90,
    render: (r: Run) => h(NTag, { type: r.stability?.result === 'PASS' ? 'success' : 'error', size: 'small' },
      { default: () => r.stability?.result || '—' }),
  },
  { title: 'DL Avg',  key: 'dl',     render: (r: Run) => r.stability ? r.stability.dl_avg_mbps + ' Mbps' : '—' },
  { title: 'Drops',   key: 'drops',  width: 70, render: (r: Run) => String(r.stability?.drops ?? '—') },
  { title: 'Checks',  key: 'checks', width: 70, render: (r: Run) => String(r.stability?.checks ?? '—') },
]

async function runTest(mode: string) {
  const res = await store.trigger({ mode })
  if (res?.status === 'already_running') message.warning(`Already running (PID ${res.pid})`)
}
</script>

<template>
  <n-space vertical :size="20">

    <!-- Stats -->
    <n-grid :cols="4" :x-gap="16">
      <n-gi>
        <n-card size="small">
          <n-statistic label="RF Runs" :value="store.rfRuns.length" />
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small">
          <n-statistic label="Pass Rate">
            <template #default>
              <n-text :type="passRateType" style="font-size:26px;font-weight:700;">
                {{ store.overallPassRate }}%
              </n-text>
            </template>
          </n-statistic>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small">
          <n-statistic label="Last RF Run">
            <template #default>
              <n-text style="font-size:13px;">{{ fmtDate(store.rfRuns[0]?.timestamp) }}</n-text>
            </template>
            <template #suffix>
              <n-tag
                v-if="store.rfRuns[0]"
                :type="store.rfRuns[0].failed > 0 ? 'error' : 'success'"
                size="small" style="margin-left:6px;"
              >
                {{ store.rfRuns[0].failed > 0 ? `${store.rfRuns[0].failed} failed` : 'All passed' }}
              </n-tag>
            </template>
          </n-statistic>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small">
          <n-statistic label="Last Stability">
            <template #default>
              <n-text style="font-size:13px;">{{ fmtDate(store.stabilityRuns[0]?.timestamp) }}</n-text>
            </template>
            <template #suffix>
              <n-tag
                v-if="store.stabilityRuns[0]"
                :type="store.stabilityRuns[0].stability?.result === 'PASS' ? 'success' : 'error'"
                size="small" style="margin-left:6px;"
              >
                {{ store.stabilityRuns[0].stability?.result || '—' }}
              </n-tag>
            </template>
          </n-statistic>
        </n-card>
      </n-gi>
    </n-grid>

    <!-- Quick Actions -->
    <n-card title="Quick Actions" size="small">
      <n-space :size="10" align="center">
        <n-button type="primary" :disabled="store.status.running" @click="runTest('rf')">
          📡 Run RF Tests
        </n-button>
        <n-button :disabled="store.status.running" @click="runTest('stability')">
          ⏱ Run Stability
        </n-button>
        <n-button :disabled="store.status.running" @click="runTest('rf stability')">
          🔁 RF + Soak
        </n-button>
        <template v-if="store.status.running">
          <n-divider vertical />
          <n-badge dot processing type="warning" />
          <n-text depth="3" style="font-size:13px;">
            Running {{ store.status.mode }} · PID {{ store.status.pid }}
          </n-text>
          <n-button size="small" type="error" ghost @click="store.stop()">■ Stop</n-button>
        </template>
      </n-space>
    </n-card>

    <!-- Recent RF Runs -->
    <n-card title="Recent RF Runs" size="small">
      <n-data-table
        :columns="rfColumns"
        :data="store.rfRuns.slice(0, 8)"
        :row-props="() => ({ style: 'cursor:pointer;', onClick: () => router.push('/tests/rf') })"
        size="small"
        :bordered="false"
      />
    </n-card>

    <!-- Recent Stability Runs -->
    <n-card v-if="store.stabilityRuns.length" title="Recent Stability Runs" size="small">
      <n-data-table
        :columns="stabilityColumns"
        :data="store.stabilityRuns.slice(0, 5)"
        :row-props="() => ({ style: 'cursor:pointer;', onClick: () => router.push('/tests/stability') })"
        size="small"
        :bordered="false"
      />
    </n-card>

  </n-space>
</template>

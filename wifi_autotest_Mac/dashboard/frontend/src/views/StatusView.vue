<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { api, type StationStatus } from '@/api'

const data  = ref<StationStatus | null>(null)
const error = ref(false)
let timer: ReturnType<typeof setInterval>

async function load() {
  try {
    data.value  = await api.stationStatus()
    error.value = false
  } catch {
    error.value = true
  }
}

onMounted(() => { load(); timer = setInterval(load, 5000) })
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <n-space vertical :size="20">

    <n-alert v-if="error" type="error" title="Cannot reach backend" :bordered="false" />

    <!-- Node connectivity -->
    <n-card title="Node Connectivity" size="small">
      <n-skeleton v-if="!data" :repeat="2" text />
      <n-grid v-else :cols="2" :x-gap="16" :y-gap="12">

        <n-gi>
          <n-card size="small" embedded>
            <n-space align="center" :size="10">
              <n-badge
                :type="data.nodes.dut.ok ? 'success' : 'error'"
                :processing="!data.nodes.dut.ok"
                dot
              />
              <div>
                <div style="font-weight:600;">DUT</div>
                <n-text depth="3" style="font-size:12px;">{{ data.nodes.dut.ip }}</n-text>
              </div>
              <n-tag :type="data.nodes.dut.ok ? 'success' : 'error'" size="small" style="margin-left:auto;">
                {{ data.nodes.dut.ok ? 'Online' : 'Offline' }}
              </n-tag>
            </n-space>
          </n-card>
        </n-gi>

        <n-gi>
          <n-card size="small" embedded>
            <n-space align="center" :size="10">
              <n-badge
                :type="data.nodes.bpi.ok ? 'success' : 'error'"
                :processing="!data.nodes.bpi.ok"
                dot
              />
              <div>
                <div style="font-weight:600;">BPI (Tester)</div>
                <n-text depth="3" style="font-size:12px;">{{ data.nodes.bpi.ip }}</n-text>
              </div>
              <n-tag :type="data.nodes.bpi.ok ? 'success' : 'error'" size="small" style="margin-left:auto;">
                {{ data.nodes.bpi.ok ? 'Online' : 'Offline' }}
              </n-tag>
            </n-space>
          </n-card>
        </n-gi>

      </n-grid>
    </n-card>

    <!-- API Key -->
    <n-card title="AI Integration" size="small">
      <n-skeleton v-if="!data" text :repeat="1" />
      <n-space v-else align="center" :size="12">
        <n-badge :type="data.api_key.set ? 'success' : 'warning'" dot />
        <span v-if="data.api_key.set">
          API Key set &nbsp;
          <n-text code depth="3">{{ data.api_key.preview }}</n-text>
        </span>
        <n-text v-else type="warning">API Key not configured — AI report disabled</n-text>
      </n-space>
    </n-card>

    <!-- Python packages -->
    <n-card title="Python Environment" size="small">
      <n-skeleton v-if="!data" text :repeat="3" />
      <n-grid v-else :cols="4" :x-gap="12" :y-gap="8">
        <n-gi v-for="(ok, pkg) in data.packages" :key="pkg">
          <n-space align="center" :size="6">
            <n-icon :color="ok ? '#18a058' : '#d03050'">
              <svg v-if="ok" viewBox="0 0 24 24"><path fill="currentColor" d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
              <svg v-else viewBox="0 0 24 24"><path fill="currentColor" d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
            </n-icon>
            <n-text :depth="ok ? 1 : 3" style="font-size:13px;">{{ pkg }}</n-text>
          </n-space>
        </n-gi>
      </n-grid>
    </n-card>

    <n-text depth="3" style="font-size:11px;">Auto-refreshes every 5 s</n-text>
  </n-space>
</template>

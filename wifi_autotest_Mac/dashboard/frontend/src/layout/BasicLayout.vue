<script setup lang="ts">
import { h, ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { NIcon, type MenuOption } from 'naive-ui'
import {
  GridOutline, PulseOutline, SettingsOutline,
  FlaskOutline, WifiOutline, TimerOutline,
} from '@vicons/ionicons5'
import { useAppStore } from '@/stores/app'

const store  = useAppStore()
const router = useRouter()
const route  = useRoute()

const collapsed = ref(false)
const activeKey = computed(() => route.path)

function icon(c: unknown) {
  return () => h(NIcon, null, { default: () => h(c as any) })
}

const menuOptions: MenuOption[] = [
  { label: 'Dashboard', key: '/dashboard',       icon: icon(GridOutline) },
  { label: 'Status',    key: '/status',           icon: icon(PulseOutline) },
  { label: 'Settings',  key: '/settings',         icon: icon(SettingsOutline) },
  {
    label: 'Tests', key: 'tests', icon: icon(FlaskOutline),
    children: [
      { label: 'RF Tests',   key: '/tests/rf',        icon: icon(WifiOutline) },
      { label: 'Stability',  key: '/tests/stability', icon: icon(TimerOutline) },
    ],
  },
]

function handleMenu(key: string) {
  if (!key.startsWith('/')) return
  router.push(key)
}

// ── polling ──────────────────────────────────────────────────
let timer: ReturnType<typeof setInterval>
onMounted(async () => {
  await store.refresh()
  timer = setInterval(() => store.pollStatus(), 3000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <n-layout has-sider style="height: 100vh;">

    <!-- ── Sidebar ── -->
    <n-layout-sider
      bordered
      collapse-mode="width"
      :collapsed-width="64"
      :width="210"
      :collapsed="collapsed"
      show-trigger
      @collapse="collapsed = true"
      @expand="collapsed = false"
    >
      <!-- Logo -->
      <div
        class="logo"
        :style="{ padding: collapsed ? '16px 0' : '14px 16px', textAlign: collapsed ? 'center' : 'left', borderBottom: '1px solid var(--n-border-color)' }"
      >
        <n-icon size="20" color="#58a6ff" style="vertical-align:middle;"><WifiOutline /></n-icon>
        <span v-if="!collapsed" style="font-weight:700;font-size:14px;margin-left:8px;vertical-align:middle;">WiFi-ATS</span>
      </div>

      <n-menu
        :collapsed="collapsed"
        :collapsed-width="64"
        :options="menuOptions"
        :value="activeKey"
        :default-expanded-keys="['tests']"
        accordion
        @update:value="handleMenu"
      />

      <div
        v-if="!collapsed"
        style="position:absolute;bottom:12px;left:0;right:0;text-align:center;font-size:11px;opacity:.4;"
      >
        Phase 1 · v1.0
      </div>
    </n-layout-sider>

    <!-- ── Main ── -->
    <n-layout>

      <!-- Header -->
      <n-layout-header
        bordered
        style="height:48px;display:flex;align-items:center;padding:0 20px;justify-content:space-between;"
      >
        <!-- Status indicator -->
        <n-space align="center" :size="10">
          <n-badge
            :processing="store.status.running"
            :type="store.status.running ? 'warning' : 'default'"
            dot
          />
          <n-text depth="3" style="font-size:13px;">
            {{ store.status.running ? `Running · PID ${store.status.pid}` : 'Idle' }}
          </n-text>
          <n-text v-if="!store.status.running && store.runs[0]" depth="3" style="font-size:11px;">
            Last: {{ store.runs[0]?.timestamp?.replace(/(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2}).*/, '$1-$2-$3 $4:$5') }}
          </n-text>
        </n-space>

        <!-- Actions -->
        <n-space :size="8">
          <n-button
            v-if="store.status.running"
            size="small" type="error" ghost
            @click="store.stop()"
          >
            ■ Stop
          </n-button>
          <n-button size="small" ghost @click="store.refresh()">↻</n-button>
        </n-space>
      </n-layout-header>

      <!-- Content -->
      <n-layout-content
        :content-style="{ padding: '20px', minHeight: 'calc(100vh - 48px)' }"
        style="overflow-y:auto;"
      >
        <RouterView />
      </n-layout-content>

    </n-layout>
  </n-layout>
</template>

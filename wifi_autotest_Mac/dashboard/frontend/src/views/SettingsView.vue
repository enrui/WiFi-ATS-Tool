<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '@/api'
import { useAppStore } from '@/stores/app'

const store   = useAppStore()
const message = useMessage()

const apiKey   = ref('')
const preview  = ref('')
const keySet   = ref(false)
const visible  = ref(false)
const saving   = ref(false)

onMounted(async () => {
  const s   = await api.settings()
  keySet.value  = s.api_key_set
  preview.value = s.api_key_preview
})

async function save() {
  if (!apiKey.value.trim()) return
  saving.value = true
  try {
    await api.saveSettings({ api_key: apiKey.value.trim() })
    keySet.value  = true
    preview.value = apiKey.value.trim().slice(0, 8) + '…'
    apiKey.value  = ''
    message.success('API key saved')
  } catch {
    message.error('Failed to save')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <n-space vertical :size="20">

    <!-- Theme -->
    <n-card title="Appearance" size="small">
      <n-space :size="16">
        <n-card
          v-for="t in (['dark', 'light'] as const)"
          :key="t"
          size="small"
          embedded
          :style="{
            cursor: 'pointer',
            border: store.theme === t ? '2px solid var(--n-primary-color)' : '2px solid transparent',
            width: '120px',
          }"
          @click="store.setTheme(t)"
        >
          <!-- mini preview swatch -->
          <div
            :style="{
              height: '52px',
              borderRadius: '4px',
              background: t === 'dark' ? '#18181c' : '#f7f6f1',
              marginBottom: '8px',
              display: 'flex',
              flexDirection: 'column',
              gap: '4px',
              padding: '6px',
            }"
          >
            <div :style="{ height:'8px', borderRadius:'3px', background: t === 'dark' ? '#3a3a40' : '#dddbd4', width:'80%' }" />
            <div :style="{ height:'8px', borderRadius:'3px', background: t === 'dark' ? '#2a7bff' : '#c9932a', width:'55%' }" />
            <div :style="{ height:'8px', borderRadius:'3px', background: t === 'dark' ? '#3a3a40' : '#dddbd4', width:'65%' }" />
          </div>
          <n-text style="font-size:13px;text-transform:capitalize;">{{ t }}</n-text>
          <n-icon v-if="store.theme === t" color="#18a058" style="margin-left:4px;vertical-align:middle;" size="14">
            <svg viewBox="0 0 24 24"><path fill="currentColor" d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
          </n-icon>
        </n-card>
      </n-space>
    </n-card>

    <!-- API Key -->
    <n-card title="AI Analysis — Anthropic API Key" size="small">
      <n-space vertical :size="12">
        <n-space v-if="keySet" align="center" :size="8">
          <n-badge type="success" dot />
          <n-text>Key configured &nbsp;</n-text>
          <n-text code depth="3">{{ preview }}</n-text>
        </n-space>
        <n-text v-else type="warning" depth="2">No API key set — AI report will be skipped</n-text>

        <n-input-group>
          <n-input
            v-model:value="apiKey"
            :type="visible ? 'text' : 'password'"
            placeholder="sk-ant-…"
            style="font-family:monospace;"
            @keyup.enter="save"
          />
          <n-button ghost @click="visible = !visible">{{ visible ? '🙈' : '👁' }}</n-button>
          <n-button type="primary" :loading="saving" @click="save">Save</n-button>
        </n-input-group>

        <n-text depth="3" style="font-size:12px;">
          Stored in <n-text code>.env</n-text> as <n-text code>ANTHROPIC_API_KEY</n-text>
        </n-text>
      </n-space>
    </n-card>

  </n-space>
</template>

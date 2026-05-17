<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { api, type SaveSettingsReq } from '@/api'
import { useAppStore } from '@/stores/app'

const store   = useAppStore()
const message = useMessage()

// ── API Key ──────────────────────────────────────────────────────────────────
const apiKey   = ref('')
const preview  = ref('')
const keySet   = ref(false)
const visible  = ref(false)
const saving   = ref(false)

// ── Network / Serial / Web ───────────────────────────────────────────────────
const dutIp      = ref('')
const bpiIp      = ref('')
const serialPort = ref('')
const serialBaud = ref(115200)
const webHost    = ref('')
const webUser    = ref('')
const webPass    = ref('')
const webVisible = ref(false)
const netSaving  = ref(false)

onMounted(async () => {
  const s      = await api.settings()
  keySet.value  = s.api_key_set
  preview.value = s.api_key_preview
  dutIp.value      = s.dut_ip
  bpiIp.value      = s.bpi_ip
  serialPort.value = s.serial_port
  serialBaud.value = s.serial_baud
  webHost.value    = s.web_host
  webUser.value    = s.web_user
  webPass.value    = s.web_password
})

async function saveApiKey() {
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

async function saveNetwork() {
  netSaving.value = true
  try {
    const req: SaveSettingsReq = {
      dut_ip:       dutIp.value,
      bpi_ip:       bpiIp.value,
      serial_port:  serialPort.value,
      serial_baud:  serialBaud.value,
      web_host:     webHost.value,
      web_user:     webUser.value,
      web_password: webPass.value,
    }
    await api.saveSettings(req)
    message.success('Settings saved to config.yaml')
  } catch {
    message.error('Failed to save')
  } finally {
    netSaving.value = false
  }
}
</script>

<template>
  <n-space vertical :size="20">

    <!-- ── Appearance ── -->
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
          <div :style="{
            height: '52px', borderRadius: '4px', marginBottom: '8px',
            background: t === 'dark' ? '#18181c' : '#f7f6f1',
            display: 'flex', flexDirection: 'column', gap: '4px', padding: '6px',
          }">
            <div :style="{ height:'8px', borderRadius:'3px', width:'80%',
              background: t === 'dark' ? '#3a3a40' : '#dddbd4' }" />
            <div :style="{ height:'8px', borderRadius:'3px', width:'55%',
              background: t === 'dark' ? '#2a7bff' : '#c9932a' }" />
            <div :style="{ height:'8px', borderRadius:'3px', width:'65%',
              background: t === 'dark' ? '#3a3a40' : '#dddbd4' }" />
          </div>
          <n-text style="font-size:13px;text-transform:capitalize;">{{ t }}</n-text>
          <n-icon v-if="store.theme === t" color="#18a058" style="margin-left:4px;vertical-align:middle;" size="14">
            <svg viewBox="0 0 24 24"><path fill="currentColor" d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
          </n-icon>
        </n-card>
      </n-space>
    </n-card>

    <!-- ── Network & Device ── -->
    <n-card title="Network & Device" size="small">
      <n-space vertical :size="14">
        <n-grid :cols="2" :x-gap="12">
          <n-gi>
            <n-form-item label="DUT IP (SSH)" :show-feedback="false">
              <n-input v-model:value="dutIp" placeholder="192.168.99.1" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="BPI IP (Tester)" :show-feedback="false">
              <n-input v-model:value="bpiIp" placeholder="192.168.99.100" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="Serial Port" :show-feedback="false">
              <n-input v-model:value="serialPort" placeholder="/dev/tty.usbserial-0001" style="font-family:monospace;" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="Serial Baud" :show-feedback="false">
              <n-input-number v-model:value="serialBaud" :min="9600" :max="921600" style="width:100%;" />
            </n-form-item>
          </n-gi>
        </n-grid>

        <n-divider style="margin:4px 0;">Web GUI Login (Reset Stress Test)</n-divider>

        <n-grid :cols="3" :x-gap="12">
          <n-gi>
            <n-form-item label="Web Host IP" :show-feedback="false">
              <n-input v-model:value="webHost" placeholder="192.168.1.1" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="Username" :show-feedback="false">
              <n-input v-model:value="webUser" placeholder="admin" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="Password" :show-feedback="false">
              <n-input-group>
                <n-input
                  v-model:value="webPass"
                  :type="webVisible ? 'text' : 'password'"
                  placeholder="admin"
                />
                <n-button ghost @click="webVisible = !webVisible">{{ webVisible ? '🙈' : '👁' }}</n-button>
              </n-input-group>
            </n-form-item>
          </n-gi>
        </n-grid>

        <n-button type="primary" :loading="netSaving" @click="saveNetwork">
          Save to config.yaml
        </n-button>
      </n-space>
    </n-card>

    <!-- ── AI API Key ── -->
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
            @keyup.enter="saveApiKey"
          />
          <n-button ghost @click="visible = !visible">{{ visible ? '🙈' : '👁' }}</n-button>
          <n-button type="primary" :loading="saving" @click="saveApiKey">Save</n-button>
        </n-input-group>

        <n-text depth="3" style="font-size:12px;">
          Stored in <n-text code>.env</n-text> as <n-text code>ANTHROPIC_API_KEY</n-text>
        </n-text>
      </n-space>
    </n-card>

  </n-space>
</template>

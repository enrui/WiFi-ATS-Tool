<script setup lang="ts">
import { computed } from 'vue'
import { darkTheme, lightTheme, NConfigProvider, NMessageProvider, NGlobalStyle } from 'naive-ui'
import { RouterView } from 'vue-router'
import { useAppStore } from '@/stores/app'

const store = useAppStore()
const theme = computed(() => store.theme === 'light' ? lightTheme : darkTheme)
</script>

<template>
  <n-config-provider :theme="theme" :theme-overrides="store.themeOverrides">
    <n-global-style />
    <n-message-provider>
      <RouterView />
    </n-message-provider>
  </n-config-provider>
</template>

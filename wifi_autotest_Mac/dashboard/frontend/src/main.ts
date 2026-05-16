import { createApp } from 'vue'
import { createPinia } from 'pinia'
import naive from 'naive-ui'
import router from './router'
import App from './App.vue'
import 'vfonts/Lato.css'

createApp(App).use(createPinia()).use(router).use(naive).mount('#app')

import { createRouter, createWebHashHistory } from 'vue-router'
import BasicLayout from '@/layout/BasicLayout.vue'

export default createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      component: BasicLayout,
      redirect: '/dashboard',
      children: [
        { path: 'dashboard',        component: () => import('@/views/DashboardView.vue') },
        { path: 'status',           component: () => import('@/views/StatusView.vue') },
        { path: 'settings',         component: () => import('@/views/SettingsView.vue') },
        { path: 'tests/rf',         component: () => import('@/views/tests/RFTestsView.vue') },
        { path: 'tests/stability',  component: () => import('@/views/tests/StabilityView.vue') },
        { path: 'stress/reset',     component: () => import('@/views/stress/ResetTestView.vue') },
      ],
    },
  ],
})

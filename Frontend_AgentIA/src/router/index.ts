import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/Login.vue') },
    { path: '/', name: 'situation', component: () => import('@/views/Synthese.vue') },
    { path: '/importer', name: 'importer', component: () => import('@/views/Importer.vue') },
    { path: '/tableau', name: 'tableau', component: () => import('@/views/Dashboard.vue') },
    { path: '/tickets/:id', name: 'ticket', component: () => import('@/views/Ticket.vue') },
    { path: '/chat', name: 'chat', component: () => import('@/views/Chat.vue') },
    { path: '/admin', name: 'admin', component: () => import('@/views/Admin.vue') },
  ],
})

// Accès réservé au haut responsable
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.name !== 'login' && !auth.isAuthenticated) return { name: 'login' }
  return true
})

export default router

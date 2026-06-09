import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { requiresAuth: false },
    },
    {
      path: '/',
      redirect: '/query',
    },
    {
      path: '/query',
      name: 'query',
      component: () => import('@/views/QueryView.vue'),
    },
    {
      path: '/upload',
      name: 'upload',
      component: () => import('@/views/UploadView.vue'),
    },
    {
      path: '/documents',
      name: 'documents',
      component: () => import('@/views/DocumentsView.vue'),
    },
    {
      path: '/banks',
      name: 'banks',
      component: () => import('@/views/BanksView.vue'),
    },
    {
      path: '/documents/:id',
      name: 'document-detail',
      component: () => import('@/views/DocumentDetail.vue'),
    },
    {
      path: '/synonyms',
      name: 'synonyms',
      component: () => import('@/views/SynonymsView.vue'),
    },
    {
      path: '/admin',
      name: 'admin',
      component: () => import('@/views/AdminView.vue'),
    },
    {
      path: '/wiki',
      name: 'wiki',
      component: () => import('@/views/WikiView.vue'),
    },
  ],
})

// Navigation guard: redirect to /login if not authenticated
router.beforeEach((to) => {
  const token = localStorage.getItem('kb2_token')
  if (to.name === 'login') {
    // Already logged in → redirect to query
    if (token) return { name: 'query' }
    return true
  }
  // All other routes require auth
  if (!token) return { name: 'login' }
  return true
})

export default router

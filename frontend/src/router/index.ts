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
      meta: { requiresAdmin: true },
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
      meta: { requiresAdmin: true },
    },
    {
      path: '/wiki',
      name: 'wiki',
      component: () => import('@/views/WikiView.vue'),
    },
    {
      path: '/wiki-entries',
      name: 'wikiEntries',
      component: () => import('@/views/WikiEntryView.vue'),
    },
    {
      path: '/extract',
      name: 'extract',
      component: () => import('@/views/ExtractView.vue'),
    },
    {
      path: '/lifecycle',
      name: 'lifecycle',
      component: () => import('@/views/LifecycleView.vue'),
      meta: { requiresAdmin: true },
    },
  ],
})

// Navigation guard: redirect to /login if not authenticated
router.beforeEach((to) => {
  const token = localStorage.getItem('kb2_token')
  const role = localStorage.getItem('kb2_role')

  if (to.name === 'login') {
    // Already logged in → redirect to query
    if (token) return { name: 'query' }
    return true
  }

  // All other routes require auth
  if (!token) return { name: 'login' }

  // Admin-only routes: reject non-admin viewers
  if (to.meta.requiresAdmin && role !== 'admin') {
    return { name: 'query' }
  }

  return true
})

export default router

import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
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
  ],
})

export default router

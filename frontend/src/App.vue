<template>
  <div v-if="isLoginRoute" class="login-layout">
    <RouterView />
  </div>
  <div v-else class="app-layout">
    <AppHeader />
    <AppSidebar />
    <main class="app-main">
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import AppSidebar from '@/components/AppSidebar.vue'

const route = useRoute()
const isLoginRoute = computed(() => route.name === 'login')
</script>

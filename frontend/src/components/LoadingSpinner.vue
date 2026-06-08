<template>
  <div class="spinner-wrap" :class="{ inline }">
    <div class="spinner"></div>
    <span v-if="label" class="spinner-label">{{ label }}</span>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    label?: string
    inline?: boolean
  }>(),
  {
    label: '',
    inline: false,
  },
)
</script>

<style scoped>
.spinner-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 2rem;
}

.spinner-wrap.inline {
  flex-direction: row;
  padding: 0;
}

.spinner {
  width: 24px;
  height: 24px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.spinner-label {
  font-size: 0.8rem;
  color: var(--fg-muted);
}
</style>

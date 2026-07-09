<template>
  <div class="spinner-wrap" :class="{ inline }">
    <div class="spinner"></div>
    <span v-if="label" class="spinner-label">{{ label }}</span>
    <span v-if="elapsed !== undefined" class="spinner-elapsed">已耗时 {{ elapsed }} 秒</span>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    label?: string
    inline?: boolean
    elapsed?: number
  }>(),
  {
    label: '',
    inline: false,
    elapsed: undefined,
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
.spinner-elapsed {
  font-size: 0.75rem;
  color: var(--fg-muted);
  font-variant-numeric: tabular-nums;
}
</style>

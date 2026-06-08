<template>
  <Transition name="toast-fade">
    <div v-if="visible" class="toast" :class="type">
      <span class="toast-msg">{{ message }}</span>
      <button class="toast-close" @click="close">&times;</button>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    message: string
    type?: 'info' | 'success' | 'error' | 'warning'
    duration?: number
  }>(),
  {
    type: 'info',
    duration: 3000,
  },
)

const emit = defineEmits<{
  (e: 'close'): void
}>()

const visible = ref(false)

watch(
  () => props.message,
  (val) => {
    if (val) {
      visible.value = true
      if (props.duration > 0) {
        setTimeout(() => close(), props.duration)
      }
    }
  },
  { immediate: true },
)

function close() {
  visible.value = false
  emit('close')
}
</script>

<style scoped>
.toast {
  position: fixed;
  top: calc(var(--header-h) + 0.75rem);
  right: 1rem;
  padding: 0.6rem 1rem;
  border: 1px solid var(--border);
  background: white;
  font-size: 0.85rem;
  z-index: 200;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  max-width: 360px;
}

.toast.success {
  border-color: var(--success);
  color: var(--success);
}

.toast.error {
  border-color: var(--danger);
  color: var(--danger);
}

.toast.warning {
  border-color: var(--warning);
  color: var(--warning);
}

.toast-msg {
  flex: 1;
}

.toast-close {
  border: none;
  background: transparent;
  font-size: 1.1rem;
  color: var(--fg-muted);
  padding: 0;
  line-height: 1;
}

.toast-fade-enter-active,
.toast-fade-leave-active {
  transition: opacity 0.2s;
}

.toast-fade-enter-from,
.toast-fade-leave-to {
  opacity: 0;
}
</style>

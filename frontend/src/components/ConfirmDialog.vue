<template>
  <Teleport to="body">
    <div v-if="visible" class="confirm-overlay" @click.self="onCancel">
      <div class="confirm-dialog card">
        <p class="confirm-message">{{ message }}</p>
        <div class="confirm-actions">
          <button @click="onCancel">取消</button>
          <button class="danger" @click="onConfirm">{{ confirmText }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
defineProps<{
  visible: boolean
  message: string
  confirmText?: string
}>()

const emit = defineEmits<{ confirm: []; cancel: [] }>()

function onConfirm() { emit('confirm') }
function onCancel() { emit('cancel') }
</script>

<style scoped>
.confirm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.confirm-dialog {
  max-width: 400px;
  width: 90%;
  padding: 1.5rem;
  box-shadow: var(--shadow-lg);
}

.confirm-message {
  font-size: 0.95rem;
  line-height: 1.5;
  margin-bottom: 1.25rem;
  color: var(--fg);
}

.confirm-actions {
  display: flex;
  gap: 0.5rem;
  justify-content: flex-end;
}
</style>

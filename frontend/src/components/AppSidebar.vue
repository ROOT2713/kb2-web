<template>
  <aside class="app-sidebar">
    <div class="sidebar-section">
      <h3 class="sidebar-title">知识库</h3>
      <div class="bank-list">
        <button
          v-for="bank in store.banks"
          :key="bank.key"
          class="bank-item"
          :class="{ active: store.selectedBank === bank.key }"
          @click="store.selectBank(bank.key)"
        >
          <span class="bank-name">{{ bank.name }}</span>
          <span class="bank-count">{{ bank.count }}</span>
        </button>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useBanksStore } from '@/stores/banks'

const store = useBanksStore()

onMounted(() => {
  if (store.banks.length === 0) {
    store.fetchBanks()
  }
})
</script>

<style scoped>
.app-sidebar {
  position: fixed;
  top: var(--header-h);
  left: 0;
  bottom: 0;
  width: var(--sidebar-w);
  background: var(--bg-alt);
  border-right: 1px solid var(--border);
  overflow-y: auto;
  padding: 1rem 0;
  z-index: 90;
}

.sidebar-title {
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--fg-muted);
  padding: 0 1rem;
  margin-bottom: 0.5rem;
}

.bank-list {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.bank-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 0;
  background: transparent;
  font-size: 0.825rem;
  text-align: left;
  transition: background 0.1s;
}

.bank-item:hover {
  background: hsl(220, 15%, 92%);
}

.bank-item.active {
  background: var(--accent-light);
  color: var(--accent);
  font-weight: 600;
}

.bank-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bank-count {
  font-size: 0.7rem;
  color: var(--fg-muted);
  border: 1px solid var(--border);
  padding: 0 0.35rem;
  border-radius: var(--radius);
  background: white;
}

@media (max-width: 768px) {
  .app-sidebar {
    display: none;
  }
}
</style>

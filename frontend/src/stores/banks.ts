import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  listBanks as apiListBanks,
  createBank as apiCreateBank,
  deleteBank as apiDeleteBank,
  type BankItem,
} from '@/services/banks'

export const useBanksStore = defineStore('banks', () => {
  const banks = ref<BankItem[]>([])
  const loading = ref(false)
  const error = ref('')
  const selectedBank = ref('all')

  async function fetchBanks() {
    loading.value = true
    error.value = ''
    try {
      const data = await apiListBanks()
      banks.value = data.banks
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '加载知识库失败'
    } finally {
      loading.value = false
    }
  }

  async function addBank(payload: {
    key: string
    label: string
    description?: string
    prompt?: string
  }) {
    try {
      await apiCreateBank(payload)
      await fetchBanks()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '创建知识库失败'
      throw e
    }
  }

  async function removeBank(bankKey: string, confirm = false) {
    try {
      await apiDeleteBank(bankKey, confirm)
      await fetchBanks()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '删除知识库失败'
      throw e
    }
  }

  function selectBank(key: string) {
    selectedBank.value = key
  }

  return {
    banks,
    loading,
    error,
    selectedBank,
    fetchBanks,
    addBank,
    removeBank,
    selectBank,
  }
})

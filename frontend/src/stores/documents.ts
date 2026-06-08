import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  listDocuments as apiListDocuments,
  deleteDocument as apiDeleteDocument,
  reparseDocument as apiReparseDocument,
  type DocumentItem,
} from '@/services/documents'

export const useDocumentsStore = defineStore('documents', () => {
  const documents = ref<DocumentItem[]>([])
  const loading = ref(false)
  const error = ref('')

  async function fetchDocuments(bank = 'all') {
    loading.value = true
    error.value = ''
    try {
      const data = await apiListDocuments(bank)
      documents.value = data.documents
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '加载文档失败'
    } finally {
      loading.value = false
    }
  }

  async function removeDocument(docId: string) {
    try {
      await apiDeleteDocument(docId)
      documents.value = documents.value.filter((d) => d.id !== docId)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '删除失败'
      throw e
    }
  }

  async function reparse(docId: string) {
    try {
      return await apiReparseDocument(docId)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '重新解析失败'
      throw e
    }
  }

  return { documents, loading, error, fetchDocuments, removeDocument, reparse }
})

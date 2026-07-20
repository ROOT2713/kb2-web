import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  listDocuments as apiListDocuments,
  deleteDocument as apiDeleteDocument,
  reparseDocument as apiReparseDocument,
  patchDocument as apiPatchDocument,
  type DocumentItem,
} from '@/services/documents'
import { getCategories as apiGetCategories, type CategoryItem } from '@/services/admin'

export const useDocumentsStore = defineStore('documents', () => {
  const documents = ref<DocumentItem[]>([])
  const loading = ref(false)
  const error = ref('')
  const categories = ref<CategoryItem[]>([])

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

  async function fetchCategories() {
    try {
      categories.value = await apiGetCategories()
    } catch (e: unknown) {
      console.error('获取分类失败', e)
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

  async function patchDocumentAction(docId: string, payload: { title?: string; category?: string; subcategory?: string }) {
    const result = await apiPatchDocument(docId, payload)
    // Update local state
    const idx = documents.value.findIndex((d) => d.id === docId)
    if (idx !== -1) {
      if (payload.title !== undefined) documents.value[idx].title = payload.title
      if (payload.category !== undefined) documents.value[idx].category = payload.category
      if (payload.subcategory !== undefined) documents.value[idx].subcategory = payload.subcategory
    }
    return result
  }

  return {
    documents, loading, error, categories,
    fetchDocuments, fetchCategories, removeDocument, reparse,
    patchDocument: patchDocumentAction,
  }
})

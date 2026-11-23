import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/services/api'

/** Modèle d'IA actif, partagé entre la barre supérieure et l'administration : un changement de modèle s'affiche tout de suite. */
export const useLlmStore = defineStore('llm', () => {
  const info = ref<{ hote: string; local: boolean; modele: string } | null>(null)
  async function refresh() {
    try { info.value = await api('/admin/llm') } catch { /* le bandeau reste masqué */ }
  }
  return { info, refresh }
})

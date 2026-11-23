import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/services/api'

export interface Membre { id: number; nom: string; photo?: string | null }
export interface Projet {
  id: number
  nom: string
  statut: string
  date_limite: string | null
  nb_tickets: number
  nb_en_retard: number
  nb_a_surveiller: number
  nb_fermes: number
  avancement: number
  prochaine_echeance: string | null
  equipe: Membre[]
}

/** Projet actif : tableau de bord, situation, évaluation, historique, analyses, chat et rapports se rapportent toujours à lui (2.6).
 *  Il n'y a AUCUN projet par défaut : le responsable le choisit sur la page de transition (/projets), après le cahier des charges. */
export const useProjectStore = defineStore('project', () => {
  const projets = ref<Projet[]>([])
  const activeId = ref<number | null>(Number(sessionStorage.getItem('projet_actif')) || null)
  const recentId = ref<number | null>(null)          // projet qui vient d'être créé (mis en avant sur la page de transition)
  const loaded = ref(false)
  const error = ref('')
  const active = computed(() => projets.value.find((p) => p.id === activeId.value) ?? null)

  async function load() {
    try {
      projets.value = await api<Projet[]>('/projets')
      error.value = ''
      if (activeId.value && !active.value) select(null)     // projet supprimé entre-temps : retour au choix du projet
    } catch (e: any) {
      error.value = e.message
    }
    loaded.value = true
  }
  function select(id: number | null) {
    activeId.value = id
    if (id) sessionStorage.setItem('projet_actif', String(id))
    else sessionStorage.removeItem('projet_actif')
  }
  return { projets, activeId, active, recentId, loaded, error, load, select }
})

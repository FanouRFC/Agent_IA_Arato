import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/services/api'

/** Analyse d'un cahier des charges EN COURS. Vit dans le store (et non dans la page) : quitter la page d'import, ou la recharger côté
 *  interface, n'interrompt pas l'analyse et ne fait pas disparaître son suivi ; à son retour, la page retrouve l'analyse ou son résultat. */
export const useAnalyseStore = defineStore('analyse', () => {
  const busy = ref(false)
  const nom = ref(''), fichierNom = ref(''), depart = ref(0)
  const cahier = ref<any>(null)      // résultat prêt à être repris par la page
  const erreur = ref('')

  async function lancer(form: FormData, nomProjet: string, nomFichier: string) {
    if (busy.value) return
    busy.value = true; erreur.value = ''; cahier.value = null
    nom.value = nomProjet; fichierNom.value = nomFichier; depart.value = Date.now()
    try { cahier.value = await api('/cahiers', { method: 'POST', body: form }) }
    catch (e: any) { erreur.value = e.message }
    busy.value = false
  }
  const reprendre = () => { const c = cahier.value; cahier.value = null; return c }
  const effacerErreur = () => { erreur.value = '' }
  return { busy, nom, fichierNom, depart, cahier, erreur, lancer, reprendre, effacerErreur }
})

import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

/* La session vit dans l'ONGLET (sessionStorage) : un nouveau démarrage de l'application, un nouvel onglet ou la
   fermeture du navigateur ramènent toujours à la page de connexion. Un rechargement de la page garde la session.
   Les anciens jetons (localStorage, versions précédentes) sont supprimés : ils ne permettent plus d'entrer directement. */
try { localStorage.removeItem('token'); localStorage.removeItem('email'); localStorage.removeItem('projet_actif') } catch { /* stockage indisponible */ }

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(sessionStorage.getItem('token'))
  const email = ref<string>(sessionStorage.getItem('email') ?? '')
  const photo = ref<string | null>(null)          // adresse de la photo de profil (chargée depuis /compte/moi)
  const isAuthenticated = computed(() => !!token.value)

  function setSession(value: string, mail: string) {
    token.value = value
    email.value = mail
    sessionStorage.setItem('token', value)
    sessionStorage.setItem('email', mail)
    sessionStorage.removeItem('projet_actif')       // chaque connexion repart de la page de choix du projet
  }
  function logout() {
    token.value = null
    email.value = ''
    photo.value = null
    sessionStorage.removeItem('token')
    sessionStorage.removeItem('email')
    sessionStorage.removeItem('projet_actif')
  }
  return { token, email, photo, isAuthenticated, setSession, logout }
})

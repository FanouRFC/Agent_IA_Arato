import { onMounted, onUnmounted } from 'vue'

/** Fond blanc pour la page en cours (la classe est retirée en quittant la page). */
export function usePageBlanche() {
  onMounted(() => document.body.classList.add('page-blanche'))
  onUnmounted(() => document.body.classList.remove('page-blanche'))
}

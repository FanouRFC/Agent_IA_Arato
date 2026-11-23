import { onMounted, onUnmounted } from 'vue'

/** Exécute `fn` tout de suite puis à intervalle régulier ; en pause quand l'onglet est masqué. */
export function usePolling(fn: () => unknown, ms: number) {
  let timer: number | undefined
  const tick = () => { if (!document.hidden) fn() }
  onMounted(() => { fn(); timer = window.setInterval(tick, ms) })
  onUnmounted(() => window.clearInterval(timer))
}
